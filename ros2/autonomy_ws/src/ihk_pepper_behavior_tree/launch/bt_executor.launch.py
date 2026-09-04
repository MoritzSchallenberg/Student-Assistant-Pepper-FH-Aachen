# Startet den Behavior-Tree-Ausfuehrungs-Node. Braucht die anderen
# ihk_pepper_bridge/-interaction/-presentation/-navigation-Nodes bereits
# laufend (siehe ihk_pepper_bringup), sonst schlagen die einzelnen
# Action-Aufrufe im Baum einfach mit FAILURE fehl (kein Crash).
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'tree_file', default_value='',
            description='Leer = pepper_main.xml aus dem share/-Ordner dieses Pakets.'),
        DeclareLaunchArgument('tick_rate_hz', default_value='10.0'),
        DeclareLaunchArgument('groot2_port', default_value='1667'),

        Node(
            package='ihk_pepper_behavior_tree', executable='bt_executor_node',
            name='bt_executor', output='screen',
            parameters=[{
                'tree_file': LaunchConfiguration('tree_file'),
                'tick_rate_hz': LaunchConfiguration('tick_rate_hz'),
                'groot2_port': LaunchConfiguration('groot2_port'),
            }],
        ),
    ])
