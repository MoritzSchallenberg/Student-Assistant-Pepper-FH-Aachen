"""
NICHT GETESTET (slam_toolbox nicht installiert, siehe docs/IMPLEMENTATION_REPORT.md).

Startet slam_toolbox im Mapping-Modus + den laser_filter_node (der IST
getestet, siehe laser_filter_node.py) + optional robot_localization fuer
eine stabile odom->base_link Transformation.

WARNUNG (siehe slam_toolbox_mapping.yaml): Peppers eingebauter Laser ist
fuer dynamisches Mapping waehrend der Fahrt vermutlich zu langsam/grob --
Kartierung im Stand/Dreh-Modus empfohlen.

Nutzung (sobald slam_toolbox installiert ist):
    ros2 launch ihk_pepper_navigation slam_mapping.launch.py
Karte speichern (Nav2-Tooling):
    ros2 run nav2_map_server map_saver_cli -f ~/pepper_map
"""
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory("ihk_pepper_navigation")
    slam_config = os.path.join(share, "config", "slam_toolbox_mapping.yaml")
    ekf_config = os.path.join(share, "config", "robot_localization.yaml")

    return LaunchDescription([
        Node(
            package="ihk_pepper_navigation", executable="laser_filter_node",
            name="laser_filter", output="screen",
        ),
        Node(
            package="robot_localization", executable="ekf_node",
            name="ekf_filter_node", output="screen",
            parameters=[ekf_config],
        ),
        Node(
            package="slam_toolbox", executable="sync_slam_toolbox_node",
            name="slam_toolbox", output="screen",
            parameters=[slam_config],
        ),
    ])
