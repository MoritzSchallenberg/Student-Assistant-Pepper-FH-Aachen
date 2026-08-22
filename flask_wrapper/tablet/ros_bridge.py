"""
Tablet<->ROS2-Bruecke fuer die erweiterte Tablet-Oberflaeche
(Entwicklungsauftrag Abschnitt 20).

Laeuft als rclpy-Node in einem Hintergrund-Thread INNERHALB des
flask_wrapper-Prozesses (Flask selbst bleibt unveraendert lauffaehig auch
ohne ROS2 -- siehe _try_import_rclpy()). Stellt read-only Snapshots der
relevanten ROS2-Topics bereit sowie GENAU ZWEI schreibende Aktionen, beide
ueber einen festen Allowlist-Pfad (Auftrag Abschnitt 3.4 -- niemals
Freitext/LLM-Text direkt in ROS-Befehle):
    - request_control(cmd) : nur "pause"|"resume"|"repeat", published auf
      /presentation_control (String)
    - request_stop()       : ruft /cancel_interaction (CancelInteraction)
      und /play_presentation/_action/cancel_goal (generischer
      Action-Cancel-Service, funktioniert unabhaengig davon wer das Ziel
      gesendet hat) -- beides feste ROS2-Service-Aufrufe, kein Shell/Text.

WICHTIG (Betrieb): Damit rclpy + die eigenen Interfaces
(ihk_pepper_interfaces) in der flask_wrapper-venv importierbar sind, MUSS
vor dem Start von app.py folgendes gesourced sein:
    source /opt/ros/jazzy/setup.bash
    source <pfad-zu>/pepper_autonomy_ws/install/setup.bash
Fehlt das, startet Flask trotzdem normal -- die Tablet-Seite zeigt dann
dauerhaft den "offline"-Zustand (getestet, siehe IMPLEMENTATION_REPORT.md).
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
        from ihk_pepper_interfaces.msg import DialogueState, PresentationState, SafetyState
        from ihk_pepper_interfaces.srv import CancelInteraction
        from action_msgs.srv import CancelGoal
        return {
            "rclpy": rclpy, "Node": Node, "SingleThreadedExecutor": SingleThreadedExecutor,
            "String": String, "UInt8": UInt8, "DialogueState": DialogueState,
            "PresentationState": PresentationState, "SafetyState": SafetyState,
            "CancelInteraction": CancelInteraction, "CancelGoal": CancelGoal,
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
        }
        self._node = None
        self._executor = None
        self._thread = None
        self._control_pub = None
        self._voice_command_pub = None
        self._cancel_interaction_client = None
        self._cancel_presentation_client = None

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

            self._control_pub = node.create_publisher(m["String"], "/presentation_control", 10)
            self._voice_command_pub = node.create_publisher(m["String"], "/audio_node/voice_command", 10)
            self._cancel_interaction_client = node.create_client(
                m["CancelInteraction"], "/cancel_interaction")
            self._cancel_presentation_client = node.create_client(
                m["CancelGoal"], "/play_presentation/_action/cancel_goal")

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

        return {
            "bridge_available": self.available,
            "dialogue_state": d["dialogue_state"] if fresh("dialogue_state") else None,
            "presentation_state": d["presentation_state"] if fresh("presentation_state") else None,
            "safety_state": d["safety_state"] if fresh("safety_state") else None,
            "interaction_state_name": d["interaction_state_name"] if fresh("interaction_state_name") else None,
            "tablet_command": d["tablet_command"] if fresh("tablet_command") else None,
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


# Modul-globale Singleton-Instanz, von app.py beim Start initialisiert.
bridge = TabletRosBridge()
