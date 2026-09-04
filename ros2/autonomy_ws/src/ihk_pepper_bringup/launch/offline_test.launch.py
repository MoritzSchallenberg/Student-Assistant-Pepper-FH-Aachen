"""
offline_test: vollstaendiger Software-Stack OHNE Pepper und OHNE Kamera
(Entwicklungsauftrag 1, Abschnitt 11). motion_capable ist fest false
(kein Argument dafuer -- kein Weg, das in diesem Modus zu umgehen), der
Nav2-Pfad laeuft ausschliesslich gegen mock_nav2_server (published NIE
/cmd_vel, siehe dortige Moduldoku).

Startet: bridge_node (verbindet sich nur lazy bei echtem Aufruf, siehe
pepper_client.py -- schadet ohne Pepper nicht), supervisor_node,
compute_health_mock_node, perception_node (ohne echte Kamera -- bleibt
idle, keine Tracks, kein Crash), camera_pose_gate_node, mock_nav2_server,
person_approach_node, bt_executor_node.

EHRLICH (siehe docs/DEVELOPMENT_ORDER_01_REPORT.md): dieser Modus startet
den kompletten Graphen sicher, generiert aber selbst KEINE synthetischen
RGB-D-/Personendaten -- ohne einen manuellen/skriptgesteuerten Publisher
auf /perception_node/person_tracks bzw. /wave_gesture_events bleibt der
Behavior Tree im IdleAttractSubtree. Ein automatisierter Ende-zu-Ende-Test
mit echten synthetischen Daten ist als offener Punkt dokumentiert.
"""
from launch import LaunchDescription
from launch.actions import LogInfo
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        LogInfo(msg="offline_test: kein Pepper, keine Kamera, kein echtes /cmd_vel."),

        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
        ),
        Node(
            package="ihk_pepper_interaction", executable="supervisor_node", output="screen",
            parameters=[{"motion_capable": False}],
        ),
        Node(
            package="ihk_pepper_interaction", executable="compute_health_mock_node",
            output="screen",
        ),
        Node(
            package="ihk_pepper_perception", executable="perception_node", output="screen",
        ),
        Node(
            package="ihk_pepper_navigation", executable="camera_pose_gate_node",
            output="screen",
        ),
        Node(
            package="ihk_pepper_navigation", executable="mock_nav2_server", output="screen",
        ),
        Node(
            package="ihk_pepper_navigation", executable="person_approach_node",
            output="screen",
        ),
        Node(
            package="ihk_pepper_behavior_tree", executable="bt_executor_node",
            output="screen",
        ),
    ])
