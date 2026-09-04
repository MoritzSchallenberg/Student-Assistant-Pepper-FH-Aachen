"""
Reine Pruef-Logik fuer "ist der Kopf in der Navigations-Pose?"
(Entwicklungsauftrag 1, Abschnitt 3). Kein ROS -- camera_pose_gate_node.py
ist der duenne ROS-Wrapper darum, gleiches Muster wie
ihk_pepper_navigation/laser_filter_node.py (filter_ranges/is_stale).

Waehrend Navigation muss Peppers Kopf eine definierte Pose einnehmen,
sonst verfaelscht die bewegte RealSense-Kopfkamera visuelle Odometrie
und projizierte Hindernisdaten (Entwicklungsauftrag 1, Abschnitt 3/6).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class HeadPoseCheckResult:
    valid: bool
    reason: str


def check_head_pose(
    head_yaw_rad: Optional[float],
    head_pitch_rad: Optional[float],
    target_yaw_rad: float,
    target_pitch_rad: float,
    tolerance_rad: float,
    joint_state_age_s: float,
    max_age_s: float,
) -> HeadPoseCheckResult:
    """Reine Funktion, keine Seiteneffekte. valid=False ist IMMER der
    sichere Ausgang bei fehlenden/veralteten Daten -- niemals ein
    stillschweigendes "wird schon passen"."""
    if head_yaw_rad is None or head_pitch_rad is None:
        return HeadPoseCheckResult(False, "keine_joint_states_empfangen")
    if joint_state_age_s > max_age_s:
        return HeadPoseCheckResult(False, "joint_states_veraltet")
    yaw_error = abs(head_yaw_rad - target_yaw_rad)
    pitch_error = abs(head_pitch_rad - target_pitch_rad)
    if yaw_error > tolerance_rad:
        return HeadPoseCheckResult(False, f"yaw_abweichung_{yaw_error:.3f}rad")
    if pitch_error > tolerance_rad:
        return HeadPoseCheckResult(False, f"pitch_abweichung_{pitch_error:.3f}rad")
    return HeadPoseCheckResult(True, "ok")
