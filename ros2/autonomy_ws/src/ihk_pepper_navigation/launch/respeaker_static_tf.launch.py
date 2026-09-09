"""
Publiziert die statische TF-Kette vom dynamischen Head-Frame zum
ReSpeaker-Mikrofonarray (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6):

    Head -> respeaker_link (statisch, Montagepunkt)

Head selbst ist dynamisch (robot_state_publisher + /joint_states, siehe
pepper_robot_state.launch.py) -- die eigentliche Kopf-Kinematik
(HeadYaw/HeadPitch) ist bereits in der Kette base_link->torso->Neck->Head
enthalten, respeaker_link haengt nur noch STARR darunter (der Montagepunkt
IST die Mikrofonarray-Position in diesem einfachen Modell, analog zu
realsense_static_tf.launch.py::realsense_mount_link).

Liest die Montagewerte aus config/respeaker_extrinsics.yaml -- ALLE
Werte dort sind aktuell Platzhalter (translation=0, rotation=Identitaet),
siehe docs/RESPEAKER_CALIBRATION.md.

NICHT live getestet -- kein ReSpeaker Core v2.0 in dieser Session
angeschlossen.
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
        'config', 'respeaker_extrinsics.yaml')
    with open(config_path) as f:
        cfg = yaml.safe_load(f)['respeaker_extrinsics']

    if not cfg.get('is_calibrated', False):
        print(
            'WARNUNG: respeaker_extrinsics.yaml ist NICHT kalibriert '
            '(is_calibrated=false) -- Translation/Rotation sind Platzhalter, '
            'siehe docs/RESPEAKER_CALIBRATION.md.')

    plausibility = check_extrinsics_plausibility(cfg['translation_m'], cfg['rotation_rpy_rad'])
    if not plausibility.plausible:
        print(
            f'WARNUNG: respeaker_extrinsics.yaml Werte unplausibel '
            f'({plausibility.reason}) -- bitte pruefen, siehe '
            f'docs/RESPEAKER_CALIBRATION.md.')

    t = cfg['translation_m']
    r = cfg['rotation_rpy_rad']

    return LaunchDescription([
        Node(
            package='tf2_ros', executable='static_transform_publisher',
            name='respeaker_mount_tf',
            arguments=[
                '--x', str(t['x']), '--y', str(t['y']), '--z', str(t['z']),
                '--roll', str(r['roll']), '--pitch', str(r['pitch']), '--yaw', str(r['yaw']),
                '--frame-id', cfg['parent_frame'],
                '--child-frame-id', cfg['mount_frame'],
            ],
        ),
    ])
