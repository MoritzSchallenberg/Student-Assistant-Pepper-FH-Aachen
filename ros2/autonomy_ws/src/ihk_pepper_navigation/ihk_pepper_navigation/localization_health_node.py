#!/usr/bin/env python3
"""
localization_health_node: bewertet die RTAB-Map-Lokalisierung fortlaufend
anhand der Aktualitaet der map->odom-TF (Entwicklungsauftrag 2, Abschnitt
8 "AP5"). Duenner ROS-Wrapper um localization_health.py, gleiches Muster
wie camera_pose_gate_node.py.

Published DIREKT auf /localization_valid (Bool) -- denselben Topic-Namen,
den ihk_pepper_interaction/supervisor_node.py bereits seit
Entwicklungsauftrag 1 abonniert (dort bisher nur per Mock ueberschreibbar).
Dieser Node liefert jetzt die echte Implementierung: nur wenn
realsense_localization.launch.py laeuft UND RTAB-Map tatsaechlich eine
aktuelle map->odom-TF liefert, wird Bewegungsfreigabe ueberhaupt moeglich.
Sicherer Default: kein Publisher laeuft -> supervisor_node's eigener
Default (False) bleibt bestehen.

NICHT live gegen eine echte Karte/Lokalisierung getestet -- keine
RealSense-Hardware in dieser Session angeschlossen.
"""
import rclpy
import tf2_ros
from rclpy.node import Node
from std_msgs.msg import Bool, String

from .localization_health import check_localization_health


class LocalizationHealthNode(Node):
    def __init__(self):
        super().__init__("localization_health")

        self.declare_parameter("map_frame", "map")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("max_tf_age_s", 2.0)
        self.declare_parameter("tf_lookup_timeout_s", 0.2)
        self.declare_parameter("publish_rate_hz", 5.0)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.valid_pub = self.create_publisher(Bool, "/localization_valid", 10)
        self.diagnostics_pub = self.create_publisher(String, "localization_health/diagnostics", 10)

        rate = self.get_parameter("publish_rate_hz").value
        self.create_timer(1.0 / rate if rate > 0 else 0.2, self._publish)

        self.get_logger().info("localization_health gestartet, publiziert /localization_valid.")

    def _publish(self):
        map_frame = self.get_parameter("map_frame").value
        odom_frame = self.get_parameter("odom_frame").value
        timeout = rclpy.duration.Duration(
            seconds=self.get_parameter("tf_lookup_timeout_s").value)

        tf_available = False
        tf_age_s = None
        try:
            transform = self.tf_buffer.lookup_transform(
                map_frame, odom_frame, rclpy.time.Time(), timeout)
            tf_available = True
            stamp = transform.header.stamp
            stamp_s = stamp.sec + stamp.nanosec * 1e-9
            now_s = self.get_clock().now().nanoseconds * 1e-9
            tf_age_s = max(0.0, now_s - stamp_s)
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            pass

        result = check_localization_health(
            map_to_odom_tf_available=tf_available,
            map_to_odom_tf_age_s=tf_age_s,
            max_tf_age_s=self.get_parameter("max_tf_age_s").value,
        )
        self.valid_pub.publish(Bool(data=result.valid))
        diag = String()
        diag.data = f"valid={result.valid} reason={result.reason}"
        self.diagnostics_pub.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = LocalizationHealthNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
