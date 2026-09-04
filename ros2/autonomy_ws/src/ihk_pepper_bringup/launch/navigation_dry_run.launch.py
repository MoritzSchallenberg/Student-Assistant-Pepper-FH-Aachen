"""
navigation_dry_run: vollstaendige Planung und Personenannaeherung gegen
den ECHTEN Nav2-Stack (nicht mock_nav2_server) -- Fahrbefehle werden in
einen Test-Sink umgeleitet, KEIN Publisher zum echten Pepper-/cmd_vel
(Entwicklungsauftrag 2, Abschnitt 14 "AP11").

Unterschied zu offline_test: dort laeuft ausschliesslich mock_nav2_server
(kein echter Nav2-Code wird ueberhaupt ausgefuehrt). Hier laeuft der
ECHTE Nav2-Stack (Controller/Planner/Costmap/Collision Monitor/Velocity
Smoother/Motion Guard) gegen echte RealSense-Daten -- nur die letzte
Verbindung von Motion Guard zu /cmd_vel wird auf
"navigation_dry_run/cmd_vel_sink" umgebogen (siehe nav2_bringup.launch.py,
Parameter cmd_vel_out_topic). Motion Guard selbst wird trotzdem
vollstaendig durchlaufen -- das ist der Sinn dieses Modus: den echten
Sicherheits-/Planungscode pruefen, ohne dass ein Fahrbefehl je
naoqi_driver2 erreichen kann.

Voraussetzung: realsense_localization.launch.py (map->odom->base_link)
laeuft als Teil dieses Launches mit -- database_path ist PFLICHT.

    ros2 launch ihk_pepper_bringup navigation_dry_run.launch.py \\
        database_path:=/pfad/zur/karte.db

NICHT live getestet -- kein Nav2-Vollstack installiert, keine RealSense-
Hardware in dieser Session (siehe docs/DEVELOPMENT_ORDER_02_REPORT.md
AP1). Nur Launch-Struktur verifiziert (--show-args).
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
        LogInfo(msg="navigation_dry_run: echter Nav2-Stack, /cmd_vel in "
                    "Test-Sink umgeleitet -- KEIN Pfad zu naoqi_driver2."),

        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("database_path", default_value="",
            description="PFLICHT: Pfad zu einer vorhandenen .db-Datei."),
        DeclareLaunchArgument("mode_lock_dir", default_value="/tmp/ihk_pepper_nav_mode_lock"),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_localization.launch.py")),
            launch_arguments={
                "camera_name": camera_name,
                "database_path": LaunchConfiguration("database_path"),
                "mode_lock_dir": LaunchConfiguration("mode_lock_dir"),
            }.items(),
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
        Node(
            package="ihk_pepper_navigation", executable="realsense_diagnostics_node",
            output="screen",
        ),

        # Echter Nav2-Stack -- cmd_vel_out_topic auf einen harmlosen
        # Sink umgebogen (siehe Moduldocstring). enable_live_motion:=true,
        # damit Motion Guard tatsaechlich vollstaendig durchlaufen wird
        # (sonst wuerde er strukturell IMMER blockieren und der Test
        # wuerde nichts pruefen) -- die Sicherheit kommt hier aus dem
        # Sink-Topic, nicht aus enable_live_motion:=false.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "nav2_bringup.launch.py")),
            launch_arguments={
                "allow_motion": "true",
                "enable_live_motion": "true",
                "cmd_vel_out_topic": "navigation_dry_run/cmd_vel_sink",
            }.items(),
        ),

        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
            parameters=[{"dry_run": True}],
        ),
        Node(
            package="ihk_pepper_interaction", executable="supervisor_node", output="screen",
            parameters=[{"motion_capable": True}],
        ),
        Node(
            package="ihk_pepper_interaction", executable="compute_health_mock_node",
            output="screen",
        ),
        Node(
            package="ihk_pepper_behavior_tree", executable="bt_executor_node",
            output="screen",
        ),
    ])
