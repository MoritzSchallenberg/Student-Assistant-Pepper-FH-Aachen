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
angebunden wird -- fail-closed, kein automatisches "true"). Wird durch
eine ereignisgebundene, an Person/Track/Befehl/Sitzung gebundene
Autorisierung ersetzt (Entwicklungsauftrag 04-B, AP7.1, Abschnitt 3.2/9
-- folgt in einem spaeteren Commit dieses Arbeitspakets).

Entwicklungsauftrag 04-B, AP7.1, Abschnitt 8 (WICHTIG): PersonIdentity.role
wird HIER NICHT MEHR gelesen/vertraut -- face_identity_node.py (jetzt
verdrahtet, siehe ihk_pepper_identity) setzt dieses Feld absichtlich
nur auf einen sicheren Platzhalter. Die tatsaechliche Rolle kommt
AUSSCHLIESSLICH aus role_resolution.py, das direkt an eine eigene
identity_registry_db.py-Instanz dieses Nodes gebunden ist (siehe
_get_effective_role()) -- eine Vermischung von Identitaet und Rolle
(Auftrag Abschnitt 8: "Das LLM darf keine Rolle setzen, erhoehen oder
bestaetigen" gilt sinngemaess auch fuer jeden anderen nicht
vertrauenswuerdigen Kanal) ist damit strukturell ausgeschlossen.
"""
import time
import uuid

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool

from ihk_pepper_interfaces.msg import (
    AudioFocusState,
    AuthorizationGrant,
    InteractionCommand,
    PersonIdentityArray,
    SafetyState,
)
from ihk_pepper_interfaces.srv import GetEffectiveRole

from .authorization_policy import POLICY_ROLE_ONLY_DEVELOPMENT, validate_policy
from .command_authorization_decision import decide_command_authorization
from .command_priority import priority_for_command
from .role_resolution import resolve_role
from .roles import ROLE_STUDENT


def _seconds_to_stamp(seconds: float):
    from builtin_interfaces.msg import Time as TimeMsg
    stamp = TimeMsg()
    stamp.sec = int(seconds)
    stamp.nanosec = int((seconds % 1) * 1e9)
    return stamp


class CommandRouterNode(Node):
    def __init__(self):
        super().__init__("command_router")

        self.declare_parameter("production_mode", False)
        self.declare_parameter("privileged_motion_policy", POLICY_ROLE_ONLY_DEVELOPMENT)
        self.declare_parameter("minimum_recognition_confidence", 0.8)
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9/19: kurzlebige
        # Referenz-ID, an person_id+track_id+command GEBUNDEN -- der
        # eigentliche Verbraucher (person_approach_node.py::FollowPerson)
        # validiert ausschliesslich gegen eine per Topic empfangene Kopie
        # dieses Grants, kein gemeinsamer Prozessspeicher noetig.
        self.declare_parameter("grant_validity_s", 30.0)

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
        self.grant_pub = self.create_publisher(AuthorizationGrant, "/authorization/grants", 10)

        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 8: Rollenaufloesung
        # AUSSCHLIESSLICH ueber diesen Service (person_memory_node.py),
        # NIE ueber PersonIdentity.role direkt (siehe role_resolution.py-
        # Moduldoku) -- ein Service statt eines direkten DB-Imports, um
        # keine zirkulaere Paketabhaengigkeit zu ihk_pepper_person_memory
        # zu erzeugen (das bereits von diesem Paket abhaengt, siehe
        # roles.py).
        self.role_lookup_client = self.create_client(GetEffectiveRole, "/get_effective_role")

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

    def _get_effective_role(self, person_id: str, now=None) -> str:
        """Ruft /get_effective_role auf (person_memory_node.py) --
        wirft bei jedem Fehler (Service nicht erreichbar, Timeout),
        role_resolution.py::resolve_role() faengt das ab und faellt auf
        ROLE_STUDENT zurueck. NIEMALS PersonIdentity.role verwenden,
        siehe Moduldoku."""
        if not self.role_lookup_client.wait_for_service(timeout_sec=0.5):
            raise RuntimeError("get_effective_role Service nicht erreichbar")
        request = GetEffectiveRole.Request()
        request.person_id = person_id
        future = self.role_lookup_client.call_async(request)
        deadline = time.time() + 1.0
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            raise RuntimeError("get_effective_role Zeitueberschreitung")
        return future.result().role

    def _lookup_identity(self, track_id: int):
        """Gibt (known, person_id, role, confidence, liveness_passed)
        zurueck -- known=False/role=ROLE_STUDENT fail-closed, wenn keine
        aktuelle PersonIdentityArray existiert ODER kein Eintrag zum
        track_id passt. Die Rolle kommt AUSSCHLIESSLICH aus
        role_resolution.py/_get_effective_role() -- identity.role (aus
        /identity/person_identities) wird bewusst NIE gelesen (siehe
        Moduldoku, Auftrag Abschnitt 8/AP7.1.4)."""
        if track_id < 0 or self._latest_identities is None:
            return False, "", ROLE_STUDENT, 0.0, False
        for identity in self._latest_identities.identities:
            if int(identity.track_id) == track_id:
                known = identity.known and identity.consent_granted
                role = resolve_role(
                    known=known, consent_granted=identity.consent_granted,
                    person_id=identity.person_id,
                    get_effective_role_fn=self._get_effective_role,
                )
                return (
                    known, identity.person_id, role,
                    identity.recognition_confidence, identity.liveness_passed,
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
        elif decision.authorization_status == "granted":
            self._issue_grant(person_id, track_id, msg.command)

    def _issue_grant(self, person_id: str, track_id: int, command: str):
        """Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9: kurzlebig, an
        person_id+track_id+command GEBUNDEN -- veroeffentlicht KEINEN
        geheimen Schluessel, nur eine zufaellige Referenz-ID. Der
        Verbraucher (person_approach_node.py) validiert genau diese
        Bindung, siehe authorization_grant_cache.py."""
        now_s = time.time()
        validity_s = self.get_parameter("grant_validity_s").value
        grant = AuthorizationGrant()
        grant.grant_id = str(uuid.uuid4())
        grant.person_id = person_id
        grant.track_id = track_id
        grant.command = command
        grant.session_id = ""  # Sitzungsbindung folgt mit InteractionSession, AP7 Commit 9
        grant.created_at = _seconds_to_stamp(now_s)
        grant.expires_at = _seconds_to_stamp(now_s + validity_s)
        grant.valid = True
        grant.reason = ""
        self.grant_pub.publish(grant)


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
