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

Entwicklungsauftrag 04-B, AP7.1, Abschnitt 9 (WICHTIG): die bisherige
globale /authorization/secondary_confirmation-Bool-Nachricht ist
ENTFERNT -- eine einzelne geteilte Bool-Nachricht konnte nicht
beweisen, welche Person/welcher Track/welcher Befehl/welche Sitzung
bestaetigt wurde (Auftrag Abschnitt 3.2). Ersetzt durch eine
ereignisgebundene Anfrage/Antwort-Autorisierung (scoped_authorization.py):
sobald ein privilegierter Befehl ALLE anderen Bedingungen erfuellt und
NUR noch eine sekundaere Bestaetigung fehlt, wird ein
AuthorizationRequest veroeffentlicht (`authorization_status =
"pending_confirmation"`), der EINMALIG per ConfirmAuthorization.srv
(an request_id+nonce gebunden, z.B. vom Tablet, siehe
apps/web/tablet/ros_bridge.py) entschieden werden kann. Ein
abgelaufener, unbeantworteter Request wird periodisch bereinigt und als
abgelehnt gemeldet -- niemals eine stillschweigende Freigabe.

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
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node

from ihk_pepper_interfaces.msg import (
    AudioFocusState,
    AuthorizationDecision,
    AuthorizationGrant,
    AuthorizationRequest,
    InteractionCommand,
    PersonIdentityArray,
    SafetyState,
)
from ihk_pepper_interfaces.srv import ConfirmAuthorization, GetEffectiveRole

from .authorization_policy import POLICY_ROLE_ONLY_DEVELOPMENT, validate_policy
from .command_authorization_decision import (
    AUTHORIZATION_DENIED,
    AUTHORIZATION_GRANTED,
    CommandDecision,
    decide_command_authorization,
)
from .command_priority import priority_for_command
from .role_resolution import resolve_role
from .roles import ROLE_STUDENT
from .scoped_authorization import CurrentContext, ScopedAuthorizationStore


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
        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 9: wie lange ein
        # AuthorizationRequest auf eine Entscheidung wartet, bevor er
        # als abgelehnt gilt ("Timeout... bedeutet Ablehnung").
        self.declare_parameter("secondary_confirmation_validity_s", 60.0)
        self.declare_parameter("authorization_request_purge_interval_s", 2.0)
        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 8: Zeitbudget fuer
        # /get_effective_role -- ein zu kurzes Zeitfenster wuerde bei
        # normaler ROS2-Graph-/Discovery-Latenz faelschlich auf STUDENT
        # zurueckfallen, obwohl der Service tatsaechlich erreichbar
        # gewesen waere (fail-closed bleibt korrekt, aber unnoetig
        # streng). 1.5s deckt normale Anlaufzeiten ab, ohne die
        # Befehlsverarbeitung spuerbar zu verzoegern.
        self.declare_parameter("role_lookup_timeout_s", 1.5)

        policy = self.get_parameter("privileged_motion_policy").value
        production_mode = self.get_parameter("production_mode").value
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 8: role_only_development
        # ist in Produktion hart gesperrt -- derselbe Start-Guard wie
        # audio_node.py::activation_mode/production_mode.
        validate_policy(policy, production_mode)

        self._latest_identities: PersonIdentityArray = None
        self._latest_focus_track_id = -1
        self._safety_state: SafetyState = None
        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 9: ersetzt die
        # bisherige globale self._secondary_confirmation_valid-Bool.
        # _pending_context haelt die ORIGINAL-InteractionCommand-Nachricht
        # + track_id zu einem noch offenen request_id, damit
        # _on_confirm_authorization() nach einer erfolgreichen
        # Bestaetigung dieselbe Entscheidung fertig treffen kann.
        self._authorization_store = ScopedAuthorizationStore()
        self._pending_context: dict = {}

        self.command_pub = self.create_publisher(
            InteractionCommand, "/interaction/authorized_command", 10)
        self.grant_pub = self.create_publisher(AuthorizationGrant, "/authorization/grants", 10)
        self.auth_request_pub = self.create_publisher(
            AuthorizationRequest, "/authorization/requests", 10)
        self.auth_decision_pub = self.create_publisher(
            AuthorizationDecision, "/authorization/decisions", 10)

        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 8: Rollenaufloesung
        # AUSSCHLIESSLICH ueber diesen Service (person_memory_node.py),
        # NIE ueber PersonIdentity.role direkt (siehe role_resolution.py-
        # Moduldoku) -- ein Service statt eines direkten DB-Imports, um
        # keine zirkulaere Paketabhaengigkeit zu ihk_pepper_person_memory
        # zu erzeugen (das bereits von diesem Paket abhaengt, siehe
        # roles.py). ReentrantCallbackGroup, NICHT der Default
        # (MutuallyExclusive): _on_command()/_on_confirm_authorization()
        # blockieren auf die Antwort dieses Clients -- mit dem Default
        # wuerde die eigene Warteschleife den einzigen Thread belegen,
        # der die Antwort ueberhaupt verarbeiten koennte (echter
        # Deadlock/Timeout, per Live-Test gefunden, siehe main()).
        cb_group = ReentrantCallbackGroup()
        self.role_lookup_client = self.create_client(
            GetEffectiveRole, "/get_effective_role", callback_group=cb_group)
        self.confirm_srv = self.create_service(
            ConfirmAuthorization, "confirm_authorization", self._on_confirm_authorization,
            callback_group=cb_group)

        self.create_subscription(
            InteractionCommand, "/interaction/command", self._on_command, 10,
            callback_group=cb_group)
        self.create_subscription(AudioFocusState, "/audio/focus_state", self._on_focus_state, 10)
        self.create_subscription(
            PersonIdentityArray, "/identity/person_identities", self._on_identities, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)

        self.create_timer(
            self.get_parameter("authorization_request_purge_interval_s").value,
            self._purge_expired_requests)

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

    def _get_effective_role(self, person_id: str, now=None) -> str:
        """Ruft /get_effective_role auf (person_memory_node.py) --
        wirft bei jedem Fehler (Service nicht erreichbar, Timeout),
        role_resolution.py::resolve_role() faengt das ab und faellt auf
        ROLE_STUDENT zurueck. NIEMALS PersonIdentity.role verwenden,
        siehe Moduldoku."""
        timeout_s = self.get_parameter("role_lookup_timeout_s").value
        if not self.role_lookup_client.wait_for_service(timeout_sec=timeout_s):
            raise RuntimeError("get_effective_role Service nicht erreichbar")
        request = GetEffectiveRole.Request()
        request.person_id = person_id
        future = self.role_lookup_client.call_async(request)
        deadline = time.time() + timeout_s
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

        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 9: zweifach mit
        # secondary_confirmation_valid=False/True auswerten, um
        # herauszufinden, ob die sekundaere Bestaetigung ueberhaupt der
        # AUSSCHLAGGEBENDE fehlende Faktor ist -- decide_command_authorization()
        # kennt selbst keine "pending"-Zwischenstufe, die wird hier
        # daraus abgeleitet, statt die Funktion selbst zu aendern.
        common_kwargs = dict(
            command=msg.command,
            policy=self.get_parameter("privileged_motion_policy").value,
            known_identity=known_identity,
            role=role,
            recognition_confidence=confidence,
            minimum_confidence=self.get_parameter("minimum_recognition_confidence").value,
            liveness_passed=liveness_passed,
            speaking_track_id=track_id,
            identity_track_id=track_id,
            safety_state_valid=self._safety_state_valid(),
        )
        without_confirmation = decide_command_authorization(
            secondary_confirmation_valid=False, **common_kwargs)
        if without_confirmation.authorization_status == AUTHORIZATION_GRANTED:
            # Rollenfrei (NOT_REQUIRED) oder eine Policy, die
            # secondary_confirmation_valid gar nicht auswertet (z.B.
            # POLICY_ROLE_ONLY_DEVELOPMENT) -- schon OHNE jede
            # Bestaetigung erlaubt, kein Grund zu warten.
            self._publish_final_command_decision(
                msg, track_id, person_id, confidence, without_confirmation)
            return

        with_confirmation = decide_command_authorization(
            secondary_confirmation_valid=True, **common_kwargs)
        if with_confirmation.authorization_status != AUTHORIZATION_GRANTED:
            # Selbst MIT einer angenommenen gueltigen Bestaetigung bleibt
            # es abgelehnt (oder weiterhin rollenfrei) -- ein anderer
            # Grund als die fehlende Bestaetigung ist ausschlaggebend,
            # die Entscheidung ist endgueltig.
            self._publish_final_command_decision(
                msg, track_id, person_id, confidence, with_confirmation)
            return

        record = self._authorization_store.create_request(
            event_id=msg.event_id, interaction_id="", session_id="",
            track_id=track_id, person_id=person_id, role=role, command=msg.command,
            requested_capability=msg.command, reason="privilegierter_befehl_braucht_bestaetigung",
            validity_s=self.get_parameter("secondary_confirmation_validity_s").value,
        )
        self._pending_context[record.request_id] = (msg, track_id)
        self._publish_authorization_request(record)

        out = self._build_command_out(msg, track_id, person_id, role, confidence)
        out.authorization_status = "pending_confirmation"
        out.reason = "warte_auf_zusatzbestaetigung"
        self.command_pub.publish(out)
        self.get_logger().info(
            f"Befehl '{msg.command}' (event_id={msg.event_id}) wartet auf "
            f"Zusatzbestaetigung (request_id={record.request_id})."
        )

    def _on_confirm_authorization(self, request, response):
        """ConfirmAuthorization.srv-Handler (Auftrag Abschnitt 9). Der
        EINZIGE Weg, einen offenen AuthorizationRequest zu entscheiden --
        prueft IMMER gegen den AKTUELLEN Zustand (Track/Person/Rolle/
        Sicherheit), nicht gegen den Stand zum Zeitpunkt der Anfrage."""
        pending = self._pending_context.get(request.request_id)
        if pending is None:
            response.success = False
            response.reason = "request_unbekannt_oder_bereits_verwendet"
            return response
        msg, track_id = pending

        known_identity, person_id, role, confidence, liveness_passed = self._lookup_identity(track_id)
        current = CurrentContext(
            track_id=track_id, person_id=person_id, role=role, command=msg.command,
            session_id="", safety_state_valid=self._safety_state_valid(),
        )
        ok, reason = self._authorization_store.confirm(
            request.request_id, request.nonce, request.approve, current)
        self._pending_context.pop(request.request_id, None)
        self._publish_authorization_decision(request.request_id, ok, reason)
        response.success = ok
        response.reason = reason

        if not ok:
            self._publish_final_command_decision(
                msg, track_id, person_id, confidence,
                CommandDecision(AUTHORIZATION_DENIED, role, reason))
            return response

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
            secondary_confirmation_valid=True,
            safety_state_valid=current.safety_state_valid,
        )
        self._publish_final_command_decision(msg, track_id, person_id, confidence, decision)
        return response

    def _purge_expired_requests(self):
        """Auftrag Abschnitt 9/10: 'Timeout... bedeutet Ablehnung' --
        ein nie beantworteter Request wird nach Ablauf seiner
        Gueltigkeit als abgelehnt gemeldet, nicht stillschweigend
        vergessen."""
        for request_id in self._authorization_store.purge_expired():
            self._pending_context.pop(request_id, None)
            self._publish_authorization_decision(request_id, False, "request_abgelaufen")

    def _build_command_out(self, msg: InteractionCommand, track_id: int, person_id: str,
                            role: str, confidence: float) -> InteractionCommand:
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
        out.role = role
        out.confidence = confidence
        out.priority = priority_for_command(msg.command)
        return out

    def _publish_final_command_decision(self, msg: InteractionCommand, track_id: int,
                                         person_id: str, confidence: float,
                                         decision: CommandDecision):
        out = self._build_command_out(msg, track_id, person_id, decision.role, confidence)
        out.authorization_status = decision.authorization_status
        out.reason = decision.reason
        self.command_pub.publish(out)

        if decision.authorization_status == AUTHORIZATION_DENIED:
            self.get_logger().info(
                f"Befehl '{msg.command}' (event_id={msg.event_id}) abgelehnt: {decision.reason}")
        elif decision.authorization_status == AUTHORIZATION_GRANTED:
            self._issue_grant(person_id, track_id, msg.command)

    def _publish_authorization_request(self, record):
        req = AuthorizationRequest()
        req.request_id = record.request_id
        req.event_id = record.event_id
        req.interaction_id = record.interaction_id
        req.session_id = record.session_id
        req.track_id = record.track_id
        req.person_id = record.person_id
        req.role = record.role
        req.command = record.command
        req.requested_capability = record.requested_capability
        req.created_at = _seconds_to_stamp(record.created_at_s)
        req.expires_at = _seconds_to_stamp(record.expires_at_s)
        req.nonce = record.nonce
        req.reason = record.reason
        self.auth_request_pub.publish(req)

    def _publish_authorization_decision(self, request_id: str, confirmed: bool, reason: str):
        decision = AuthorizationDecision()
        decision.request_id = request_id
        decision.confirmed = confirmed
        decision.reason = reason
        decision.decided_at = _seconds_to_stamp(time.time())
        self.auth_decision_pub.publish(decision)

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
    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 8: _get_effective_role()
    # blockiert innerhalb von _on_command()/_on_confirm_authorization()
    # auf die Antwort eines eigenen Service-Aufrufs (/get_effective_role).
    # Mit einem einfachen rclpy.spin() (SingleThreadedExecutor) wuerde
    # das den EINZIGEN Thread blockieren, der die Antwort ueberhaupt
    # verarbeiten koennte -- echter Deadlock/Timeout, per Live-Test
    # gefunden. MultiThreadedExecutor behebt das (gleiches Prinzip wie
    # person_approach_node.py/face_identity_node.py).
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
