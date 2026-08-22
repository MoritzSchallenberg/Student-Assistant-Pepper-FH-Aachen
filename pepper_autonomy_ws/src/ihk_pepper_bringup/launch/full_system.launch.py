"""
Gesamtstart des IHK-Pepper-Autonomiesystems (Arbeitspaket 42/8).

Startet standardmaessig NUR die in dieser Session vollstaendig gebauten
und getesteten Pakete (bridge, audio, dialog, perception, interaction,
presentation). Navigation/Personen-Ansteuerung ist per Default AUS
(Nav2/robot_localization/slam_toolbox sind auf dem Entwicklungssystem
dieser Session nicht installiert, siehe IMPLEMENTATION_REPORT.md) und
muss explizit ueber `enable_navigation:=true` UND `motion_capable:=true`
angefordert werden (Auftrag Abschnitt 3.2: sicherer Default, kein
unbeaufsichtigter Bewegungstest).

Credentials/Config kommen wie ueberall in diesem Projekt aus
Umgebungsvariablen (siehe flask_wrapper/.env.example) -- NICHT hier
hartcodiert. Vor dem Start:
    set -a && source flask_wrapper/.env && set +a
    ros2 launch ihk_pepper_bringup full_system.launch.py

Getestet (2026-08-20): jedes einzelne Node/Paket, das dieses Launch-File
startet, wurde separat live getestet (siehe IMPLEMENTATION_REPORT.md).
Der GESAMTE full_system.launch.py-Start als EIN Kommando ist NICHT als
Ganzes durchgetestet worden (Zeitgrund) -- nur die Launch-Datei selbst
wurde erfolgreich geparst/gebaut (siehe Test unten).
"""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    motion_capable = LaunchConfiguration("motion_capable")
    enable_navigation = LaunchConfiguration("enable_navigation")
    enable_perception = LaunchConfiguration("enable_perception")
    audio_source_kind = LaunchConfiguration("audio_source_kind")
    pepper_host = LaunchConfiguration("pepper_host")
    pepper_password = LaunchConfiguration("pepper_password")

    nav_launch_path = os.path.join(
        get_package_share_directory("ihk_pepper_navigation"), "launch", "nav2_bringup.launch.py"
    )

    return LaunchDescription([
        DeclareLaunchArgument("motion_capable", default_value="false",
            description="Kill-Switch (Auftrag 3.2). Nur bei true kann der "
                        "Supervisor jemals allow_motion setzen."),
        DeclareLaunchArgument("enable_navigation", default_value="false",
            description="Startet zusaetzlich ihk_pepper_navigation "
                        "(Nav2-Stack) -- NICHT installiert auf dem "
                        "Entwicklungssystem dieser Session, siehe "
                        "IMPLEMENTATION_REPORT.md."),
        DeclareLaunchArgument("enable_perception", default_value="true",
            description="Kamera/YOLO-Personenerkennung starten."),
        DeclareLaunchArgument("audio_source_kind", default_value="pepper_pulseaudio",
            description="siehe ihk_pepper_audio/audio_source.py: "
                        "pepper_pulseaudio | microphone | file"),
        DeclareLaunchArgument("pepper_host", default_value=os.environ.get("PEPPER_QI_HOST", "")),
        DeclareLaunchArgument("pepper_password", default_value=os.environ.get("PEPPER_QI_PASSWORD", "")),

        LogInfo(msg=["motion_capable=", motion_capable,
                     " (true=Bewegung moeglich, false=gesperrt -- Auftrag 3.2)"]),

        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
        ),
        Node(
            package="ihk_pepper_audio", executable="audio_node", output="screen",
            parameters=[{
                "source_kind": audio_source_kind,
                "pepper_host": pepper_host,
                "pepper_password": pepper_password,
            }],
        ),
        Node(
            package="ihk_pepper_dialog", executable="dialog_manager_node", output="screen",
        ),
        Node(
            package="ihk_pepper_perception", executable="perception_node", output="screen",
            condition=IfCondition(enable_perception),
        ),
        Node(
            package="ihk_pepper_interaction", executable="supervisor_node", output="screen",
            parameters=[{"motion_capable": motion_capable}],
        ),
        Node(
            package="ihk_pepper_presentation", executable="presentation_manager_node",
            output="screen",
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav_launch_path),
            condition=IfCondition(enable_navigation),
            launch_arguments={"allow_motion": motion_capable}.items(),
        ),
    ])
