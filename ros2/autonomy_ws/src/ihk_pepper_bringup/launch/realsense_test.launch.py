"""
realsense_test: echte RealSense-Kamera, Wahrnehmung/Tiefendaten/Diagnose
-- KEINE Bewegung, kein Pepper-Bridge, kein Nav2/Mock-Nav2
(Entwicklungsauftrag 1, Abschnitt 11). Fuer isoliertes Pruefen von
Kamera/Wahrnehmung, bevor irgendetwas mit Pepper selbst zusammenspielt.

Startet: RealSense-Treiber (realsense_bringup.launch.py), statische
Montage-TF (realsense_static_tf.launch.py), perception_node MIT auf
RealSense-Topics umgebogenen Parametern, camera_pose_gate_node.

NICHT live getestet -- keine RealSense-Hardware in dieser Session
angeschlossen (siehe docs/DEVELOPMENT_ORDER_01_REPORT.md).
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    camera_name = LaunchConfiguration("camera_name")
    nav_share = get_package_share_directory("ihk_pepper_navigation")

    return LaunchDescription([
        LogInfo(msg="realsense_test: echte Kamera, KEINE Bewegung, kein Pepper-Bridge."),

        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("serial_no", default_value="''"),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_bringup.launch.py")),
            launch_arguments={
                "camera_name": camera_name,
                "serial_no": LaunchConfiguration("serial_no"),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_static_tf.launch.py")),
        ),

        Node(
            package="ihk_pepper_perception", executable="perception_node", output="screen",
            parameters=[{
                "image_topic": ["/", camera_name, "/color/image_raw"],
                "depth_topic": ["/", camera_name, "/aligned_depth_to_color/image_raw"],
                "camera_info_topic": ["/", camera_name, "/color/camera_info"],
                "camera_frame": "camera_color_optical_frame",
                "source_camera_name": "realsense",
                "depth_scale_to_m": 0.001,
            }],
        ),
        Node(
            package="ihk_pepper_navigation", executable="camera_pose_gate_node",
            output="screen",
        ),
    ])
