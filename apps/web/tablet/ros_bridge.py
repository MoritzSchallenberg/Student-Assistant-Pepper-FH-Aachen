"""
Tablet<->ROS2-Bruecke fuer die erweiterte Tablet-Oberflaeche
(Entwicklungsauftrag Abschnitt 20; sichere Bestaetigungsansicht:
Entwicklungsauftrag 04-B, AP7.1, Abschnitt 10/AP7.1.6).

Laeuft als rclpy-Node in einem Hintergrund-Thread INNERHALB des
apps/web-Prozesses (Flask selbst bleibt unveraendert lauffaehig auch
ohne ROS2 -- siehe _try_import_rclpy()). Stellt read-only Snapshots der
relevanten ROS2-Topics bereit sowie feste, allowlist-gebundene
schreibende Aktionen (Auftrag Abschnitt 3.4 -- niemals Freitext/LLM-Text
direkt in ROS-Befehle):
    - request_control(cmd) : nur "pause"|"resume"|"repeat", published auf
      /presentation_control (String)
    - request_stop()       : ruft /cancel_interaction (CancelInteraction)
      und /play_presentation/_action/cancel_goal (generischer
      Action-Cancel-Service, funktioniert unabhaengig davon wer das Ziel
      gesendet hat) -- beides feste ROS2-Service-Aufrufe, kein Shell/Text.
    - confirm_authorization(request_id, nonce, approve): ruft
      /confirm_authorization (ConfirmAuthorization.srv,
      command_router_node.py) auf -- das Tablet kann NUR den aktuell
      angezeigten AuthorizationRequest bestaetigen/ablehnen, NIEMALS
      selbst eine Rolle setzen oder einen eigenen AuthorizationGrant
      erzeugen (das bleibt ausschliesslich command_router_node.py
      vorbehalten, siehe scoped_authorization.py). request_id+nonce
      werden IMMER frisch aus /authorization/requests gelesen -- eine
      alte Browserseite, die einen laengst entschiedenen/abgelaufenen
      request_id einsendet, wird server-seitig abgelehnt
      ("request_unbekannt_oder_bereits_verwendet"/"request_abgelaufen").

WICHTIG (Betrieb): Damit rclpy + die eigenen Interfaces
(ihk_pepper_interfaces) in der apps/web-venv importierbar sind, MUSS
vor dem Start von app.py folgendes gesourced sein:
    source /opt/ros/jazzy/setup.bash
    source <pfad-zu>/ros2/autonomy_ws/install/setup.bash
Fehlt das, startet Flask trotzdem normal -- die Tablet-Seite zeigt dann
dauerhaft den "offline"-Zustand (getestet, siehe docs/IMPLEMENTATION_REPORT.md).
"""
import json
import threading
import time


def _try_import_ros():
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.executors import SingleThreadedExecutor
        from std_msgs.msg import String, UInt8
        from ihk_pepper_interfaces.msg import (
            AuthorizationDecision, AuthorizationRequest, DialogueState, PresentationState, SafetyState,
        )
        from ihk_pepper_interfaces.srv import CancelInteraction, ConfirmAuthorization
        from action_msgs.srv import CancelGoal
        return {
            "rclpy": rclpy, "Node": Node, "SingleThreadedExecutor": SingleThreadedExecutor,
            "String": String, "UInt8": UInt8, "DialogueState": DialogueState,
            "PresentationState": PresentationState, "SafetyState": SafetyState,
            "AuthorizationRequest": AuthorizationRequest, "AuthorizationDecision": AuthorizationDecision,
            "CancelInteraction": CancelInteraction, "CancelGoal": CancelGoal,
            "ConfirmAuthorization": ConfirmAuthorization,
        }
    except Exception:
        return None


STALE_AFTER_S = 5.0  # Kein Update seit N Sekunden -> Topic gilt als "offline"

# Erlaubte presentation_control-Kommandos (Abschnitt 3.4: fester Allowlist,
# niemals Freitext durchreichen).
ALLOWED_CONTROL_COMMANDS = ("pause", "resume", "repeat")

# Gleiches Vokabular wie ihk_pepper_audio/cancel_words.py -- das Tablet ist
# damit einfach eine zweite Eingabequelle fuer denselben festen Kanal wie
# Sprachbefehle (/audio_node/voice_command). dialog_manager_node setzt
# aktuell nur "stop"/"cancel" vollstaendig um, der Rest wird geloggt
# (siehe dialog_manager_node.py _on_voice_command) -- hier bewusst
# trotzdem durchgereicht statt weggelassen, damit es sofort mitfunktioniert
# sobald diese Umsetzung nachgezogen wird.
ALLOWED_VOICE_COMMANDS = ("stop", "cancel", "quiet", "repeat", "volume_up", "volume_down")


class TabletRosBridge:
    def __init__(self):
        self._mods = _try_import_ros()
        self.available = self._mods is not None
        self._lock = threading.Lock()
        self._data = {
            "dialogue_state": None, "dialogue_state_t": 0.0,
            "presentation_state": None, "presentation_state_t": 0.0,
            "safety_state": None, "safety_state_t": 0.0,
            "interaction_state_name": None, "interaction_state_t": 0.0,
            "tablet_command": None, "tablet_command_t": 0.0,
            # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 10: der aktuell
            # offene AuthorizationRequest (oder None). NICHT staleness-
            # gefiltert wie die anderen Felder -- ein Request hat seine
            # EIGENE server-seitige expires_at, siehe get_snapshot().
            "pending_authorization": None, "pending_authorization_t": 0.0,
        }
        self._node = None
        self._executor = None
        self._thread = None
        self._control_pub = None
        self._voice_command_pub = None
        self._cancel_interaction_client = None
        self._cancel_presentation_client = None
        self._confirm_authorization_client = None

        if not self.available:
            print("tablet_ros_bridge: rclpy/ihk_pepper_interfaces nicht importierbar -- "
                  "Tablet-UI laeuft im 'offline'-Modus (siehe Moduldoku).")

    def start(self):
        if not self.available:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        m = self._mods
        try:
            m["rclpy"].init(args=None)
            node = m["Node"]("flask_tablet_bridge")
            self._node = node

            node.create_subscription(
                m["DialogueState"], "/dialogue_state",
                lambda msg: self._store("dialogue_state", self._dialogue_to_dict(msg)), 10)
            node.create_subscription(
                m["PresentationState"], "/presentation_state",
                lambda msg: self._store("presentation_state", self._presentation_to_dict(msg)), 10)
            node.create_subscription(
                m["SafetyState"], "/safety_state",
                lambda msg: self._store("safety_state", self._safety_to_dict(msg)), 10)
            node.create_subscription(
                m["String"], "/interaction_state_name",
                lambda msg: self._store("interaction_state_name", msg.data), 10)
            node.create_subscription(
                m["String"], "/tablet_command",
                lambda msg: self._store("tablet_command", self._safe_json(msg.data)), 10)
            node.create_subscription(
                m["AuthorizationRequest"], "/authorization/requests",
                lambda msg: self._store("pending_authorization", self._authorization_request_to_dict(msg)), 10)
            node.create_subscription(
                m["AuthorizationDecision"], "/authorization/decisions",
                self._on_authorization_decision, 10)

            self._control_pub = node.create_publisher(m["String"], "/presentation_control", 10)
            self._voice_command_pub = node.create_publisher(m["String"], "/audio_node/voice_command", 10)
            self._cancel_interaction_client = node.create_client(
                m["CancelInteraction"], "/cancel_interaction")
            self._cancel_presentation_client = node.create_client(
                m["CancelGoal"], "/play_presentation/_action/cancel_goal")
            self._confirm_authorization_client = node.create_client(
                m["ConfirmAuthorization"], "/confirm_authorization")

            self._executor = m["SingleThreadedExecutor"]()
            self._executor.add_node(node)
            self._executor.spin()
        except Exception as e:
            print(f"tablet_ros_bridge: Hintergrund-Thread beendet mit Fehler: {e}")

    def stop(self):
        if not self.available or self._node is None:
            return
        try:
            if self._executor:
                self._executor.shutdown()
            self._node.destroy_node()
            self._mods["rclpy"].shutdown()
        except Exception:
            pass

    # ---- Konvertierung ROS-Msg -> dict (json-serialisierbar) ----

    @staticmethod
    def _safe_json(s):
        try:
            return json.loads(s)
        except Exception:
            return None

    def _dialogue_to_dict(self, msg):
        return {
            "state": msg.state, "state_name": msg.state_name,
            "session_id": msg.session_id, "last_transcript": msg.last_transcript,
            "last_response": msg.last_response, "error_message": msg.error_message,
        }

    def _presentation_to_dict(self, msg):
        return {
            "state": msg.state, "state_name": msg.state_name,
            "topic_id": msg.topic_id, "progress_seconds": msg.progress_seconds,
        }

    def _safety_to_dict(self, msg):
        return {
            "allow_motion": msg.allow_motion, "emergency_stop": msg.emergency_stop,
            "bumper_active": msg.bumper_active, "reason": msg.reason,
        }

    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 10: menschenlesbare
    # Beschreibung der "beabsichtigten Roboteraktion" -- feste Abbildung,
    # kein Freitext (Auftrag Abschnitt 3.4).
    _ACTION_DESCRIPTIONS = {
        "follow_speaker": "Pepper folgt dieser Person durch den Raum.",
    }

    @staticmethod
    def _stamp_to_epoch_s(stamp) -> float:
        return stamp.sec + stamp.nanosec / 1e9

    def _authorization_request_to_dict(self, msg):
        return {
            "request_id": msg.request_id,
            "nonce": msg.nonce,
            "person_id": msg.person_id,
            "known": bool(msg.person_id),
            "role": msg.role,
            "command": msg.command,
            "action_description": self._ACTION_DESCRIPTIONS.get(
                msg.command, f"Privilegierter Befehl: {msg.command}"),
            "created_at_s": self._stamp_to_epoch_s(msg.created_at),
            "expires_at_s": self._stamp_to_epoch_s(msg.expires_at),
        }

    def _on_authorization_decision(self, msg):
        # Sobald IRGENDEINE Entscheidung fuer den aktuell angezeigten
        # Request eintrifft (vom Tablet selbst bestaetigt, von woanders
        # entschieden, oder serverseitig abgelaufen), verschwindet die
        # Bestaetigungsansicht -- niemals ein bereits entschiedener
        # Request weiter anzeigen.
        with self._lock:
            current = self._data.get("pending_authorization")
            if current and current.get("request_id") == msg.request_id:
                self._data["pending_authorization"] = None
                self._data["pending_authorization_t"] = time.time()

    def _store(self, key, value):
        with self._lock:
            self._data[key] = value
            self._data[key + "_t"] = time.time()

    # ---- Oeffentliche, read-only API fuer Flask-Routen ----

    def get_snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            d = dict(self._data)

        def fresh(key):
            t = d.get(key + "_t", 0.0)
            return t > 0 and (now - t) < STALE_AFTER_S

        pending_auth = d.get("pending_authorization")
        if pending_auth is not None and now > pending_auth.get("expires_at_s", 0.0):
            # Server-seitig laengst abgelaufen (command_router_node.py
            # hat es bereits bereinigt und eine AuthorizationDecision
            # veroeffentlicht) -- niemals einen abgelaufenen Request
            # weiter als aktuell anzeigen, selbst wenn die Decision-
            # Nachricht aus irgendeinem Grund nicht angekommen sein sollte.
            pending_auth = None

        return {
            "bridge_available": self.available,
            "dialogue_state": d["dialogue_state"] if fresh("dialogue_state") else None,
            "presentation_state": d["presentation_state"] if fresh("presentation_state") else None,
            "safety_state": d["safety_state"] if fresh("safety_state") else None,
            "interaction_state_name": d["interaction_state_name"] if fresh("interaction_state_name") else None,
            "tablet_command": d["tablet_command"] if fresh("tablet_command") else None,
            "pending_authorization": pending_auth,
            "server_time": now,
        }

    # ---- Feste Allowlist-Aktionen (Abschnitt 3.4) ----

    def request_control(self, cmd: str) -> (bool, str):
        if cmd not in ALLOWED_CONTROL_COMMANDS:
            return False, f"Befehl nicht erlaubt: {cmd}"
        if not self.available or self._control_pub is None:
            return False, "ROS2-Bruecke nicht verfuegbar"
        self._control_pub.publish(self._mods["String"](data=cmd))
        return True, "OK"

    def request_voice_command(self, cmd: str) -> (bool, str):
        if cmd not in ALLOWED_VOICE_COMMANDS:
            return False, f"Befehl nicht erlaubt: {cmd}"
        if not self.available or self._voice_command_pub is None:
            return False, "ROS2-Bruecke nicht verfuegbar"
        self._voice_command_pub.publish(self._mods["String"](data=cmd))
        return True, "OK"

    def request_stop(self) -> (bool, str):
        if not self.available:
            return False, "ROS2-Bruecke nicht verfuegbar"
        messages = []
        try:
            if self._cancel_interaction_client.wait_for_service(timeout_sec=1.0):
                req = self._mods["CancelInteraction"].Request()
                req.reason = "tablet_stop_button"
                self._cancel_interaction_client.call_async(req)
                messages.append("cancel_interaction angefragt")
            else:
                messages.append("cancel_interaction nicht erreichbar")
        except Exception as e:
            messages.append(f"cancel_interaction Fehler: {e}")

        try:
            if self._cancel_presentation_client.wait_for_service(timeout_sec=1.0):
                req = self._mods["CancelGoal"].Request()  # leere GoalInfo = alle Ziele abbrechen
                self._cancel_presentation_client.call_async(req)
                messages.append("play_presentation Cancel angefragt")
            else:
                messages.append("play_presentation Cancel-Service nicht erreichbar")
        except Exception as e:
            messages.append(f"play_presentation Cancel Fehler: {e}")

        return True, "; ".join(messages)

    def confirm_authorization(self, request_id: str, nonce: str, approve: bool) -> (bool, str):
        """Entwicklungsauftrag 04-B, AP7.1, Abschnitt 10: bestaetigt/
        lehnt EINEN AuthorizationRequest ab -- ruft ausschliesslich
        /confirm_authorization auf (command_router_node.py trifft die
        eigentliche Entscheidung, prueft Ablauf/Wiederverwendung/
        Track-Wechsel/Sicherheitszustand erneut). Dieses Tablet kann
        dadurch NIE selbst eine Rolle setzen oder einen Grant erzeugen --
        nur genau DIESEN einen, bereits ausgestellten Request
        beantworten."""
        if not self.available or self._confirm_authorization_client is None:
            return False, "ROS2-Bruecke nicht verfuegbar"
        if not request_id or not nonce:
            return False, "request_id/nonce fehlen"
        if not self._confirm_authorization_client.wait_for_service(timeout_sec=2.0):
            return False, "confirm_authorization Service nicht erreichbar"
        req = self._mods["ConfirmAuthorization"].Request()
        req.request_id = request_id
        req.nonce = nonce
        req.approve = bool(approve)
        req.confirmed_by = "tablet"
        future = self._confirm_authorization_client.call_async(req)
        deadline = time.time() + 3.0
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "confirm_authorization Zeitueberschreitung"
        response = future.result()
        return bool(response.success), response.reason


# Modul-globale Singleton-Instanz, von app.py beim Start initialisiert.
bridge = TabletRosBridge()
