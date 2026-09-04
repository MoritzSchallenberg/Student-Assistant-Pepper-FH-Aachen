"""
mapping: RealSense-Odometrie + RTAB-Map-Mapping, standardmaessig KEINE
Ausgabe an Pepper (Entwicklungsauftrag 2, Abschnitt 14 "AP11"). Duenner
Wrapper um ihk_pepper_navigation/launch/realsense_mapping.launch.py
(AP5) -- siehe dort fuer die volle Dokumentation (database_path,
mode_lock.py-Mutex gegen realsense_localization_test).

    ros2 launch ihk_pepper_bringup realsense_mapping.launch.py

Fuer einen eigenen database_path das navigation-Paket-Launch direkt
aufrufen (siehe docs/MAPPING_AND_LOCALIZATION.md):
    ros2 launch ihk_pepper_navigation realsense_mapping.launch.py \\
        database_path:=/pfad/zur/karte.db

NICHT live gegen echte RGB-D-Daten getestet -- keine RealSense-Hardware
in dieser Session angeschlossen (siehe docs/DEVELOPMENT_ORDER_02_REPORT.md).
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    nav_share = get_package_share_directory("ihk_pepper_navigation")
    return LaunchDescription([
        LogInfo(msg="mapping: RealSense-Odometrie + RTAB-Map-Mapping, keine Bewegung."),

        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("mode_lock_dir", default_value="/tmp/ihk_pepper_nav_mode_lock"),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_mapping.launch.py")),
            launch_arguments={
                "camera_name": LaunchConfiguration("camera_name"),
                "mode_lock_dir": LaunchConfiguration("mode_lock_dir"),
            }.items(),
        ),
    ])
