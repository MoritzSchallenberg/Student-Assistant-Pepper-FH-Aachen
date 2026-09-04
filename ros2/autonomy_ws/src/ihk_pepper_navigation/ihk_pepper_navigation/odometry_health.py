"""
Reine Bewertungslogik fuer die RGB-D-Visual-Odometry-Gesundheit
(Entwicklungsauftrag 2, Abschnitt 7 "AP4"). Kein ROS -- der Node-Wrapper
(realsense_odometry_health_node.py) liest rtabmap_msgs/OdomInfo aus und
ruft diese Funktion mit bereits ausgepackten Rohwerten auf, gleiches
Muster wie head_pose_gate.py/check_head_pose.

Track-Verlust (odom_info.lost) oder eine zu hohe Kovarianz fuehrt IMMER
zu valid=False, NIE zu einer stillschweigend weiterverwendeten
Fantasieposition -- Auftrag Abschnitt 7: "keine Fantasieposition bei
Trackingverlust veroeffentlichen".
"""
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class OdometryHealthResult:
    valid: bool
    reason: str


def check_odometry_health(
    lost: bool,
    translation_variance: float,
    max_translation_variance: float,
    data_age_s: Optional[float],
    max_data_age_s: float,
    inliers: Optional[int] = None,
    min_inliers: Optional[int] = None,
) -> OdometryHealthResult:
    """Reine Funktion, keine Seiteneffekte. valid=False ist immer der
    sichere Ausgang -- gleiches Prinzip wie ueberall im Projekt."""
    if data_age_s is None:
        return OdometryHealthResult(False, "keine_odometrie_empfangen")
    if data_age_s > max_data_age_s:
        return OdometryHealthResult(False, "odometrie_veraltet")
    if lost:
        return OdometryHealthResult(False, "odometrie_tracking_verloren")
    if translation_variance > max_translation_variance:
        return OdometryHealthResult(False, f"odometrie_kovarianz_zu_hoch_{translation_variance:.4f}")
    if inliers is not None and min_inliers is not None and inliers < min_inliers:
        return OdometryHealthResult(False, f"odometrie_zu_wenig_inliers_{inliers}")
    return OdometryHealthResult(True, "ok")


def max_translation_variance_from_covariance(covariance_36: Sequence[float]) -> float:
    """rtabmap_msgs/OdomInfo.covariance ist eine 6x6-Kovarianzmatrix
    (row-major, Reihenfolge x,y,z,roll,pitch,yaw wie ueberall in ROS).
    Gibt die groesste der drei Translationsvarianzen (Diagonalelemente
    x,y,z) zurueck -- ein einzelner grosser Ausreisser soll nicht durch
    einen Mittelwert verschleiert werden."""
    # Diagonalindizes einer 6x6-Matrix (row-major): 0, 7, 14 fuer x,y,z.
    return max(covariance_36[0], covariance_36[7], covariance_36[14])
