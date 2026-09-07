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

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from std_msgs.msg import String, Bool, Float32
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_interfaces.action import Say, PlayGesture
from ihk_pepper_interfaces.msg import SystemHealth

from .pepper_client import ThreadSafePepperClient
from .gesture_catalog import GestureCatalog, GestureValidationError
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

        cb_group = ReentrantCallbackGroup()

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

    # ---- Say ----

    def _goal_callback_say(self, goal_request):
        if not goal_request.text.strip():
            self.get_logger().warn("Say-Ziel mit leerem Text abgelehnt")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute_say(self, goal_handle):
        text = goal_handle.request.text
        feedback = Say.Feedback()
        feedback.status = "speaking"
        goal_handle.publish_feedback(feedback)

        result = Say.Result()
        self._say_active.set()
        self.speaking_pub.publish(Bool(data=True))
        try:
            import time
            t0 = time.time()
            if not self.get_parameter("dry_run").value:
                self.pepper.say(text)
            result.duration_s = time.time() - t0
            result.success = True
            goal_handle.succeed()
        except Exception as e:
            self.get_logger().error(f"Say fehlgeschlagen: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
        finally:
            self._say_active.clear()
            self.speaking_pub.publish(Bool(data=False))
        return result

    def is_speaking(self) -> bool:
        """Fuer den Halbduplex-Controller in ihk_pepper_audio: waehrend
        Pepper spricht, soll die Audio-Pipeline nicht gleichzeitig
        zuhoeren (sonst transkribiert er sich selbst)."""
        return self._say_active.is_set()

    def _on_nav2_moving(self, msg: Bool):
        self._nav2_moving = msg.data

    # ---- PlayGesture ----

    def _execute_gesture(self, goal_handle):
        name = goal_handle.request.gesture_name
        speed = goal_handle.request.speed_scale or 1.0
        result = PlayGesture.Result()

        def feedback_cb(status, progress):
            fb = PlayGesture.Feedback()
            fb.status = status
            fb.progress = progress
            goal_handle.publish_feedback(fb)

        # Entwicklungsauftrag 4, AP4/AP13: schliesst die seit Auftrag 2
        # dokumentierte Luecke -- dieses Topic wurde bisher von KEINEM
        # Node tatsaechlich publiziert. True fuer die volle Dauer der
        # Ausfuehrung (auch waehrend eines fehlgeschlagenen Versuchs --
        # es ist erst "vorbei", wenn play() zurueckkehrt), garantiert per
        # finally auf False zurueckgesetzt.
        self.gesture_in_progress_pub.publish(Bool(data=True))
        try:
            self.catalog.play(
                self.pepper, name, speed, feedback_cb,
                dry_run=self.get_parameter("dry_run").value,
                # Entwicklungsauftrag 2, AP10: jetzt tatsaechlich live
                # verdrahtet (vorher dokumentierte Luecke aus Auftrag 1,
                # siehe docs/GESTURE_AUTHORING.md "Live-Wiring-Stand").
                nav2_moving=self._nav2_moving,
            )
            result.success = True
            goal_handle.succeed()
        except (KeyError, GestureValidationError) as e:
            self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
        except Exception as e:
            self.get_logger().error(f"PlayGesture '{name}' fehlgeschlagen: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
        finally:
            self.gesture_in_progress_pub.publish(Bool(data=False))
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
