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
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


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
