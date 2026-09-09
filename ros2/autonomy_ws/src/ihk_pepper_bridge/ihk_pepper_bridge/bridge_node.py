#!/usr/bin/env python3
"""
ihk_pepper_bridge: kapselt die vorhandenen qicli-Faehigkeiten (SSH) als
ROS2-Node -- Actions fuer lang laufende Dinge (Sprechen, Gesten), Topics
fuer Status (Akku, Touch, Autonomous-Life).

Getestet (2026-08-19): NUR mit Pepper nicht angeschlossen, d.h. Action-
Server/Struktur/Gesten-Validierung wurden verifiziert, die tatsaechliche
SSH-Kommunikation mit dem echten Roboter NICHT live in dieser Session
(siehe docs/IMPLEMENTATION_REPORT.md).
"""
import os
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from std_msgs.msg import String, Bool, Float32
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_interfaces.action import Say, PlayGesture
from ihk_pepper_interfaces.msg import SystemHealth
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease

from ihk_pepper_interaction.actuator_arbiter import PRIORITY_DIALOGUE
from ihk_pepper_interaction.resource_derivation import resources_for_gesture, resources_for_speech

from .pepper_client import PepperInterruptChannel, ThreadSafePepperClient
from .gesture_catalog import GestureCatalog, GestureValidationError
from .tts_guard import TtsTextRejected, validate_tts_text
from . import safety_topics


def _default_gesture_dir():
    # Installierter Fall (ros2 run/launch): Daten liegen im share/-Ordner,
    # siehe setup.py data_files. Fallback aufs Source-Layout, falls jemand
    # das Modul direkt aus dem src/-Baum importiert (z.B. in Tests).
    try:
        return os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "gestures"
        )


DEFAULT_GESTURE_DIR = _default_gesture_dir()

# Entwicklungsauftrag 04-B, AP5B: Poll-Intervalle/Wartezeiten fuer die
# Cancel-Beobachtung waehrend Say/PlayGesture -- kein unbegrenztes
# Blockieren mehr (siehe Abschnitt 2.1/2.2).
SAY_POLL_INTERVAL_S = 0.1
SAY_CANCEL_GRACE_S = 1.0
GESTURE_POLL_INTERVAL_S = 0.1
GESTURE_CANCEL_GRACE_S = 2.0
OWNER_ID = "pepper_bridge"


class PepperBridgeNode(Node):
    def __init__(self):
        super().__init__("pepper_bridge")

        self.declare_parameter("gesture_dir", DEFAULT_GESTURE_DIR)
        self.declare_parameter("health_publish_interval_s", 5.0)
        # Entwicklungsauftrag 1, Abschnitt 12: erlaubt offline_test/
        # navigation_dry_run, den kompletten Behavior-Tree-Ablauf bis
        # CONVERSATION_READY zu durchlaufen, OHNE eine echte SSH-
        # Verbindung zu Pepper zu brauchen -- Say/PlayGesture melden
        # sofort Erfolg, OHNE pepper_client anzufassen. Siehe
        # gesture_catalog.py::play(dry_run=...), das dieselbe Idee schon
        # fuer die reine Katalog-Logik hatte.
        self.declare_parameter("dry_run", False)
        if self.get_parameter("dry_run").value:
            self.get_logger().warn(
                "pepper_bridge im dry_run-Modus -- KEINE echte SSH-Verbindung zu Pepper, "
                "Say/PlayGesture melden sofort Erfolg ohne jede Hardwareaktion."
            )

        gesture_dir = self.get_parameter("gesture_dir").value
        self.catalog = GestureCatalog(gesture_dir)
        for e in self.catalog.reload():
            self.get_logger().error(f"Geste ungueltig, uebersprungen: {e}")
        self.get_logger().info(
            f"Gesten-Katalog geladen aus {gesture_dir}: {self.catalog.names()}"
        )

        self.pepper = ThreadSafePepperClient()
        # Entwicklungsauftrag 04-B, AP5B, Abschnitt 2.3/10: unabhaengiger
        # zweiter SSH-Kanal AUSSCHLIESSLICH fuer Abbruchbefehle -- teilt
        # sich nie den Lock des Hauptkanals, blockiert also nie hinter
        # einem lange laufenden TTS-/Trajektorienaufruf. Lazy Verbindung
        # (siehe PepperInterruptChannel), kein Zusatzaufwand, solange nie
        # abgebrochen wird.
        self.interrupt_channel = PepperInterruptChannel()

        cb_group = ReentrantCallbackGroup()

        # Entwicklungsauftrag 04-B, AP5B: Service-Clients zum zentralen
        # Aktuator-Arbiter -- jede Say-/PlayGesture-Ausfuehrung MUSS erst
        # eine Lease erhalten, bevor irgendeine Hardwareaktion angestossen
        # wird (siehe _acquire_lease()/_release_lease() unten).
        self.acquire_lease_client = self.create_client(
            AcquireActuatorLease, "/actuator_arbiter/acquire", callback_group=cb_group)
        self.release_lease_client = self.create_client(
            ReleaseActuatorLease, "/actuator_arbiter/release", callback_group=cb_group)

        self._say_active = threading.Event()

        # Fuer den Halbduplex-Controller in ihk_pepper_audio: solange
        # Pepper spricht, soll die Audio-Pipeline nicht gleichzeitig
        # zuhoeren (sonst transkribiert er sich selbst).
        self.speaking_pub = self.create_publisher(Bool, "speaking", 10)

        # Entwicklungsauftrag 2, AP10: waehrend Nav2 aktiv faehrt (siehe
        # ihk_pepper_navigation/person_approach_node.py) duerfen keine
        # Arm-/Kopfgesten laufen -- gesture_catalog.py::play() konnte das
        # bereits seit Auftrag 1 pruefen (nav2_moving-Parameter), wurde
        # aber nie tatsaechlich live verdrahtet. Sicherer Default: False
        # bis das Topic je empfangen wurde -- KEIN Blockieren durch
        # Abwesenheit des Signals, aber auch keine falsche Freigabe.
        self._nav2_moving = False
        self.create_subscription(Bool, "/nav2_moving", self._on_nav2_moving, 10)

        self.say_action_server = ActionServer(
            self, Say, "say",
            execute_callback=self._execute_say,
            goal_callback=self._goal_callback_say,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )
        self.gesture_action_server = ActionServer(
            self, PlayGesture, "play_gesture",
            execute_callback=self._execute_gesture,
            goal_callback=self._goal_callback_gesture,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )

        self.health_pub = self.create_publisher(SystemHealth, "system_health", 10)
        interval = self.get_parameter("health_publish_interval_s").value
        self.create_timer(interval, self._publish_health)

        # Entwicklungsauftrag 4, AP4 / Entwicklungsauftrag 04-B, AP2: reale
        # Statustopics statt Platzhalter. Alle unter dem eigenen Node-
        # Namespace (pepper_bridge/...) -- Namen jetzt aus der
        # gemeinsamen safety_topics.py-Konstantendatei (04-B: "zentrale,
        # dokumentierte Topic-Liste... vermeide leicht abweichende Namen
        # in mehreren Paketen") statt lokaler String-Literale, die von
        # den Abonnenten (Supervisor/Motion Guard) unabhaengig
        # nachgetippt werden mussten -- genau DAS ist bei
        # gesture_in_progress bereits einmal auseinandergedriftet (siehe
        # safety_topics.py-Docstring: motion_guard_node.py abonnierte
        # bisher "/gesture_in_progress" ohne Namespace-Praefix und hat
        # dieses Topic dadurch NIE empfangen).
        self.bumper_pub = self.create_publisher(Bool, safety_topics.BUMPER_TOPIC_RELATIVE, 10)
        self.charging_state_pub = self.create_publisher(
            Bool, safety_topics.CHARGING_STATE_TOPIC_RELATIVE, 10)
        self.battery_pub = self.create_publisher(Float32, safety_topics.BATTERY_TOPIC_RELATIVE, 10)
        self.connection_state_pub = self.create_publisher(
            String, safety_topics.CONNECTION_STATE_TOPIC_RELATIVE, 10)
        self.gesture_in_progress_pub = self.create_publisher(
            Bool, safety_topics.GESTURE_IN_PROGRESS_TOPIC_RELATIVE, 10)

        self.get_logger().info("pepper_bridge Node gestartet.")

    # ---- Aktuator-Arbiter (Entwicklungsauftrag 04-B, AP5B) ----

    def _acquire_lease(self, resources, purpose: str, goal_id: str, ttl_s: float):
        """Gibt (granted, lease_id, reason) zurueck. Fail-closed: ein
        nicht erreichbarer/nicht antwortender Arbiter gewaehrt NIE
        stillschweigend eine Aktuation."""
        if not self.acquire_lease_client.wait_for_service(timeout_sec=1.0):
            return False, "", "actuator_arbiter nicht erreichbar"
        req = AcquireActuatorLease.Request()
        req.owner_id = OWNER_ID
        req.resources = sorted(resources)
        req.purpose = purpose
        req.priority = PRIORITY_DIALOGUE
        req.ttl_s = ttl_s
        req.goal_id = goal_id
        future = self.acquire_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "", "actuator_arbiter Zeitueberschreitung"
        try:
            response = future.result()
        except Exception as e:
            return False, "", f"actuator_arbiter Fehler: {e}"
        return response.granted, response.lease_id, response.reason

    def _release_lease(self, lease_id: str):
        if not lease_id:
            return
        if not self.release_lease_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(
                f"Lease '{lease_id}' konnte nicht freigegeben werden (Arbiter nicht erreichbar).")
            return
        req = ReleaseActuatorLease.Request()
        req.lease_id = lease_id
        future = self.release_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)

    @staticmethod
    def _goal_id_str(goal_handle) -> str:
        try:
            return str(bytes(goal_handle.goal_id.uuid))
        except Exception:
            return ""

    # ---- Say ----

    def _goal_callback_say(self, goal_request):
        if not goal_request.text.strip():
            self.get_logger().warn("Say-Ziel mit leerem Text abgelehnt")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute_say(self, goal_handle):
        """Entwicklungsauftrag 04-B, AP5B, Abschnitt 9/12: Text wird an
        DIESER Grenze nochmal validiert (Abschnitt 9.2, unabhaengig von
        einer bereits erfolgten Bereinigung im Dialogserver), die
        eigentliche TTS-Ausgabe laeuft in einem Hintergrund-Thread, damit
        goal_handle.is_cancel_requested/max_duration_s waehrend des
        Sprechens tatsaechlich beobachtet werden (vorher: blockierender
        Aufruf ohne jede Cancel-Beobachtung). SPEECH-Lease wird VOR jeder
        Hardwareaktion angefordert und in JEDEM Endpfad freigegeben."""
        result = Say.Result()
        try:
            text = validate_tts_text(goal_handle.request.text)
        except TtsTextRejected as e:
            self.get_logger().warn(f"Say abgelehnt (Textpruefung an der Bridge-Grenze): {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
            return result

        allow_interrupt = goal_handle.request.allow_interrupt
        max_duration_s = goal_handle.request.max_duration_s or None
        goal_id = self._goal_id_str(goal_handle)

        granted, lease_id, reason = self._acquire_lease(
            resources_for_speech(), purpose="say", goal_id=goal_id,
            ttl_s=(max_duration_s or 30.0) + 10.0,
        )
        if not granted:
            self.get_logger().warn(f"Say abgelehnt (Aktuator-Arbiter): {reason}")
            result.success = False
            result.error_message = f"Ressourcenkonflikt: {reason}"
            goal_handle.abort()
            return result

        feedback = Say.Feedback()
        feedback.status = "speaking"
        goal_handle.publish_feedback(feedback)

        self._say_active.set()
        self.speaking_pub.publish(Bool(data=True))

        done_event = threading.Event()
        outcome = {"error": None}

        def _run():
            try:
                if not self.get_parameter("dry_run").value:
                    self.pepper.say_text_only(text)
            except Exception as e:  # noqa: BLE001
                outcome["error"] = e
            finally:
                done_event.set()

        thread = threading.Thread(target=_run, daemon=True)
        t0 = time.time()
        thread.start()

        final_state = "SUCCEEDED"
        try:
            while not done_event.wait(timeout=SAY_POLL_INTERVAL_S):
                elapsed = time.time() - t0
                timed_out = max_duration_s is not None and elapsed > max_duration_s
                # Safety-/Nutzer-Stopp bleiben unabhaengig von
                # allow_interrupt wirksam (Abschnitt 9.3) -- ein echter
                # Not-Stopp/Bumper laeuft ueber
                # actuator_arbiter::emergency_revoke_all() und entzieht
                # die Lease bereits arbiterseitig; ein normaler
                # ROS2-Cancel respektiert allow_interrupt=False.
                user_cancel = goal_handle.is_cancel_requested and allow_interrupt
                if not (timed_out or user_cancel):
                    continue
                reason_text = "max_duration_s ueberschritten" if timed_out else "abgebrochen"
                self.get_logger().info(f"Say wird beendet: {reason_text}")
                try:
                    self.interrupt_channel.stop_speech()
                except Exception:
                    self.get_logger().warning(
                        "stop_speech() ueber Interrupt-Kanal fehlgeschlagen.", exc_info=True)
                done_event.wait(SAY_CANCEL_GRACE_S)
                final_state = "TIMED_OUT" if timed_out else "CANCELLED"
                break

            result.duration_s = time.time() - t0
            if final_state == "SUCCEEDED" and outcome["error"] is not None:
                self.get_logger().error(f"Say fehlgeschlagen: {outcome['error']}")
                result.success = False
                result.error_message = str(outcome["error"])
                goal_handle.abort()
            elif final_state == "SUCCEEDED":
                result.success = True
                goal_handle.succeed()
            elif final_state == "CANCELLED":
                result.success = False
                result.error_message = "abgebrochen"
                goal_handle.canceled()
            else:
                result.success = False
                result.error_message = final_state
                goal_handle.abort()
        finally:
            self._say_active.clear()
            self.speaking_pub.publish(Bool(data=False))
            self._release_lease(lease_id)
        return result

    def is_speaking(self) -> bool:
        """Fuer den Halbduplex-Controller in ihk_pepper_audio: waehrend
        Pepper spricht, soll die Audio-Pipeline nicht gleichzeitig
        zuhoeren (sonst transkribiert er sich selbst)."""
        return self._say_active.is_set()

    def _on_nav2_moving(self, msg: Bool):
        self._nav2_moving = msg.data

    # ---- PlayGesture ----

    def _goal_callback_gesture(self, goal_request):
        if not goal_request.gesture_name.strip():
            self.get_logger().warn("PlayGesture-Ziel ohne Gestennamen abgelehnt")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _execute_gesture(self, goal_handle):
        """Entwicklungsauftrag 04-B, AP5B, Abschnitt 4/12: Ressourcen
        werden DETERMINISTISCH aus den tatsaechlich betroffenen Gelenken
        abgeleitet (nie aus dem Gestennamen/einer LLM-Angabe), ALLE
        atomar ueber den Aktuator-Arbiter angefordert, BEVOR
        catalog.play() irgendeine Hardwareaktion anstoesst. Laeuft in
        einem Hintergrund-Thread, damit ein Cancel waehrend der
        Ausfuehrung tatsaechlich beobachtet und an
        catalog.play()s cancel_event durchgereicht wird (vorher: kein
        Cancel-Handling waehrend der Bewegung)."""
        name = goal_handle.request.gesture_name
        speed = goal_handle.request.speed_scale or 1.0
        result = PlayGesture.Result()

        def feedback_cb(status, progress):
            fb = PlayGesture.Feedback()
            fb.status = status
            fb.progress = progress
            goal_handle.publish_feedback(fb)

        try:
            gesture = self.catalog.get(name)
        except KeyError as e:
            self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
            return result

        try:
            resources = resources_for_gesture(gesture)
        except ValueError as e:
            self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
            return result

        goal_id = self._goal_id_str(goal_handle)
        granted, lease_id, reason = self._acquire_lease(
            resources, purpose=f"play_gesture:{name}", goal_id=goal_id,
            ttl_s=max(gesture.duration_s() / max(speed, 0.01) + 10.0, 15.0),
        )
        if not granted:
            self.get_logger().warn(f"PlayGesture '{name}' abgelehnt (Aktuator-Arbiter): {reason}")
            result.success = False
            result.error_message = f"Ressourcenkonflikt: {reason}"
            goal_handle.abort()
            return result

        # Entwicklungsauftrag 4, AP4/AP13: schliesst die seit Auftrag 2
        # dokumentierte Luecke -- dieses Topic wurde bisher von KEINEM
        # Node tatsaechlich publiziert. True fuer die volle Dauer der
        # Ausfuehrung (auch waehrend eines fehlgeschlagenen Versuchs --
        # es ist erst "vorbei", wenn play() zurueckkehrt), garantiert per
        # finally auf False zurueckgesetzt.
        self.gesture_in_progress_pub.publish(Bool(data=True))
        cancel_event = threading.Event()
        try:
            done_event = threading.Event()
            outcome = {"error": None}

            def _run():
                try:
                    self.catalog.play(
                        self.pepper, name, speed, feedback_cb,
                        dry_run=self.get_parameter("dry_run").value,
                        # Entwicklungsauftrag 2, AP10: jetzt tatsaechlich
                        # live verdrahtet (vorher dokumentierte Luecke aus
                        # Auftrag 1, siehe docs/GESTURE_AUTHORING.md
                        # "Live-Wiring-Stand").
                        nav2_moving=self._nav2_moving,
                        cancel_event=cancel_event,
                        interrupt_channel=self.interrupt_channel,
                    )
                except Exception as e:  # noqa: BLE001
                    outcome["error"] = e
                finally:
                    done_event.set()

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            while not done_event.wait(timeout=GESTURE_POLL_INTERVAL_S):
                if goal_handle.is_cancel_requested:
                    self.get_logger().info(f"PlayGesture '{name}' wird abgebrochen.")
                    cancel_event.set()
                    done_event.wait(GESTURE_CANCEL_GRACE_S)
                    break

            if outcome["error"] is not None:
                e = outcome["error"]
                if isinstance(e, (KeyError, GestureValidationError)):
                    self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
                else:
                    self.get_logger().error(f"PlayGesture '{name}' fehlgeschlagen: {e}")
                result.success = False
                result.error_message = str(e)
                goal_handle.abort()
            elif goal_handle.is_cancel_requested:
                result.success = False
                result.error_message = "abgebrochen"
                goal_handle.canceled()
            else:
                result.success = True
                goal_handle.succeed()
        finally:
            self.gesture_in_progress_pub.publish(Bool(data=False))
            self._release_lease(lease_id)
        return result

    # ---- Health ----

    def _publish_health(self):
        msg = SystemHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        reachable = self.pepper.is_reachable(timeout_s=1.0)
        msg.pepper_bridge_ok = reachable
        msg.audio_pipeline_ok = False  # von ihk_pepper_audio ueberschrieben, hier nur Platzhalter
        msg.anythingllm_ok = False  # von ihk_pepper_dialog ueberschrieben
        msg.navigation_ok = False
        msg.perception_ok = False

        # Entwicklungsauftrag 4, AP4: reale Werte statt Platzhalter fuer
        # bumper/charging_state/battery/connection_state. Bei fehlendem
        # oder ungueltigem Wert wird bewusst NICHT "false"/0 verwendet
        # (das waere eine unbegruendete positive Aussage), sondern der
        # sicherste Wert je Topic -- ein Bumper, dessen Zustand nicht
        # ermittelt werden konnte, gilt als GEDRUECKT (blockiert), keine
        # Ladeinfo gilt als LAEDT NICHT (konservativ fuer den
        # Fahr-Interlock ist das die Annahme, die Fahrt eher zulaesst als
        # verweigert -- die eigentliche Sicherheitsentscheidung liegt bei
        # Motion Guard, der bei fehlenden/veralteten Daten ohnehin
        # blockiert, nicht bei diesem reinen Statustopic).
        bumper_pressed = None
        charging = None
        battery = None
        if reachable:
            try:
                bumper_pressed = self.pepper.get_bumper_pressed()
            except Exception as e:
                self.get_logger().warn(f"get_bumper_pressed() fehlgeschlagen: {e}")
            try:
                charging = self.pepper.get_charging_state()
            except Exception as e:
                self.get_logger().warn(f"get_charging_state() fehlgeschlagen: {e}")
            try:
                battery = self.pepper.get_battery()
            except Exception as e:
                self.get_logger().warn(f"get_battery() fehlgeschlagen: {e}")

        self.bumper_pub.publish(Bool(data=True if bumper_pressed is None else bumper_pressed))
        self.charging_state_pub.publish(Bool(data=False if charging is None else charging))
        self.battery_pub.publish(Float32(data=-1.0 if battery is None else float(battery)))
        self.connection_state_pub.publish(String(data=self.pepper.connection_state))

        msg.battery_percent = -1.0 if battery is None else float(battery)
        msg.current_mode = "unknown"
        msg.active_warnings = [] if reachable else ["pepper_unreachable"]
        self.health_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PepperBridgeNode()
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.pepper.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
