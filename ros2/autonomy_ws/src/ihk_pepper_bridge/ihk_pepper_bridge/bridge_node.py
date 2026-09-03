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
from std_msgs.msg import String, Bool
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_interfaces.action import Say, PlayGesture
from ihk_pepper_interfaces.msg import SystemHealth

from .pepper_client import ThreadSafePepperClient
from .gesture_catalog import GestureCatalog, GestureValidationError


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

        try:
            self.catalog.play(self.pepper, name, speed, feedback_cb)
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
        if reachable:
            try:
                battery = self.pepper.get_battery()
                msg.battery_percent = float(battery) if battery is not None else -1.0
            except Exception:
                msg.battery_percent = -1.0
        else:
            msg.battery_percent = -1.0
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
