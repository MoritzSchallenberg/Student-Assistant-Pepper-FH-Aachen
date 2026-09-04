"""
RGB-D-Mapping ausschliesslich mit der RealSense (Entwicklungsauftrag 2,
Abschnitt 8 "AP5"). Startet realsense_odometry.launch.py (AP4, liefert
/realsense/odom) und rtabmap_slam/rtabmap im Mapping-Modus
(Mem/IncrementalMemory=true -- die Karte waechst, statt nur gegen eine
bestehende zu lokalisieren).

Speicherung nur auf explizitem Befehl (Auftrag Abschnitt 8): dieser Modus
wird nie automatisch von einem Bringup-Launch mitgestartet, sondern muss
gezielt aufgerufen werden. database_path bekommt standardmaessig einen
ZEITGESTEMPELTEN Namen unter maps/ -- jeder Lauf erzeugt eine neue,
eindeutig benannte Datenbank, nichts wird stillschweigend ueberschrieben.
RTAB-Map selbst schreibt waehrend des Laufs kontinuierlich in diese Datei
(so ist das Werkzeug gebaut) -- das explizite "Speichern" besteht darin,
DIESEN Modus bewusst zu starten und die erzeugte Datei danach gezielt zu
uebernehmen/umzubenennen, nicht in einem zusaetzlichen Speicher-Knopf.

Mapping- und Lokalisierungsmodus duerfen nicht gleichzeitig aktiv sein
(mode_lock.py) -- beide wuerden sonst widersprechende Annahmen ueber
map->odom treffen.

NICHT live gegen echte RGB-D-Daten getestet -- keine RealSense-Hardware
in dieser Session angeschlossen.
"""
import os
import time

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.event_handlers import OnShutdown
from launch.actions import RegisterEventHandler
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from ihk_pepper_navigation.mode_lock import ModeLockError, acquire_mode_lock, release_mode_lock

_lock_state = {"path": None}


def _acquire_lock(context, lock_dir_arg, *args, **kwargs):
    lock_dir = context.perform_substitution(lock_dir_arg)
    try:
        _lock_state["path"] = acquire_mode_lock(lock_dir, "mapping", ["localization"])
    except ModeLockError as e:
        raise RuntimeError(str(e)) from e
    return []


def _release_lock(*args, **kwargs):
    release_mode_lock(_lock_state["path"])
    return []


def generate_launch_description():
    camera_name = LaunchConfiguration("camera_name")
    nav_share = get_package_share_directory("ihk_pepper_navigation")
    # BEWUSST NICHT unter dem Paket-share-Verzeichnis (install/... wird bei
    # jedem colcon build ueberschrieben/geloescht, und eine .db-Datei duerfte
    # laut CI-Regel ohnehin nie ins Git-Repo -- siehe .github/workflows/ci.yml,
    # Pruefung auf verbotene Dateitypen). Default: Heimverzeichnis, ausserhalb
    # jedes von Git/Colcon verwalteten Baums.
    default_db = os.path.join(
        os.path.expanduser("~/.ihk_pepper_maps"),
        f"mapping_{time.strftime('%Y%m%d_%H%M%S')}.db")
    os.makedirs(os.path.dirname(default_db), exist_ok=True)

    return LaunchDescription([
        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("database_path", default_value=default_db,
            description="Eindeutiger, zeitgestempelter Pfad -- ueberschreibt "
                        "standardmaessig keine vorhandene Karte."),
        DeclareLaunchArgument("mode_lock_dir", default_value="/tmp/ihk_pepper_nav_mode_lock"),

        OpaqueFunction(function=lambda context: _acquire_lock(
            context, LaunchConfiguration("mode_lock_dir"))),
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
                "Mem/IncrementalMemory": "true",
                "Mem/InitWMWithAllNodes": "false",
            }],
            remappings=[
                ("rgb/image", [camera_name, "/color/image_raw"]),
                ("depth/image", [camera_name, "/aligned_depth_to_color/image_raw"]),
                ("rgb/camera_info", [camera_name, "/color/camera_info"]),
                ("odom", "/realsense/odom"),
            ],
        ),
    ])
