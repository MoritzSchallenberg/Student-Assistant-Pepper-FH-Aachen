"""
NICHT GETESTET (depthimage_to_laserscan nicht installiert, siehe
docs/DEVELOPMENT_ORDER_02_REPORT.md AP1 fuer die Install-Befehle).

Wandelt ein Tiefenbild in einen LaserScan um (genutzt von Nav2s
Costmaps, siehe AP6 in nav2_params.yaml). `image_topic`/`camera_info_topic`
sind Launch-Argumente. Default seit Entwicklungsauftrag 2 (AP6):
RealSense-Topics (Auftrag Abschnitt 1: "duerfen keine ... Kamera-... Daten
von Pepper verwenden" fuer Navigation/Hinderniserkennung) -- Peppers
eigene Tiefenkamera bleibt als expliziter Override moeglich (Nicht-
Navigations-Zwecke), ist aber nicht mehr der Standard.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory("ihk_pepper_navigation"),
        "config", "depthimage_to_laserscan.yaml",
    )

    image_topic = LaunchConfiguration("image_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")

    return LaunchDescription([
        DeclareLaunchArgument(
            "image_topic", default_value="/camera/aligned_depth_to_color/image_raw",
            description="Tiefenbild-Quelle, Standard RealSense (Auftrag 2: "
                        "RealSense-only fuer Navigation). Fuer Peppers "
                        "eigene Kamera explizit auf /camera/depth/image_raw "
                        "umbiegen (nicht Navigation-Zweck).",
        ),
        DeclareLaunchArgument(
            "camera_info_topic", default_value="/camera/color/camera_info",
        ),
        Node(
            package="depthimage_to_laserscan",
            executable="depthimage_to_laserscan_node",
            name="depthimage_to_laserscan",
            output="screen",
            parameters=[config],
            remappings=[
                ("depth", image_topic),
                ("depth_camera_info", camera_info_topic),
                ("scan", "/navigation/depth_scan"),
            ],
        ),
    ])
