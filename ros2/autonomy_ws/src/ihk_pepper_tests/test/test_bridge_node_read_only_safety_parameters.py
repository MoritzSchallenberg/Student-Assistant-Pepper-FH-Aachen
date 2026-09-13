"""
Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 5/7 (Testpunkt 7): "Ein
Offline-Prozess darf nicht durch nachtraegliche ROS-Parameteraenderung
hardwarefaehig werden." Echter rclpy-Node (kein Fake) -- prueft, dass
dry_run/execution_profile/allow_head_motion/allow_arm_motion/
allow_torso_motion tatsaechlich als read_only deklariert sind: rclpy
selbst lehnt JEDEN nachtraeglichen set_parameters()-Versuch ab, mit
einer eindeutigen, von ROS2 selbst ausgesprochenen Fehlermeldung.

dry_run:=true (Default in dieser Konstruktion) -- keine echte SSH-
Verbindung, kein Hardwarezugriff.
"""
import rclpy

from ihk_pepper_bridge.bridge_node import PepperBridgeNode


def test_dry_run_and_execution_profile_and_motion_permissions_are_read_only():
    rclpy.init(args=["--ros-args", "-p", "dry_run:=true"])
    try:
        node = PepperBridgeNode()
        try:
            for param_name, new_value in (
                ("dry_run", False),
                ("execution_profile", "production"),
                ("allow_head_motion", True),
                ("allow_arm_motion", True),
                ("allow_torso_motion", True),
            ):
                from rclpy.parameter import Parameter
                result = node.set_parameters([Parameter(param_name, value=new_value)])[0]
                assert result.successful is False, (
                    f"'{param_name}' haette als read_only-Parameter eine Aenderung "
                    "ablehnen muessen, wurde aber akzeptiert."
                )
            # Die urspruenglichen, sicheren Werte bleiben unveraendert.
            assert node.get_parameter("dry_run").value is True
            assert node.get_parameter("execution_profile").value == "offline_mock"
            assert node.get_parameter("allow_head_motion").value is False
            assert node.get_parameter("allow_arm_motion").value is False
            assert node.get_parameter("allow_torso_motion").value is False
        finally:
            node.pepper.close() if hasattr(node.pepper, "close") else None
            node.destroy_node()
    finally:
        rclpy.shutdown()
