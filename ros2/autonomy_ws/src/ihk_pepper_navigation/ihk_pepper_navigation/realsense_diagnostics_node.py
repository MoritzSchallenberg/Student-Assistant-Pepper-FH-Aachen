#!/usr/bin/env python3
"""
realsense_diagnostics_node: erkennt zur Laufzeit, ob die RealSense-Kamera
tatsaechlich nutzbare Daten liefert (Entwicklungsauftrag 2, Abschnitt 5
"AP2"). Kein Kameramodell wird fest angenommen -- Modell/Aufloesung/Rate
werden aus den tatsaechlich empfangenen Topics abgeleitet, nicht
vorausgesetzt.

Published realsense_diagnostics_valid (Bool) auf `realsense_diagnostics_valid`
-- false blockiert spaeter die Bewegungsfreigabe (Motion Guard,
Entwicklungsauftrag 2 AP8). Sichere Ausgangslage: false, bis alle
ueberwachten Topics tatsaechlich empfangen wurden.

NICHT live gegen eine echte RealSense getestet -- keine Hardware in dieser
Session angeschlossen (siehe docs/DEVELOPMENT_ORDER_02_REPORT.md). Die
Diagnose-Logik selbst (realsense_diagnostics.py) ist vollstaendig
unit-getestet.
"""
import time

import rclpy
import tf2_ros
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import Bool, String

from .realsense_diagnostics import check_realsense_diagnostics, compute_invalid_depth_fraction


class RealsenseDiagnosticsNode(Node):
    def __init__(self):
        super().__init__("realsense_diagnostics")

        self.declare_parameter("color_topic", "/camera/color/image_raw")
        self.declare_parameter("depth_topic", "/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")
        self.declare_parameter("camera_optical_frame", "camera_color_optical_frame")
        self.declare_parameter("robot_base_frame", "base_link")
        self.declare_parameter("max_data_age_s", 1.0)
        self.declare_parameter("max_sync_diff_s", 0.1)
        self.declare_parameter("min_fps", 8.0)
        self.declare_parameter("max_invalid_depth_fraction", 0.9)
        self.declare_parameter("depth_scale_to_m", 0.001)
        self.declare_parameter("require_usb3", True)
        self.declare_parameter("publish_rate_hz", 2.0)
        self.declare_parameter("tf_lookup_timeout_s", 0.2)

        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self._color_stamp_s = None
        self._depth_stamp_s = None
        self._camera_info_stamp_s = None
        self._last_invalid_depth_fraction = None
        self._color_frame_times = []  # fuer FPS-Schaetzung, letzte N Ankunftszeiten

        self.valid_pub = self.create_publisher(Bool, "realsense_diagnostics_valid", 10)
        self.diagnostics_pub = self.create_publisher(String, "realsense_diagnostics/diagnostics", 10)

        self.create_subscription(
            Image, self.get_parameter("color_topic").value, self._on_color, 10)
        self.create_subscription(
            Image, self.get_parameter("depth_topic").value, self._on_depth, 10)
        self.create_subscription(
            CameraInfo, self.get_parameter("camera_info_topic").value, self._on_camera_info, 10)

        rate = self.get_parameter("publish_rate_hz").value
        self.create_timer(1.0 / rate if rate > 0 else 0.5, self._publish)

        self.get_logger().info(
            "realsense_diagnostics gestartet -- ueberwacht "
            f"{self.get_parameter('color_topic').value}, "
            f"{self.get_parameter('depth_topic').value}, "
            f"{self.get_parameter('camera_info_topic').value}."
        )

    def _stamp_to_s(self, stamp) -> float:
        return stamp.sec + stamp.nanosec * 1e-9

    def _on_color(self, msg: Image):
        self._color_stamp_s = self._stamp_to_s(msg.header.stamp)
        now = time.time()
        self._color_frame_times.append(now)
        # Nur ein kurzes Zeitfenster fuer die FPS-Schaetzung behalten.
        cutoff = now - 5.0
        self._color_frame_times = [t for t in self._color_frame_times if t >= cutoff]

    def _on_depth(self, msg: Image):
        self._depth_stamp_s = self._stamp_to_s(msg.header.stamp)
        try:
            depth_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            self._last_invalid_depth_fraction = compute_invalid_depth_fraction(
                depth_image,
                depth_scale_to_m=self.get_parameter("depth_scale_to_m").value,
            )
        except Exception as e:
            self.get_logger().warn(f"Tiefenbild konnte nicht dekodiert werden: {e}")
            self._last_invalid_depth_fraction = 1.0

    def _on_camera_info(self, msg: CameraInfo):
        self._camera_info_stamp_s = self._stamp_to_s(msg.header.stamp)

    def _measured_fps(self):
        if len(self._color_frame_times) < 2:
            return None
        span = self._color_frame_times[-1] - self._color_frame_times[0]
        if span <= 0.0:
            return None
        return (len(self._color_frame_times) - 1) / span

    def _tf_to_base_available(self) -> bool:
        camera_frame = self.get_parameter("camera_optical_frame").value
        base_frame = self.get_parameter("robot_base_frame").value
        try:
            timeout = rclpy.duration.Duration(
                seconds=self.get_parameter("tf_lookup_timeout_s").value)
            self.tf_buffer.lookup_transform(base_frame, camera_frame, rclpy.time.Time(), timeout)
            return True
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            return False

    def _age_or_none(self, stamp_s, now_s):
        return None if stamp_s is None else max(0.0, now_s - stamp_s)

    def _publish(self):
        now_s = time.time()
        color_age = self._age_or_none(self._color_stamp_s, now_s)
        depth_age = self._age_or_none(self._depth_stamp_s, now_s)
        camera_info_age = self._age_or_none(self._camera_info_stamp_s, now_s)
        sync_diff = (abs(self._color_stamp_s - self._depth_stamp_s)
                     if self._color_stamp_s is not None and self._depth_stamp_s is not None
                     else None)

        result = check_realsense_diagnostics(
            color_topic_age_s=color_age,
            depth_topic_age_s=depth_age,
            camera_info_topic_age_s=camera_info_age,
            max_data_age_s=self.get_parameter("max_data_age_s").value,
            color_depth_sync_diff_s=sync_diff,
            max_sync_diff_s=self.get_parameter("max_sync_diff_s").value,
            measured_fps=self._measured_fps(),
            min_fps=self.get_parameter("min_fps").value,
            invalid_depth_fraction=self._last_invalid_depth_fraction,
            max_invalid_depth_fraction=self.get_parameter("max_invalid_depth_fraction").value,
            tf_to_base_available=self._tf_to_base_available(),
            require_usb3=self.get_parameter("require_usb3").value,
        )
        self.valid_pub.publish(Bool(data=result.valid))
        diag = String()
        diag.data = f"valid={result.valid} reasons={','.join(result.reasons) or 'ok'}"
        self.diagnostics_pub.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = RealsenseDiagnosticsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
