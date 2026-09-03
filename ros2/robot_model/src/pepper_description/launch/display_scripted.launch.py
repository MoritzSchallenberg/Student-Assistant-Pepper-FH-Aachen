"""
Wie display.launch.py, aber OHNE joint_state_publisher_gui -- fuer die
skriptgesteuerte Bewegung per sim_qicli.py (das publiziert selbst auf
/joint_states, wuerde sonst mit den Schiebereglern kollidieren).

Nutzung:
    ros2 launch pepper_description display_scripted.launch.py
    # in einem zweiten Terminal:
    python3 sim_qicli.py
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
            package="rviz2",
            executable="rviz2",
            arguments=["-d", rviz_config],
        ),
    ])
