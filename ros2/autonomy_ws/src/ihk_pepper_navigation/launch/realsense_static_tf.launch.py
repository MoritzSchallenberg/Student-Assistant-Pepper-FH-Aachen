"""
Publiziert die statische TF-Kette von Peppers base_link bis zum
Wurzel-Frame des RealSense-Treibers (Entwicklungsauftrag 1, Abschnitt 3):

    base_link -> realsense_mount_link -> camera_link (Treiber uebernimmt ab hier)

Liest die Montagewerte aus config/realsense_extrinsics.yaml -- ALLE
Werte dort sind aktuell Platzhalter (translation=0, rotation=Identitaet),
siehe docs/REALSENSE_CALIBRATION.md. realsense_mount_link -> camera_link
ist bewusst Identitaet (der Montagepunkt IST die Kameraposition in diesem
einfachen Modell) -- alles ab camera_link (color/depth/optical frames)
publiziert der realsense2_camera-Treiber bereits selbst korrekt.

NICHT live getestet -- keine RealSense-Hardware in dieser Session
angeschlossen, siehe docs/DEVELOPMENT_ORDER_01_REPORT.md.

Entwicklungsauftrag 2, AP3: zusaetzlich zur is_calibrated-Warnung wird
jetzt eine Plausibilitaetspruefung der Werte selbst durchgefuehrt
(extrinsics_plausibility.py) -- erkennt grob falsche/vertauschte Zahlen
(z.B. Meter statt Zentimeter), ersetzt aber keine echte Vermessung.

Volle beabsichtigte TF-Kette dieses Auftrags (siehe
docs/REALSENSE_NAVIGATION_ARCHITECTURE.md):
    map -> odom -> base_link -> realsense_mount_link -> camera_link
map->odom kommt aus der RTAB-Map-Lokalisierung (AP5), odom->base_link
aus der RTAB-Map-Odometrie (AP4) -- beide existieren zum Zeitpunkt
dieses Launch-Files noch nicht. Die hier publizierte Teilkette
(base_link->camera_link) ist bewusst STATISCH: sie modelliert nicht
Peppers echte Kopf-Kinematik (HeadYaw/HeadPitch), sondern geht von einer
FESTEN Kopfpose aus. Das ist nur deshalb sicher, weil
camera_pose_gate_node (Entwicklungsauftrag 1) die Bewegungsfreigabe
entzieht, sobald der Kopf von dieser Pose abweicht (head_navigation_pose_valid)
-- eine echte kinematische Kette waere praeziser, ist fuer den Umfang
dieses Auftrags aber nicht erforderlich.
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

from ihk_pepper_navigation.extrinsics_plausibility import check_extrinsics_plausibility


def generate_launch_description():
    config_path = os.path.join(
        get_package_share_directory('ihk_pepper_navigation'),
        'config', 'realsense_extrinsics.yaml')
    with open(config_path) as f:
        cfg = yaml.safe_load(f)['realsense_extrinsics']

    if not cfg.get('is_calibrated', False):
        print(
            'WARNUNG: realsense_extrinsics.yaml ist NICHT kalibriert '
            '(is_calibrated=false) -- Translation/Rotation sind Platzhalter, '
            'siehe docs/REALSENSE_CALIBRATION.md.')

    plausibility = check_extrinsics_plausibility(cfg['translation_m'], cfg['rotation_rpy_rad'])
    if not plausibility.plausible:
        print(
            f'WARNUNG: realsense_extrinsics.yaml Werte unplausibel '
            f'({plausibility.reason}) -- bitte pruefen, siehe '
            f'docs/REALSENSE_CALIBRATION.md.')

    t = cfg['translation_m']
    r = cfg['rotation_rpy_rad']

    return LaunchDescription([
        Node(
            package='tf2_ros', executable='static_transform_publisher',
            name='realsense_mount_tf',
            arguments=[
                '--x', str(t['x']), '--y', str(t['y']), '--z', str(t['z']),
                '--roll', str(r['roll']), '--pitch', str(r['pitch']), '--yaw', str(r['yaw']),
                '--frame-id', cfg['parent_frame'],
                '--child-frame-id', cfg['mount_frame'],
            ],
        ),
        Node(
            package='tf2_ros', executable='static_transform_publisher',
            name='realsense_mount_to_camera_root_tf',
            arguments=[
                '--frame-id', cfg['mount_frame'],
                '--child-frame-id', cfg['camera_root_frame'],
            ],
        ),
    ])
