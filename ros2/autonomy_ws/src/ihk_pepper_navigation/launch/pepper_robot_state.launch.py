"""
Startet robot_state_publisher mit Peppers echtem URDF, damit die
Gelenkkette base_link -> torso -> Neck -> Head TATSAECHLICH dynamisch
aus /joint_states berechnet wird (Entwicklungsauftrag 04-B, AP6.1,
Abschnitt 6) -- ersetzt die vorherige, bewusst als Vereinfachung
dokumentierte STATISCHE base_link->camera_link/base_link->respeaker_link-
Transformation (siehe realsense_static_tf.launch.py/
respeaker_static_tf.launch.py, deren parent_frame jetzt "Head" statt
"base_link" ist).

WICHTIGE VORAUSSETZUNG: das URDF liegt im SEPARATEN Workspace
`ros2/robot_model` (Paket `pepper_description`, siehe README.md:
"Offline-Simulation, kein Pepper noetig") -- NICHT in `ros2/autonomy_ws`.
Vor jedem Start eines ReSpeaker-/RealSense-Modus muss deshalb ZUSAETZLICH

    source ros2/robot_model/install/setup.bash

gesourct sein (nach dem autonomy_ws-Overlay), sonst wirft
get_package_share_directory("pepper_description") einen klaren
PackageNotFoundError -- kein stillschweigender Fallback auf eine
erfundene/leere Kette.

Publiziert selbst KEINE /joint_states -- das macht
ihk_pepper_bridge/bridge_node.py periodisch (HeadYaw/HeadPitch, aus
pepper_client.get_angle(), fail-closed: unerreichbarer Pepper liefert
keine Werte, robot_state_publisher haelt dann einfach die letzten
bekannten/Default-Winkel).
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    share_dir = get_package_share_directory("pepper_description")
    urdf_path = os.path.join(share_dir, "urdf", "pepper.urdf")
    with open(urdf_path, "r") as f:
        robot_description = f.read()

    return LaunchDescription([
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="pepper_robot_state_publisher",
            output="screen",
            parameters=[{"robot_description": robot_description}],
        ),
    ])
