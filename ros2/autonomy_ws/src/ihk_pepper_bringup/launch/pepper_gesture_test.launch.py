"""
pepper_gesture_test: Pepper per SSH/qicli verbunden, NUR einzeln
freigegebene Gesten ueber die PlayGesture-Action ausloesbar
(Entwicklungsauftrag 1, Abschnitt 11). motion_capable bleibt in diesem
Modus IMMER false (kein Argument dafuer, kein supervisor_node gestartet)
-- Gesten laufen unabhaengig von SafetyGate.allow_motion (das gilt nur
fuer Nav2-Fahrbefehle), sind aber weiterhin einzeln ueber `ros2 action
send_goal /pepper_bridge/play_gesture ...` unter direkter Aufsicht
auszuloesen, NIE automatisch.

Startet NUR bridge_node -- kein Perception/Interaction/Navigation, damit
nichts automatisch eine Geste ausloest. bridge_node deklariert KEINE
eigenen ROS-Parameter fuer Host/Passwort (anders als ihk_pepper_audio) --
die Zugangsdaten kommen wie ueberall in diesem Projekt aus
Umgebungsvariablen (apps/web/config/config.py liest sie), NICHT aus
ROS-Launch-Argumenten. Vor dem Start:

    set -a && source apps/web/.env && set +a
    ros2 launch ihk_pepper_bringup pepper_gesture_test.launch.py

Danach z.B.:
    ros2 action send_goal /pepper_bridge/play_gesture \\
      ihk_pepper_interfaces/action/PlayGesture "{gesture_name: wave_right, speed_scale: 1.0}"
"""
from launch import LaunchDescription
from launch.actions import LogInfo
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        LogInfo(msg="pepper_gesture_test: NUR einzeln ausgeloeste Gesten, keine Bewegung."),

        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
        ),
    ])
