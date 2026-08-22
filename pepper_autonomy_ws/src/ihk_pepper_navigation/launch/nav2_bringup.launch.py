"""
NICHT GETESTET (Nav2/robot_localization/twist_mux/nav2_collision_monitor
sind auf diesem Entwicklungssystem nicht installiert, siehe
IMPLEMENTATION_REPORT.md fuer die Install-Befehle).

Befehlskette (Auftrag Abschnitt 6):
    Nav2 -> Velocity Smoother -> Collision Monitor -> Twist Mux ->
    /cmd_vel -> naoqi_driver2 -> Pepper

SICHERHEIT (Auftrag Abschnitt 3.2): `allow_motion` ist HIER NUR ein
Launch-Parameter, der bestimmt, ob die Bewegungs-Nodes (AMCL, Controller,
Planner, Velocity Smoother, Collision Monitor, Twist Mux, person_approach)
UEBERHAUPT GESTARTET werden -- er ersetzt NICHT die eigentliche
Sicherheits-Freigabe zur Laufzeit (die kommt ausschliesslich vom
Supervisor/SafetyGate, siehe ihk_pepper_interaction). Mit
allow_motion:=false (Standard) werden diese Nodes gar nicht erst
gestartet -- die sicherste moegliche Voreinstellung.

Nutzung (sobald die Pakete installiert sind, NIEMALS unbeaufsichtigt am
echten Roboter, siehe Auftrag 3.2):
    ros2 launch ihk_pepper_navigation nav2_bringup.launch.py \\
        allow_motion:=true map:=/pfad/zur/karte.yaml
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
    ekf_config = os.path.join(share, "config", "robot_localization.yaml")

    allow_motion = LaunchConfiguration("allow_motion")
    map_yaml = LaunchConfiguration("map")

    motion_on = IfCondition(allow_motion)

    return LaunchDescription([
        DeclareLaunchArgument(
            "allow_motion", default_value="false",
            description="Startet die Bewegungs-Nodes ueberhaupt erst bei "
                        "'true' (Auftrag 3.2: sicherer Default = false). "
                        "Ersetzt NICHT die Laufzeit-Sicherheitsfreigabe "
                        "des Supervisors.",
        ),
        DeclareLaunchArgument(
            "map", default_value="",
            description="Pfad zur mit slam_toolbox erstellten Karte (.yaml).",
        ),

        # Immer sicher zu starten (reine Sensor-/Zustands-Aufbereitung,
        # keine Aktuatorik) -- laesst sich unabhaengig von allow_motion
        # z.B. fuer die Tablet-UI/Diagnose nutzen.
        Node(
            package="ihk_pepper_navigation", executable="laser_filter_node",
            name="laser_filter", output="screen",
        ),
        Node(
            package="robot_localization", executable="ekf_node",
            name="ekf_filter_node", output="screen",
            parameters=[ekf_config],
        ),

        # Ab hier: nur mit allow_motion:=true.
        Node(
            package="nav2_amcl", executable="amcl", name="amcl",
            output="screen", parameters=[nav2_config], condition=motion_on,
        ),
        Node(
            package="nav2_map_server", executable="map_server", name="map_server",
            output="screen", parameters=[{"yaml_filename": map_yaml}], condition=motion_on,
        ),
        Node(
            package="nav2_controller", executable="controller_server",
            name="controller_server", output="screen",
            parameters=[nav2_config], condition=motion_on,
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
            remappings=[("cmd_vel", "cmd_vel_raw"), ("cmd_vel_smoothed", "cmd_vel_smoothed")],
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
                "node_names": ["map_server", "amcl", "controller_server",
                                "planner_server", "behavior_server",
                                "bt_navigator", "waypoint_follower",
                                "velocity_smoother", "collision_monitor"],
            }],
        ),
        Node(
            package="twist_mux", executable="twist_mux", name="twist_mux",
            output="screen", parameters=[nav2_config], condition=motion_on,
            remappings=[("cmd_vel_out", "/cmd_vel")],
        ),

        # Personen anfahren/begleiten -- nutzt SafetyState als eigentliche
        # Freigabe (siehe person_approach_node.py), wird aber ebenfalls
        # nur gestartet wenn allow_motion:=true (defense in depth).
        Node(
            package="ihk_pepper_navigation", executable="person_approach_node",
            name="person_approach", output="screen", condition=motion_on,
        ),
    ])
