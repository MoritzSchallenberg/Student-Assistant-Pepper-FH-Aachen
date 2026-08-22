"""
Minimal-Start fuer den Kern-Dialogablauf (Bridge + Audio + Dialogmanager,
OHNE Wahrnehmung/Interaktions-FSM/Praesentation/Navigation). Nuetzlich fuer
schnelle Tests und Debugging, siehe IMPLEMENTATION_REPORT.md.

    set -a && source flask_wrapper/.env && set +a
    ros2 launch ihk_pepper_bringup dialog_only.launch.py
"""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    audio_source_kind = LaunchConfiguration("audio_source_kind")
    pepper_host = LaunchConfiguration("pepper_host")
    pepper_password = LaunchConfiguration("pepper_password")

    return LaunchDescription([
        DeclareLaunchArgument("audio_source_kind", default_value="pepper_pulseaudio"),
        DeclareLaunchArgument("pepper_host", default_value=os.environ.get("PEPPER_QI_HOST", "")),
        DeclareLaunchArgument("pepper_password", default_value=os.environ.get("PEPPER_QI_PASSWORD", "")),

        Node(package="ihk_pepper_bridge", executable="bridge_node",
             namespace="pepper_bridge", output="screen"),
        Node(package="ihk_pepper_audio", executable="audio_node", output="screen",
             parameters=[{"source_kind": audio_source_kind, "pepper_host": pepper_host,
                          "pepper_password": pepper_password}]),
        Node(package="ihk_pepper_dialog", executable="dialog_manager_node", output="screen"),
    ])
