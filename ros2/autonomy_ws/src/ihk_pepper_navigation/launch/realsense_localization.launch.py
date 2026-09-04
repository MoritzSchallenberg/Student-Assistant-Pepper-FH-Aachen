"""
Lokalisierung gegen eine vorhandene RTAB-Map-Karte, ausschliesslich mit
der RealSense (Entwicklungsauftrag 2, Abschnitt 8 "AP5"). Startet
realsense_odometry.launch.py (AP4) und rtabmap_slam/rtabmap im
Lokalisierungsmodus (Mem/IncrementalMemory=false -- die geladene Karte
wird NICHT veraendert/erweitert, nur zur Lokalisierung genutzt).

database_path MUSS explizit auf eine vorhandene, per realsense_mapping.launch.py
erzeugte .db-Datei zeigen -- kein stiller Fallback auf eine geratene
Karte. Ohne bestaetigte Startposition/gueltige Datenbank keine Fahrt
(Auftrag Abschnitt 8) -- hier bereits beim Start erzwungen: fehlende
oder nicht existierende database_path bricht das Launch sofort ab.

Mapping- und Lokalisierungsmodus duerfen nicht gleichzeitig aktiv sein
(mode_lock.py).

NICHT live gegen echte RGB-D-Daten/eine echte Karte getestet -- keine
RealSense-Hardware in dieser Session angeschlossen.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnShutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from ihk_pepper_navigation.mode_lock import ModeLockError, acquire_mode_lock, release_mode_lock

_lock_state = {"path": None}


def _validate_and_acquire(context, database_path_arg, lock_dir_arg, *args, **kwargs):
    db_path = context.perform_substitution(database_path_arg)
    if not db_path:
        raise RuntimeError(
            "realsense_localization.launch.py: database_path ist leer -- "
            "eine vorhandene, per realsense_mapping.launch.py erzeugte "
            ".db-Datei muss explizit angegeben werden, kein stiller Fallback.")
    if not os.path.isfile(db_path):
        raise RuntimeError(
            f"realsense_localization.launch.py: database_path '{db_path}' "
            "existiert nicht -- keine Lokalisierung ohne echte Karte.")

    lock_dir = context.perform_substitution(lock_dir_arg)
    try:
        _lock_state["path"] = acquire_mode_lock(lock_dir, "localization", ["mapping"])
    except ModeLockError as e:
        raise RuntimeError(str(e)) from e
    return []


def _release_lock(*args, **kwargs):
    release_mode_lock(_lock_state["path"])
    return []


def generate_launch_description():
    camera_name = LaunchConfiguration("camera_name")
    nav_share = get_package_share_directory("ihk_pepper_navigation")

    return LaunchDescription([
        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("database_path", default_value="",
            description="PFLICHT: Pfad zu einer vorhandenen .db-Datei aus "
                        "realsense_mapping.launch.py."),
        DeclareLaunchArgument("mode_lock_dir", default_value="/tmp/ihk_pepper_nav_mode_lock"),

        OpaqueFunction(function=lambda context: _validate_and_acquire(
            context, LaunchConfiguration("database_path"), LaunchConfiguration("mode_lock_dir"))),
        RegisterEventHandler(OnShutdown(on_shutdown=_release_lock)),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_odometry.launch.py")),
            launch_arguments={"camera_name": camera_name}.items(),
        ),

        Node(
            package="rtabmap_slam", executable="rtabmap", output="screen",
            name="rtabmap",
            parameters=[{
                "frame_id": "base_link",
                "subscribe_depth": True,
                "approx_sync": True,
                "database_path": LaunchConfiguration("database_path"),
                "Mem/IncrementalMemory": "false",
                "Mem/InitWMWithAllNodes": "true",
            }],
            remappings=[
                ("rgb/image", [camera_name, "/color/image_raw"]),
                ("depth/image", [camera_name, "/aligned_depth_to_color/image_raw"]),
                ("rgb/camera_info", [camera_name, "/color/camera_info"]),
                ("odom", "/realsense/odom"),
            ],
        ),
        Node(
            package="ihk_pepper_navigation", executable="localization_health_node",
            output="screen",
        ),
    ])
