#!/usr/bin/env python3
"""
compute_health_mock_node: Mock-Eingaenge fuer Rechen-NUC + zwei externe
Akkupacks (Entwicklungsauftrag 1, Abschnitt 10).

Nur fuer offline_test/realsense_test-Betriebsmodi gedacht -- auf dem
allgemeinen Entwicklungs-NUC gibt es keine echte NUC-Unterspannungs-
oder Akkupack-Telemetrie, die hier ausgelesen werden koennte. Dieser
Node published feste/konfigurierbare Werte, damit supervisor_node.py und
spaetere Behavior-Tree-Knoten (IsSystemReady) gegen ein reales Topic
statt gegen einen im Code hartcodierten Wert getestet werden koennen.

KEINE elektrische Aussage, KEINE Aussage ueber Parallelschaltbarkeit von
zwei Akkus -- reine Software-Eingaenge. Elektrische Auslegung, BMS,
Sicherungen, DC/DC-Regelung etc. sind ausdruecklich NICHT Teil dieses
Auftrags (siehe docs/DEVELOPMENT_ORDER_01_REPORT.md, "Nicht Bestandteil").
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String


class ComputeHealthMockNode(Node):
    def __init__(self):
        super().__init__("compute_health_mock_node")

        self.declare_parameter("compute_power_valid", True)
        self.declare_parameter("nuc_undervoltage_warning", False)
        self.declare_parameter("battery_pack_1_percent", 100.0)
        self.declare_parameter("battery_pack_2_percent", 100.0)
        self.declare_parameter("publish_interval_s", 1.0)

        self.power_pub = self.create_publisher(Bool, "/compute_power_valid", 10)
        self.diagnostics_pub = self.create_publisher(String, "compute_health_mock/diagnostics", 10)

        interval = self.get_parameter("publish_interval_s").value
        self.create_timer(interval, self._publish)

        self.get_logger().warn(
            "compute_health_mock_node laeuft -- Mock-Werte, KEINE echte NUC-/Akku-Telemetrie. "
            "Nicht in production verwenden."
        )

    def _publish(self):
        valid = bool(self.get_parameter("compute_power_valid").value)
        self.power_pub.publish(Bool(data=valid))

        undervoltage = bool(self.get_parameter("nuc_undervoltage_warning").value)
        pack1 = float(self.get_parameter("battery_pack_1_percent").value)
        pack2 = float(self.get_parameter("battery_pack_2_percent").value)
        diag = String()
        diag.data = (
            f"compute_power_valid={valid} nuc_undervoltage_warning={undervoltage} "
            f"battery_pack_1_percent={pack1:.1f} battery_pack_2_percent={pack2:.1f} (MOCK)"
        )
        self.diagnostics_pub.publish(diag)

        if undervoltage or not valid:
            self.get_logger().warn(
                f"MOCK: kontrolliertes Stoppen aller Robotikprozesse waere hier faellig "
                f"(compute_power_valid={valid}, nuc_undervoltage_warning={undervoltage}) -- "
                f"echtes Shutdown-Verhalten ist NICHT Teil dieses Mocks."
            )


def main(args=None):
    rclpy.init(args=args)
    node = ComputeHealthMockNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
