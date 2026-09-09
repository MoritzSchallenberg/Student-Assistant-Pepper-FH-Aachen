#!/usr/bin/env python3
"""
command_router_node: deterministischer Sprachbefehls-Router
(Entwicklungsauftrag 04-B, AP7, Abschnitt 10). Laeuft VOR jedem
LLM-Aufruf -- abonniert die bereits nach base_link transformierten
Codewort-/Befehlsereignisse (/interaction/command, siehe
sound_direction_transform_node.py) und trifft DIE Autorisierungs-
entscheidung (roles.py + authorization_policy.py), bevor irgendein
anderer Node auf diesen Befehl reagiert.

Das LLM erreicht diesen Pfad NIE -- es kann keinen Steuerbefehl
erfinden, keine Rolle bestimmen, keine Autorisierung erteilen, keine
Track-ID auswaehlen, keinen FollowPerson-Start ausloesen (kein Code-Pfad
von ihk_pepper_llm_contracts zu diesem Node oder umgekehrt).

EHRLICHER STAND: die "zusaetzliche Bestaetigung am Tablet oder durch
eine kurzzeitig freigegebene Mitarbeitersitzung" (Auftrag Abschnitt 8)
ist NOCH NICHT an eine echte Tablet-UI angebunden -- dieser Node
abonniert dafuer /authorization/secondary_confirmation (Bool) als
Platzhalter-Eingang, der aktuell von KEINEM echten UI-Node gesetzt wird
(bleibt also strukturell immer False, bis eine echte Bestaetigungsquelle
angebunden wird -- fail-closed, kein automatisches "true"). Ebenso ist
/identity/person_identities (PersonIdentityArray) aktuell von KEINEM
Identity-Node befuellt (siehe ihk_pepper_identity, Commit 3 -- die
Backend-Familie existiert, die Laufzeit-Verdrahtung folgt in einem
spaeteren Commit) -- follow_speaker bleibt deshalb bis dahin IMMER
"identity_unknown", NICHT stillschweigend autorisiert.
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool

from ihk_pepper_interfaces.msg import (
    AudioFocusState,
    InteractionCommand,
    PersonIdentityArray,
    SafetyState,
)

from .authorization_policy import POLICY_ROLE_ONLY_DEVELOPMENT, validate_policy
from .command_authorization_decision import decide_command_authorization
from .command_priority import priority_for_command
from .roles import ROLE_STUDENT


class CommandRouterNode(Node):
    def __init__(self):
        super().__init__("command_router")

        self.declare_parameter("production_mode", False)
        self.declare_parameter("privileged_motion_policy", POLICY_ROLE_ONLY_DEVELOPMENT)
        self.declare_parameter("minimum_recognition_confidence", 0.8)

        policy = self.get_parameter("privileged_motion_policy").value
        production_mode = self.get_parameter("production_mode").value
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 8: role_only_development
        # ist in Produktion hart gesperrt -- derselbe Start-Guard wie
        # audio_node.py::activation_mode/production_mode.
        validate_policy(policy, production_mode)

        self._latest_identities: PersonIdentityArray = None
        self._latest_focus_track_id = -1
        self._safety_state: SafetyState = None
        self._secondary_confirmation_valid = False

        self.command_pub = self.create_publisher(
            InteractionCommand, "/interaction/authorized_command", 10)

        self.create_subscription(InteractionCommand, "/interaction/command", self._on_command, 10)
        self.create_subscription(AudioFocusState, "/audio/focus_state", self._on_focus_state, 10)
        self.create_subscription(
            PersonIdentityArray, "/identity/person_identities", self._on_identities, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)
        # Platzhalter, siehe Moduldoku -- KEIN echter UI-Node setzt dies
        # bislang, bleibt also strukturell immer False.
        self.create_subscription(
            Bool, "/authorization/secondary_confirmation", self._on_secondary_confirmation, 10)

        self.get_logger().info(
            f"command_router gestartet (privileged_motion_policy={policy}, "
            f"production_mode={production_mode})."
        )

    def _on_focus_state(self, msg: AudioFocusState):
        self._latest_focus_track_id = msg.selected_track_id if msg.valid else -1

    def _on_identities(self, msg: PersonIdentityArray):
        self._latest_identities = msg

    def _on_safety_state(self, msg: SafetyState):
        self._safety_state = msg

    def _on_secondary_confirmation(self, msg: Bool):
        self._secondary_confirmation_valid = msg.data

    def _lookup_identity(self, track_id: int):
        """Gibt (known, person_id, role, confidence, liveness_passed)
        zurueck -- known=False/role=ROLE_STUDENT fail-closed, wenn keine
        aktuelle PersonIdentityArray existiert ODER kein Eintrag zum
        track_id passt (siehe Moduldoku: aktuell IMMER dieser Fall, bis
        ein echter Identity-Node verdrahtet ist)."""
        if track_id < 0 or self._latest_identities is None:
            return False, "", ROLE_STUDENT, 0.0, False
        for identity in self._latest_identities.identities:
            if int(identity.track_id) == track_id:
                return (
                    identity.known and identity.consent_granted, identity.person_id,
                    identity.role, identity.recognition_confidence, identity.liveness_passed,
                )
        return False, "", ROLE_STUDENT, 0.0, False

    def _safety_state_valid(self) -> bool:
        return self._safety_state is not None and self._safety_state.allow_person_approach

    def _on_command(self, msg: InteractionCommand):
        track_id = msg.track_id if msg.track_id >= 0 else self._latest_focus_track_id
        known_identity, person_id, role, confidence, liveness_passed = self._lookup_identity(track_id)

        decision = decide_command_authorization(
            command=msg.command,
            policy=self.get_parameter("privileged_motion_policy").value,
            known_identity=known_identity,
            role=role,
            recognition_confidence=confidence,
            minimum_confidence=self.get_parameter("minimum_recognition_confidence").value,
            liveness_passed=liveness_passed,
            speaking_track_id=track_id,
            identity_track_id=track_id,
            secondary_confirmation_valid=self._secondary_confirmation_valid,
            safety_state_valid=self._safety_state_valid(),
        )

        out = InteractionCommand()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = msg.header.frame_id
        out.event_id = msg.event_id
        out.command = msg.command
        out.raw_transcript = msg.raw_transcript
        out.direction_azimuth_rad_base = msg.direction_azimuth_rad_base
        out.direction_valid = msg.direction_valid
        out.track_id = track_id
        out.person_id = person_id
        out.role = decision.role
        out.confidence = confidence
        out.authorization_status = decision.authorization_status
        out.priority = priority_for_command(msg.command)
        out.reason = decision.reason
        self.command_pub.publish(out)

        if decision.authorization_status == "denied":
            self.get_logger().info(
                f"Befehl '{msg.command}' (event_id={msg.event_id}) abgelehnt: {decision.reason}")


def main(args=None):
    rclpy.init(args=args)
    node = CommandRouterNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
