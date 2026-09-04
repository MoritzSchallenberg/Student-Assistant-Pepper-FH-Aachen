"""
navigation_live: ECHTE Livebewegung an Pepper (Entwicklungsauftrag 2,
Abschnitt 14 "AP11"). Technisch vorbereitet, standardmaessig GESPERRT.

*** WARNUNG *** Dieses Launch-File wurde in dieser Entwicklungssitzung
NIEMALS ausgefuehrt und darf von Claude auch nicht eigenmaechtig
ausgefuehrt werden (Auftrag: "darf von Claude in diesem Auftrag nicht am
echten Pepper gestartet werden, benoetigt spaeter eine bewusste,
beaufsichtigte Freigabe durch den Nutzer"). Nur per --show-args auf
korrekte Launch-Struktur geprueft.

Struktur identisch zu navigation_dry_run.launch.py, ABER:
  - cmd_vel_out_topic bleibt das ECHTE /cmd_vel (kein Sink).
  - Ein zusaetzliches Pflicht-Argument `i_understand_this_moves_pepper`
    muss explizit auf "true" gesetzt werden (kein Default) -- rein
    software-seitige Huerde gegen versehentliches Copy-Paste eines
    anderen Modus-Befehls, ERSETZT NICHT eine echte Sicherheitsabnahme.
  - motion_capable UND die explizite /set_motion_permission-Freigabe
    (SafetyGate-Zwei-Schluessel-System) sind weiterhin zusaetzlich
    erforderlich, GENAU wie in jedem anderen Modus.

Voraussetzungen vor jedem realen Einsatz (Auftrag Abschnitt 18, NICHT in
dieser Session erfuellt): RealSense-Abdeckung, Kamerakalibrierung, TF,
Lokalisierung, Costmaps, Collision Monitor, Stoppkette, NUC-Stromversorgung
und Gespraechsabstand MUESSEN einzeln nachgewiesen sein -- siehe
docs/NAVIGATION_SAFETY_ACCEPTANCE.md.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _confirm_or_abort(context, confirm_arg, *args, **kwargs):
    if context.perform_substitution(confirm_arg) != "true":
        raise RuntimeError(
            "navigation_live.launch.py: i_understand_this_moves_pepper "
            "muss explizit auf 'true' gesetzt werden. Dieses Launch "
            "bewegt Pepper WIRKLICH -- siehe docs/NAVIGATION_SAFETY_ACCEPTANCE.md "
            "fuer die Voraussetzungen, die vorher einzeln nachgewiesen "
            "sein muessen. NIEMALS unbeaufsichtigt starten.")
    return []


def generate_launch_description():
    camera_name = LaunchConfiguration("camera_name")
    nav_share = get_package_share_directory("ihk_pepper_navigation")

    return LaunchDescription([
        LogInfo(msg="*** navigation_live: ECHTE BEWEGUNG -- NIE unbeaufsichtigt starten. ***"),

        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("database_path", default_value="",
            description="PFLICHT: Pfad zu einer vorhandenen .db-Datei."),
        DeclareLaunchArgument("mode_lock_dir", default_value="/tmp/ihk_pepper_nav_mode_lock"),
        DeclareLaunchArgument("i_understand_this_moves_pepper", default_value="false",
            description="MUSS explizit 'true' sein -- keine Sicherheitsfunktion, "
                        "nur ein Schutz gegen versehentliches Kopieren eines "
                        "anderen Modus-Befehls."),

        OpaqueFunction(function=lambda context: _confirm_or_abort(
            context, LaunchConfiguration("i_understand_this_moves_pepper"))),

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

        # KEIN cmd_vel_out_topic-Override -- das echte /cmd_vel.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "nav2_bringup.launch.py")),
            launch_arguments={
                "allow_motion": "true",
                "enable_live_motion": "true",
            }.items(),
        ),

        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
            parameters=[{"dry_run": False}],
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
