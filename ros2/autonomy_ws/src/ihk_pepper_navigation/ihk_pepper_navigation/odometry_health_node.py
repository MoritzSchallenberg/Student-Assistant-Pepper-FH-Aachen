#!/usr/bin/env python3
"""
odometry_health_node: bewertet die RGB-D-Visual-Odometry aus RTAB-Map
(rtabmap_odom/rgbd_odometry, siehe realsense_odometry.launch.py) fortlaufend
(Entwicklungsauftrag 2, Abschnitt 7 "AP4"). Duenner ROS-Wrapper um
odometry_health.py, gleiches Muster wie camera_pose_gate_node.py.

Published odometry_valid (Bool) auf `odometry_valid` -- false blockiert
spaeter die Bewegungsfreigabe (Motion Guard, Entwicklungsauftrag 2 AP8).
Sichere Ausgangslage: false, bis /odom_info tatsaechlich empfangen wurde.

NICHT live gegen echte RGB-D-Daten getestet -- keine RealSense-Hardware
in dieser Session angeschlossen. odometry_health.py selbst ist
vollstaendig unit-getestet.
"""
import time

import rclpy
from rclpy.node import Node
from rtabmap_msgs.msg import OdomInfo
from std_msgs.msg import Bool, String

from .odometry_health import check_odometry_health, max_translation_variance_from_covariance


class OdometryHealthNode(Node):
    def __init__(self):
        super().__init__("odometry_health")

        self.declare_parameter("odom_info_topic", "/odom_info")
        self.declare_parameter("max_data_age_s", 1.0)
        self.declare_parameter("max_translation_variance", 0.05)
        self.declare_parameter("min_inliers", 10)
        self.declare_parameter("publish_rate_hz", 5.0)

        self._last_odom_info = None
        self._last_received_wall_s = None

        self.valid_pub = self.create_publisher(Bool, "odometry_valid", 10)
        self.diagnostics_pub = self.create_publisher(String, "odometry_health/diagnostics", 10)

        self.create_subscription(
            OdomInfo, self.get_parameter("odom_info_topic").value, self._on_odom_info, 10)

        rate = self.get_parameter("publish_rate_hz").value
        self.create_timer(1.0 / rate if rate > 0 else 0.2, self._publish)

        self.get_logger().info(
            f"odometry_health gestartet, ueberwacht {self.get_parameter('odom_info_topic').value}.")

    def _on_odom_info(self, msg: OdomInfo):
        self._last_odom_info = msg
        self._last_received_wall_s = time.time()

    def _publish(self):
        if self._last_odom_info is None:
            data_age_s = None
            translation_variance = 0.0
            lost = True  # sicherer Default: ohne je empfangene Daten gilt Tracking als verloren
            inliers = None
        else:
            data_age_s = time.time() - self._last_received_wall_s
            translation_variance = max_translation_variance_from_covariance(
                self._last_odom_info.covariance)
            lost = self._last_odom_info.lost
            inliers = self._last_odom_info.inliers

        result = check_odometry_health(
            lost=lost,
            translation_variance=translation_variance,
            max_translation_variance=self.get_parameter("max_translation_variance").value,
            data_age_s=data_age_s,
            max_data_age_s=self.get_parameter("max_data_age_s").value,
            inliers=inliers,
            min_inliers=self.get_parameter("min_inliers").value,
        )
        self.valid_pub.publish(Bool(data=result.valid))
        diag = String()
        diag.data = f"valid={result.valid} reason={result.reason}"
        self.diagnostics_pub.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = OdometryHealthNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
