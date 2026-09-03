#!/usr/bin/env python3
"""
Pepper-Laser-Filter (Arbeitspaket 6). Peppers eingebaute Laser (`/laser`)
haben eine bekannte Eigenheit (siehe docs/STATUS.md, Abschnitt "Sensor-
Bewertung"): vereinzelte Werte liegen UEBER range_max (z.B. 7.08m bei
range_max=3.0m) und kodieren "kein Echo" statt einer echten Distanz. Ein
naiver Konsument (z.B. Nav2s Costmap) wuerde das als eine sehr weit
entfernte, aber gueltige Messung interpretieren.

Dieser Node:
    - ersetzt NaN/Inf und Werte > range_max durch `inf` (Standard-ROS2-
      Konvention fuer "kein Hindernis in Reichweite" -- Nav2s Costmap
      interpretiert `inf` korrekt als "frei bis max. Range", NICHT als
      Hindernis)
    - verwirft Werte < range_min ebenso (Rauschen/Sensor-Artefakt)
    - markiert das Scan als veraltet (verwirft die Publikation), wenn der
      Zeitstempel aelter als `max_age_s` ist -- wichtig, da Peppers Laser
      nur ~1.1Hz liefert (siehe docs/STATUS.md) und Nav2 mit veralteten Daten
      gefaehrlich falsche Freiraum-Annahmen treffen wuerde

Getestet (2026-08-20): mit synthetischen LaserScan-Nachrichten (siehe
ihk_pepper_tests) -- NICHT mit echten Pepper-Laserdaten (kein Pepper
verbunden in dieser Session).
"""
import math
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


def filter_ranges(msg: LaserScan) -> list:
    """Reine Funktion (fuer Unit-Tests ohne rclpy-Node)."""
    out = []
    for r in msg.ranges:
        if math.isnan(r) or math.isinf(r):
            out.append(float("inf"))
        elif r > msg.range_max:
            out.append(float("inf"))  # "kein Echo"-Artefakt, siehe Moduldoku
        elif r < msg.range_min:
            out.append(float("inf"))
        else:
            out.append(r)
    return out


def is_stale(msg_stamp_s: float, now_s: float, max_age_s: float) -> bool:
    return (now_s - msg_stamp_s) > max_age_s


class LaserFilterNode(Node):
    def __init__(self):
        super().__init__("laser_filter")
        self.declare_parameter("input_topic", "/laser")
        self.declare_parameter("output_topic", "/navigation/laser_filtered")
        self.declare_parameter("max_age_s", 2.0)

        self.max_age_s = self.get_parameter("max_age_s").value
        self._dropped_stale_count = 0

        self.pub = self.create_publisher(
            LaserScan, self.get_parameter("output_topic").value, 10)
        self.create_subscription(
            LaserScan, self.get_parameter("input_topic").value, self._on_scan, 10)

        self.get_logger().info(
            f"laser_filter gestartet: {self.get_parameter('input_topic').value} -> "
            f"{self.get_parameter('output_topic').value}"
        )

    def _on_scan(self, msg: LaserScan):
        stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        now_s = self.get_clock().now().nanoseconds * 1e-9
        if stamp_s > 0 and is_stale(stamp_s, now_s, self.max_age_s):
            self._dropped_stale_count += 1
            if self._dropped_stale_count % 20 == 1:
                self.get_logger().warn(
                    f"Laser-Scan veraltet (>{self.max_age_s}s) -- verworfen "
                    f"(bisher {self._dropped_stale_count}x)."
                )
            return

        out = LaserScan()
        out.header = msg.header
        out.angle_min = msg.angle_min
        out.angle_max = msg.angle_max
        out.angle_increment = msg.angle_increment
        out.time_increment = msg.time_increment
        out.scan_time = msg.scan_time
        out.range_min = msg.range_min
        out.range_max = msg.range_max
        out.ranges = filter_ranges(msg)
        out.intensities = msg.intensities
        self.pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = LaserFilterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
