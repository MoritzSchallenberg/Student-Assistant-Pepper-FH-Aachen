"""
NICHT GETESTET (voller Nav2-Stack ist auf diesem Entwicklungssystem
nicht installiert, siehe docs/DEVELOPMENT_ORDER_02_REPORT.md AP1 fuer
die exakten Install-Befehle).

Ueberarbeitet in Entwicklungsauftrag 2 (AP6/AP7/AP8) fuer RealSense-only
Navigation. Setzt voraus, dass VORHER bereits laeuft:
    ros2 launch ihk_pepper_navigation realsense_localization.launch.py \\
        database_path:=/pfad/zur/karte.db
(liefert map->odom->base_link ueber RTAB-Map, siehe AP4/AP5) -- dieses
Launch startet dagegen absichtlich NICHT selbst amcl/map_server/
robot_localization mit Peppers eigener Odometrie/IMU mehr (Auftrag
Abschnitt 1: "duerfen keine Odometrie-... von Pepper verwenden").

Befehlskette (Auftrag Abschnitt 10, repariert -- siehe
docs/DEVELOPMENT_ORDER_02_REPORT.md AP7 fuer die vier urspruenglich
gefundenen Verdrahtungsfehler):
    Nav2 controller_server -> cmd_vel_raw
    -> Velocity Smoother -> cmd_vel_smoothed_raw
    -> Collision Monitor -> cmd_vel_smoothed
    -> Motion Guard (AP8) -> /cmd_vel
    -> naoqi_driver2 -> Pepper

SICHERHEIT (Auftrag Abschnitt 3.2/AP8): `allow_motion` ist HIER NUR ein
Launch-Parameter, der bestimmt, ob die Bewegungs-Nodes UEBERHAUPT
GESTARTET werden -- er ersetzt NICHT die eigentliche Sicherheits-
Freigabe zur Laufzeit (die kommt von SafetyGate UND zusaetzlich, als
letzte Instanz, von Motion Guard). Mit allow_motion:=false (Standard)
werden diese Nodes gar nicht erst gestartet. `enable_live_motion` (an
Motion Guard durchgereicht) ist eine ZWEITE, unabhaengige Sperre --
beide muessen explizit gesetzt sein, bevor ueberhaupt ein reales
Fahrsignal Pepper erreichen kann (navigation_dry_run/navigation_live,
siehe AP11).

Nutzung (sobald die Pakete installiert sind, NIEMALS unbeaufsichtigt am
echten Roboter, siehe Auftrag 3.2):
    ros2 launch ihk_pepper_navigation nav2_bringup.launch.py \\
        allow_motion:=true enable_live_motion:=true
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory("ihk_pepper_navigation")
    nav2_config = os.path.join(share, "config", "nav2_params.yaml")

    allow_motion = LaunchConfiguration("allow_motion")
    enable_live_motion = LaunchConfiguration("enable_live_motion")

    motion_on = IfCondition(allow_motion)

    return LaunchDescription([
        DeclareLaunchArgument(
            "allow_motion", default_value="false",
            description="Startet die Nav2-Bewegungs-Nodes ueberhaupt erst "
                        "bei 'true' (Auftrag 3.2: sicherer Default = "
                        "false). Ersetzt NICHT die Laufzeit-Sicherheits-"
                        "freigabe (SafetyGate + Motion Guard).",
        ),
        DeclareLaunchArgument(
            "enable_live_motion", default_value="false",
            description="An motion_guard_node durchgereicht -- zweite, "
                        "unabhaengige Sperre (AP8). Beide Parameter "
                        "muessen 'true' sein, bevor ueberhaupt ein "
                        "Fahrsignal /cmd_vel erreichen kann.",
        ),

        # Immer sicher zu starten (reine Sensor-Aufbereitung, keine
        # Aktuatorik) -- laesst sich unabhaengig von allow_motion nutzen.
        Node(
            package="ihk_pepper_navigation", executable="laser_filter_node",
            name="laser_filter", output="screen",
        ),

        # Ab hier: nur mit allow_motion:=true. KEIN amcl/map_server/
        # robot_localization mehr -- map->odom->base_link kommt aus
        # realsense_localization.launch.py (AP5), das VOR diesem Launch
        # separat gestartet sein muss.
        Node(
            package="nav2_controller", executable="controller_server",
            name="controller_server", output="screen",
            parameters=[nav2_config], condition=motion_on,
            remappings=[("cmd_vel", "cmd_vel_raw")],
        ),
        Node(
            package="nav2_planner", executable="planner_server",
            name="planner_server", output="screen",
            parameters=[nav2_config], condition=motion_on,
        ),
        Node(
            package="nav2_behaviors", executable="behavior_server",
            name="behavior_server", output="screen",
            parameters=[nav2_config], condition=motion_on,
        ),
        Node(
            package="nav2_bt_navigator", executable="bt_navigator",
            name="bt_navigator", output="screen",
            parameters=[nav2_config], condition=motion_on,
        ),
        Node(
            package="nav2_waypoint_follower", executable="waypoint_follower",
            name="waypoint_follower", output="screen",
            parameters=[nav2_config], condition=motion_on,
        ),
        Node(
            package="nav2_velocity_smoother", executable="velocity_smoother",
            name="velocity_smoother", output="screen",
            parameters=[nav2_config], condition=motion_on,
            # AP7-Verdrahtungsfix: Ausgabe jetzt eindeutig "cmd_vel_smoothed_raw"
            # (vorher identisch zu Collision Monitors Ausgabetopic benannt).
            remappings=[("cmd_vel", "cmd_vel_raw"),
                        ("cmd_vel_smoothed", "cmd_vel_smoothed_raw")],
        ),
        Node(
            package="nav2_collision_monitor", executable="collision_monitor",
            name="collision_monitor", output="screen",
            parameters=[nav2_config], condition=motion_on,
        ),
        Node(
            package="nav2_lifecycle_manager", executable="lifecycle_manager",
            name="lifecycle_manager_navigation", output="screen",
            condition=motion_on,
            parameters=[{
                "autostart": True,
                "node_names": ["controller_server", "planner_server",
                                "behavior_server", "bt_navigator",
                                "waypoint_follower", "velocity_smoother",
                                "collision_monitor"],
            }],
        ),

        # Motion Guard (AP8): letzte Instanz vor /cmd_vel, ersetzt Twist
        # Mux. Liest Collision Monitors Ausgabe direkt.
        Node(
            package="ihk_pepper_interaction", executable="motion_guard_node",
            name="motion_guard", output="screen", condition=motion_on,
            parameters=[{
                "cmd_vel_in_topic": "cmd_vel_smoothed",
                "cmd_vel_out_topic": "/cmd_vel",
                "enable_live_motion": enable_live_motion,
            }],
        ),

        # Personen anfahren/begleiten -- nutzt SafetyState als eigentliche
        # Freigabe (siehe person_approach_node.py), wird aber ebenfalls
        # nur gestartet wenn allow_motion:=true (defense in depth).
        Node(
            package="ihk_pepper_navigation", executable="person_approach_node",
            name="person_approach", output="screen", condition=motion_on,
        ),
    ])
