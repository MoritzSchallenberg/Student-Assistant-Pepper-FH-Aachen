"""
RGB-D Visual Odometry ausschliesslich mit der RealSense (Entwicklungsauftrag
2, Abschnitt 7 "AP4"). Startet rtabmap_odom/rgbd_odometry (bereits per apt
installiert, siehe docs/DEVELOPMENT_ORDER_02_REPORT.md) gegen die
RealSense-Color-/Tiefen-/CameraInfo-Topics, dazu odometry_health_node zur
fortlaufenden Bewertung (Tracking-Verlust/Kovarianz/Alter).

Verbindliche Regeln aus dem Auftrag: KEINE Pepper-Odometrie, KEINE
Pepper-IMU, KEINE Pepper-Laser/Sonare. Die RealSense-eigene IMU wird NICHT
verwendet (kein erkanntes Modell mit IMU in dieser Session bestaetigt,
siehe realsense_diagnostics_node/AP2) -- rein visuelle RGB-D-Odometrie.

Ausgabe: /realsense/odom (nav_msgs/Odometry), TF odom -> base_link,
/odom_info (rtabmap_msgs/OdomInfo, von odometry_health_node ausgewertet).

Startet NICHT die RealSense-Kamera selbst (siehe realsense_bringup.launch.py)
und NICHT die Mapping-/Lokalisierungs-Sitzung (AP5, realsense_mapping.launch.py/
realsense_localization.launch.py) -- reine Odometrie, wiederverwendbar von
beiden.

NICHT live gegen echte RGB-D-Daten getestet -- keine RealSense-Hardware in
dieser Session angeschlossen. rgbd_odometry selbst wurde gestartet und
beendet sich sauber ohne Kamera (kein Crash, wartet auf Eingangsdaten).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    camera_name = LaunchConfiguration("camera_name")

    return LaunchDescription([
        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("robot_base_frame", default_value="base_link"),
        DeclareLaunchArgument("odom_frame_id", default_value="odom"),
        DeclareLaunchArgument("approx_sync", default_value="true",
            description="RealSense Color-/Tiefenbild sind i.d.R. nicht "
                        "exakt zeitgleich gestempelt -- approximative "
                        "Synchronisierung noetig."),

        Node(
            package="rtabmap_odom", executable="rgbd_odometry", output="screen",
            name="realsense_rgbd_odometry",
            parameters=[{
                "frame_id": LaunchConfiguration("robot_base_frame"),
                "odom_frame_id": LaunchConfiguration("odom_frame_id"),
                "publish_tf": True,
                "approx_sync": LaunchConfiguration("approx_sync"),
                # Auftrag Abschnitt 7: keine Pepper-Sensoren -- ausschliesslich
                # RGB-D von der RealSense. Kein IMU-Topic konfiguriert.
                "guess_frame_id": "",
                "wait_imu_to_init": False,
            }],
            remappings=[
                ("rgb/image", [camera_name, "/color/image_raw"]),
                ("depth/image", [camera_name, "/aligned_depth_to_color/image_raw"]),
                ("rgb/camera_info", [camera_name, "/color/camera_info"]),
                ("odom", "/realsense/odom"),
            ],
        ),
        Node(
            package="ihk_pepper_navigation", executable="odometry_health_node",
            output="screen",
        ),
    ])
