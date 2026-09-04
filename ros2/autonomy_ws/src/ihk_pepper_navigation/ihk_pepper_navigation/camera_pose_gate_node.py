#!/usr/bin/env python3
"""
camera_pose_gate_node: prueft, ob Peppers Kopf in der konfigurierten
Navigations-Pose steht (Entwicklungsauftrag 1, Abschnitt 3). Waehrend
Navigation muss der Kopf eine definierte Pose einnehmen, sonst
verfaelscht die bewegte RealSense-Kopfkamera visuelle Odometrie und
projizierte Hindernisdaten. Umgekehrt sind Kopfgesten waehrend Mapping/
Navigation gesperrt (siehe ihk_pepper_bridge/gesture_catalog.py::play(),
Parameter mapping_active).

Published camera_pose_valid (Bool) auf head_navigation_pose_valid --
false blockiert die Bewegungsfreigabe (spaeter in SafetyInputs verdrahtet,
Entwicklungsauftrag 2). Sichere Ausgangslage: false, bis echte
/joint_states-Daten UND eine bestaetigte Kopfpose vorliegen.

NICHT live getestet -- kein Pepper in dieser Session verbunden, daher
auch kein echtes /joint_states-Topic verfuegbar.
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, String

from .head_pose_gate import check_head_pose


class CameraPoseGateNode(Node):
    def __init__(self):
        super().__init__("camera_pose_gate")

        self.declare_parameter("joint_states_topic", "/joint_states")
        self.declare_parameter("navigation_head_yaw_rad", 0.0)
        self.declare_parameter("navigation_head_pitch_rad", 0.0)
        self.declare_parameter("tolerance_rad", 0.05)
        self.declare_parameter("max_age_s", 1.0)
        self.declare_parameter("publish_rate_hz", 5.0)

        self._head_yaw = None
        self._head_pitch = None
        self._last_joint_state_t = None

        self.valid_pub = self.create_publisher(Bool, "head_navigation_pose_valid", 10)
        self.diagnostics_pub = self.create_publisher(String, "camera_pose_gate/diagnostics", 10)

        self.create_subscription(
            JointState, self.get_parameter("joint_states_topic").value, self._on_joint_state, 10)

        rate = self.get_parameter("publish_rate_hz").value
        self.create_timer(1.0 / rate if rate > 0 else 0.2, self._publish)

        self.get_logger().info(
            f"camera_pose_gate gestartet, Ziel-Pose: "
            f"yaw={self.get_parameter('navigation_head_yaw_rad').value:.3f} "
            f"pitch={self.get_parameter('navigation_head_pitch_rad').value:.3f} rad "
            f"(Toleranz {self.get_parameter('tolerance_rad').value:.3f} rad)"
        )

    def _on_joint_state(self, msg: JointState):
        for name, position in zip(msg.name, msg.position):
            if name == "HeadYaw":
                self._head_yaw = position
            elif name == "HeadPitch":
                self._head_pitch = position
        if "HeadYaw" in msg.name or "HeadPitch" in msg.name:
            self._last_joint_state_t = self.get_clock().now()

    def _publish(self):
        now = self.get_clock().now()
        age_s = (now - self._last_joint_state_t).nanoseconds * 1e-9 if self._last_joint_state_t else 999.0

        result = check_head_pose(
            head_yaw_rad=self._head_yaw,
            head_pitch_rad=self._head_pitch,
            target_yaw_rad=self.get_parameter("navigation_head_yaw_rad").value,
            target_pitch_rad=self.get_parameter("navigation_head_pitch_rad").value,
            tolerance_rad=self.get_parameter("tolerance_rad").value,
            joint_state_age_s=age_s,
            max_age_s=self.get_parameter("max_age_s").value,
        )
        self.valid_pub.publish(Bool(data=result.valid))
        diag = String()
        diag.data = f"valid={result.valid} reason={result.reason} age_s={age_s:.2f}"
        self.diagnostics_pub.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = CameraPoseGateNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
