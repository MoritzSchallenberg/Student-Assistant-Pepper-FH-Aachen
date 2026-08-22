"""
NICHT GETESTET (depthimage_to_laserscan nicht installiert, siehe
IMPLEMENTATION_REPORT.md). Syntax mit `python3 -c "import ast; ast.parse(...)"`
geprueft, NICHT mit `ros2 launch` (Paket fehlt).

Wandelt ein Tiefenbild in einen LaserScan um. `image_topic`/`camera_info_topic`
sind Launch-Argumente -- Umschalten zwischen Peppers eingebauter Kamera und
einer optionalen RealSense ist damit eine reine Parameteraenderung, kein
Code-Wechsel (Auftrag-Anforderung).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory("ihk_pepper_navigation"),
        "config", "depthimage_to_laserscan.yaml",
    )

    image_topic = LaunchConfiguration("image_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")

    return LaunchDescription([
        DeclareLaunchArgument(
            "image_topic", default_value="/camera/depth/image_raw",
            description="Tiefenbild-Quelle. Fuer eine RealSense z.B. "
                        "/camera/camera/depth/image_rect_raw",
        ),
        DeclareLaunchArgument(
            "camera_info_topic", default_value="/camera/depth/camera_info",
        ),
        Node(
            package="depthimage_to_laserscan",
            executable="depthimage_to_laserscan_node",
            name="depthimage_to_laserscan",
            output="screen",
            parameters=[config],
            remappings=[
                ("depth", image_topic),
                ("depth_camera_info", camera_info_topic),
                ("scan", "/navigation/depth_scan"),
            ],
        ),
    ])
