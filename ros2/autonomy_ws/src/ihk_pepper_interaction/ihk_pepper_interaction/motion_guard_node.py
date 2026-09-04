#!/usr/bin/env python3
"""
motion_guard_node: letzte, hardwarenahe Sicherheitsinstanz vor /cmd_vel
(Entwicklungsauftrag 2, Abschnitt 11 "AP8"). Duenner ROS-Wrapper um
motion_guard.py, gleiches Muster wie supervisor_node.py.

Sitzt als letztes Glied in der Fahrbefehlskette:
    Nav2 -> Velocity Smoother -> Collision Monitor -> Motion Guard -> /cmd_vel
Liest den Kandidaten-Twist von `cmd_vel_in` (Parameter, Standard
"motion_guard/cmd_vel_in" -- wird in Auftrag 2 AP7 auf den tatsaechlichen
Collision-Monitor-Ausgang remapped) und leitet ihn NUR auf /cmd_vel
weiter, wenn evaluate_motion_guard() erlaubt=True liefert. Sonst wird
mit konfigurierbarer Rate eine Nullgeschwindigkeit publiziert (Auftrag:
"unmittelbar Nullgeschwindigkeit ausgeben, weitere Bewegungsbefehle
verwerfen") -- kein einmaliges Stop-Signal, sondern ein fortlaufendes,
solange der Zustand ungueltig bleibt.

`enable_live_motion` (Parameter, Standard false) ist der "expliziter
Livebewegungsmodus" aus dem Auftrag -- nur navigation_live/
navigation_dry_run setzen ihn auf true. In offline_test/realsense_test
bleibt er false, Motion Guard laesst dann NIE etwas durch, unabhaengig
von allen anderen Bedingungen.

Bekannte Luecke (ehrlich dokumentiert, siehe docs/DEVELOPMENT_ORDER_02_REPORT.md):
`gesture_in_progress` wird von KEINEM Node dieser Session tatsaechlich
publiziert -- sicherer Default: ohne je empfangenes Signal gilt
gesture_in_progress=True (blockiert Bewegung), bis bridge_node.py's
PlayGesture-Handler das in einem spaeteren Auftrag tatsaechlich
publiziert.

NICHT live gegen echten Nav2-Ausgang getestet -- kein Nav2 installiert
in dieser Session (siehe AP1-Bestandsaufnahme).
"""
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool, String

from ihk_pepper_interfaces.msg import SafetyState

from .motion_guard import MotionGuardInputs, evaluate_motion_guard


class MotionGuardNode(Node):
    def __init__(self):
        super().__init__("motion_guard")

        self.declare_parameter("cmd_vel_in_topic", "motion_guard/cmd_vel_in")
        self.declare_parameter("cmd_vel_out_topic", "/cmd_vel")
        self.declare_parameter("enable_live_motion", False)
        self.declare_parameter("max_cmd_age_s", 0.5)
        self.declare_parameter("publish_rate_hz", 10.0)

        self._last_cmd = None
        self._last_cmd_wall_s = None
        self._safety_allow_motion = False
        self._emergency_stop = True  # sicherer Default: bis /safety_state empfangen wurde
        self._realsense_diagnostics_valid = False
        self._odometry_valid = False
        self._localization_valid = False
        self._obstacle_data_valid = False
        self._head_navigation_pose_valid = False
        self._bumper_active = True  # sicherer Default: unbekannt = wie ausgeloest behandeln
        self._gesture_in_progress = True  # sicherer Default, siehe Moduldocstring

        self.cmd_pub = self.create_publisher(Twist, self.get_parameter("cmd_vel_out_topic").value, 10)
        self.diagnostics_pub = self.create_publisher(String, "motion_guard/diagnostics", 10)

        self.create_subscription(
            Twist, self.get_parameter("cmd_vel_in_topic").value, self._on_cmd_vel_in, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)
        self.create_subscription(Bool, "/pepper_bridge/bumper", self._on_bumper, 10)
        self.create_subscription(
            Bool, "realsense_diagnostics_valid", self._on_realsense_diagnostics_valid, 10)
        self.create_subscription(Bool, "odometry_valid", self._on_odometry_valid, 10)
        self.create_subscription(Bool, "/localization_valid", self._on_localization_valid, 10)
        self.create_subscription(Bool, "/obstacle_data_valid", self._on_obstacle_data_valid, 10)
        self.create_subscription(
            Bool, "head_navigation_pose_valid", self._on_head_navigation_pose_valid, 10)
        self.create_subscription(Bool, "/gesture_in_progress", self._on_gesture_in_progress, 10)

        rate = self.get_parameter("publish_rate_hz").value
        self.create_timer(1.0 / rate if rate > 0 else 0.1, self._tick)

        self.get_logger().info(
            "motion_guard gestartet -- enable_live_motion="
            f"{self.get_parameter('enable_live_motion').value}.")

    def _on_cmd_vel_in(self, msg: Twist):
        self._last_cmd = msg
        self._last_cmd_wall_s = time.time()

    def _on_safety_state(self, msg: SafetyState):
        self._safety_allow_motion = msg.allow_motion
        self._emergency_stop = msg.emergency_stop
        # obstacle_data_valid kommt auch direkt ueber SafetyState -- als
        # zusaetzliche Quelle genutzt, falls kein eigenes Topic laeuft.
        self._obstacle_data_valid = self._obstacle_data_valid or msg.obstacle_data_valid

    def _on_bumper(self, msg: Bool):
        self._bumper_active = msg.data

    def _on_realsense_diagnostics_valid(self, msg: Bool):
        self._realsense_diagnostics_valid = msg.data

    def _on_odometry_valid(self, msg: Bool):
        self._odometry_valid = msg.data

    def _on_localization_valid(self, msg: Bool):
        self._localization_valid = msg.data

    def _on_obstacle_data_valid(self, msg: Bool):
        self._obstacle_data_valid = msg.data

    def _on_head_navigation_pose_valid(self, msg: Bool):
        self._head_navigation_pose_valid = msg.data

    def _on_gesture_in_progress(self, msg: Bool):
        self._gesture_in_progress = msg.data

    def _tick(self):
        cmd_age_s = None if self._last_cmd_wall_s is None else time.time() - self._last_cmd_wall_s

        result = evaluate_motion_guard(MotionGuardInputs(
            live_motion_mode_active=self.get_parameter("enable_live_motion").value,
            safety_allow_motion=self._safety_allow_motion,
            realsense_diagnostics_valid=self._realsense_diagnostics_valid,
            odometry_valid=self._odometry_valid,
            localization_valid=self._localization_valid,
            obstacle_data_valid=self._obstacle_data_valid,
            head_navigation_pose_valid=self._head_navigation_pose_valid,
            bumper_active=self._bumper_active,
            emergency_stop=self._emergency_stop,
            gesture_in_progress=self._gesture_in_progress,
            cmd_age_s=cmd_age_s,
            max_cmd_age_s=self.get_parameter("max_cmd_age_s").value,
        ))

        if result.allow and self._last_cmd is not None:
            self.cmd_pub.publish(self._last_cmd)
        else:
            self.cmd_pub.publish(Twist())  # explizit Nullgeschwindigkeit

        diag = String()
        diag.data = f"allow={result.allow} reason={result.reason}"
        self.diagnostics_pub.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = MotionGuardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
