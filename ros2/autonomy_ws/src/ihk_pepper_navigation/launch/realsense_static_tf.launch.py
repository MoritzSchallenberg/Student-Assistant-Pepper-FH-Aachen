"""
Publiziert die statische TF-Kette von Peppers Kopf bis zum Wurzel-Frame
des RealSense-Treibers (urspruenglich Entwicklungsauftrag 1, Abschnitt 3;
parent_frame auf "Head" umgestellt in Entwicklungsauftrag 04-B, AP6.1,
Abschnitt 6):

    Head -> realsense_mount_link -> camera_link (Treiber uebernimmt ab hier)

Head ist SEIT AP6.1 Peppers ECHTES, dynamisches Kopf-Frame --
robot_state_publisher (siehe pepper_robot_state.launch.py) berechnet
base_link -> torso -> Neck -> Head live aus /joint_states
(HeadYaw/HeadPitch). Dieses Launch-File publiziert nur noch die
STARRE Teilkette Head -> realsense_mount_link (der Montagepunkt IST die
Kameraposition in diesem einfachen Modell) -- die eigentliche
Kopf-Kinematik ist bereits in der robot_state_publisher-Kette enthalten,
KEINE feste base_link->Kamera-Annahme mehr.

Frueherer Stand (bis AP6.1, siehe Commit-Historie): parent_frame war
"base_link", eine bewusst dokumentierte Vereinfachung ("modelliert nicht
Peppers echte Kopf-Kinematik"), abgesichert allein durch
camera_pose_gate_node (entzieht die Bewegungsfreigabe, sobald der Kopf
von der Navigations-Pose abweicht). Diese Sperre BLEIBT als zusaetzliche
Verteidigung in der Tiefe bestehen (Auftrag AP6.1 Abschnitt 6: "Die
bestehende Navigationssperre bei abweichender Kopfpose bleibt erhalten") --
Navigation ist NICHT automatisch fuer beliebige Kopfbewegungen freigegeben,
nur weil die TF-Kette jetzt korrekt ist.

Liest die Montagewerte aus config/realsense_extrinsics.yaml -- ALLE
Werte dort sind aktuell Platzhalter (translation=0, rotation=Identitaet),
siehe docs/REALSENSE_CALIBRATION.md.

NICHT live getestet -- keine RealSense-Hardware in dieser Session
angeschlossen, siehe docs/DEVELOPMENT_ORDER_01_REPORT.md.

Entwicklungsauftrag 2, AP3: zusaetzlich zur is_calibrated-Warnung wird
jetzt eine Plausibilitaetspruefung der Werte selbst durchgefuehrt
(extrinsics_plausibility.py) -- erkennt grob falsche/vertauschte Zahlen
(z.B. Meter statt Zentimeter), ersetzt aber keine echte Vermessung.

Volle beabsichtigte TF-Kette (siehe docs/REALSENSE_NAVIGATION_ARCHITECTURE.md,
docs/RESPEAKER_CORE_V2_INTEGRATION.md):
    map -> odom -> base_link -> torso -> Neck -> Head -> realsense_mount_link -> camera_link
map->odom kommt aus der RTAB-Map-Lokalisierung (AP5), odom->base_link
aus der RTAB-Map-Odometrie (AP4).
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
