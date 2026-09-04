"""
localization_test: gespeicherte Karte + Lokalisierung, KEINE Bewegung
(Entwicklungsauftrag 2, Abschnitt 14 "AP11"). Duenner Wrapper um
ihk_pepper_navigation/launch/realsense_localization.launch.py (AP5).

    ros2 launch ihk_pepper_bringup realsense_localization_test.launch.py \\
        database_path:=/pfad/zur/karte.db

database_path ist PFLICHT (wird vor dem Start auf Existenz geprueft,
kein stiller Fallback -- siehe dortige Dokumentation).

NICHT live gegen echte RGB-D-Daten/eine echte Karte getestet -- keine
RealSense-Hardware in dieser Session angeschlossen.
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
        LogInfo(msg="localization_test: gespeicherte Karte, KEINE Bewegung."),

        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("database_path", default_value="",
            description="PFLICHT: Pfad zu einer vorhandenen .db-Datei."),
        DeclareLaunchArgument("mode_lock_dir", default_value="/tmp/ihk_pepper_nav_mode_lock"),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_localization.launch.py")),
            launch_arguments={
                "camera_name": LaunchConfiguration("camera_name"),
                "database_path": LaunchConfiguration("database_path"),
                "mode_lock_dir": LaunchConfiguration("mode_lock_dir"),
            }.items(),
        ),
    ])
