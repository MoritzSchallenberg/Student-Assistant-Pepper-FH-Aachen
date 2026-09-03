"""
Zeigt Peppers 3D-Modell in RViz2, steuerbar per Schieberegler
(joint_state_publisher_gui) -- komplett offline, kein echter Roboter noetig.

Nutzung:
    colcon build
    source install/setup.bash
    ros2 launch pepper_description display.launch.py
"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    share_dir = get_package_share_directory("pepper_description")
    urdf_path = os.path.join(share_dir, "urdf", "pepper.urdf")
    rviz_config = os.path.join(share_dir, "pepper_offline.rviz")
    with open(urdf_path, "r") as f:
        robot_description = f.read()

    return LaunchDescription([
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
        ),
        Node(
            package="joint_state_publisher_gui",
            executable="joint_state_publisher_gui",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            arguments=["-d", rviz_config],
        ),
    ])
