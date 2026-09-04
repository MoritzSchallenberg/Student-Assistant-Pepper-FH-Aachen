"""
Startet den RealSense-Kameratreiber (ros-jazzy-realsense2-camera, vendor-
Paket) mit einem konservativen, konfigurierbaren Profil (Entwicklungsauftrag
1, Abschnitt 3). Kein Kameramodell wird hier fest angenommen -- alle
Parameter sind Launch-Argumente mit Defaults, die je nach tatsaechlich
angeschlossenem Geraet ueberschrieben werden koennen.

WICHTIG (ehrlich, siehe docs/DEVELOPMENT_ORDER_01_REPORT.md): dieses
Launch-File ist NICHT live gegen eine echte RealSense getestet -- keine
Hardware in dieser Session angeschlossen (nur `lsusb` geprueft, kein
Intel-RealSense-Geraet sichtbar). ros-jazzy-realsense2-camera ist zwar
installiert, aber `ros2 launch` selbst wurde nie ausgefuehrt. Startet den
Treiber, PERCEPTION_NODE muss separat mit passenden Topic-Parametern
gestartet werden (siehe ihk_pepper_perception/config/perception_params.yaml,
auskommentierter RealSense-Block).

Publiziert (Topic-Namen je nach camera_name/camera_namespace-Parametern):
  /camera/color/image_raw, /camera/color/camera_info
  /camera/aligned_depth_to_color/image_raw (durch align_depth.enable=true)
Keine Pointcloud (pointcloud.enable bleibt false -- Entwicklungsauftrag 1
nutzt Tiefenbilder direkt, siehe ihk_pepper_perception/deprojection.py).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    rs_launch_file = os.path.join(
        get_package_share_directory('realsense2_camera'), 'launch', 'rs_launch.py')

    return LaunchDescription([
        DeclareLaunchArgument('serial_no', default_value="''",
            description='Leer = erstes gefundenes Geraet. Explizit setzen, '
                        'sobald mehr als eine RealSense im Einsatz ist.'),
        DeclareLaunchArgument('camera_name', default_value='camera'),
        DeclareLaunchArgument('camera_namespace', default_value='camera'),
        DeclareLaunchArgument('color_width', default_value='640'),
        DeclareLaunchArgument('color_height', default_value='480'),
        DeclareLaunchArgument('color_fps', default_value='15.0',
            description='Konservativ (nicht die maximal moegliche Bildrate) -- '
                        'siehe docs/REALSENSE_CALIBRATION.md.'),
        DeclareLaunchArgument('depth_width', default_value='640'),
        DeclareLaunchArgument('depth_height', default_value='480'),
        DeclareLaunchArgument('depth_fps', default_value='15.0'),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(rs_launch_file),
            launch_arguments={
                'serial_no': LaunchConfiguration('serial_no'),
                'camera_name': LaunchConfiguration('camera_name'),
                'camera_namespace': LaunchConfiguration('camera_namespace'),
                'enable_color': 'true',
                'rgb_camera.color_profile': [
                    LaunchConfiguration('color_width'), 'x',
                    LaunchConfiguration('color_height'), 'x',
                    LaunchConfiguration('color_fps'),
                ],
                'enable_depth': 'true',
                'depth_module.depth_profile': [
                    LaunchConfiguration('depth_width'), 'x',
                    LaunchConfiguration('depth_height'), 'x',
                    LaunchConfiguration('depth_fps'),
                ],
                'align_depth.enable': 'true',
                'pointcloud.enable': 'false',
                'enable_sync': 'true',
            }.items(),
        ),
    ])
