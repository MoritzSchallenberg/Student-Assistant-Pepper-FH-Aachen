"""
Reine Diagnose-Logik fuer die RealSense-Kamera (Entwicklungsauftrag 2,
Abschnitt 5 "AP2 -- RealSense-Hardwareprofil und Diagnose"). Kein ROS --
realsense_diagnostics_node.py ist der duenne ROS-Wrapper, gleiches Muster
wie head_pose_gate.py/camera_pose_gate_node.py.

Anders als head_pose_gate.check_head_pose (ein einzelner Gate-Wert)
sammelt check_realsense_diagnostics() ALLE gleichzeitig zutreffenden
Probleme -- ein Diagnoseknoten soll dem Betreiber zeigen, WAS konkret
fehlt, nicht nur DASS etwas fehlt. Jeder Fehlerfall fuehrt zu einem
sicheren ungueltigen Navigationszustand (valid=False), niemals zu einer
optimistischen Annahme bei fehlenden Daten.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# Gleiche Grenzen wie ihk_pepper_perception/deprojection.py, damit
# "ungueltige Tiefe" projektweit einheitlich definiert ist.
DEFAULT_MIN_VALID_DEPTH_M = 0.2
DEFAULT_MAX_VALID_DEPTH_M = 8.0


@dataclass
class RealsenseDiagnosticsResult:
    valid: bool
    reasons: List[str] = field(default_factory=list)


def check_realsense_diagnostics(
    *,
    color_topic_age_s: Optional[float],
    depth_topic_age_s: Optional[float],
    camera_info_topic_age_s: Optional[float],
    max_data_age_s: float,
    color_depth_sync_diff_s: Optional[float],
    max_sync_diff_s: float,
    measured_fps: Optional[float],
    min_fps: float,
    invalid_depth_fraction: Optional[float],
    max_invalid_depth_fraction: float,
    tf_to_base_available: bool,
    usb_type: Optional[str] = None,
    require_usb3: bool = True,
) -> RealsenseDiagnosticsResult:
    """Reine Funktion, keine Seiteneffekte. `None` bei einem Alter/einer
    Messgroesse bedeutet "noch nie empfangen" -- fuehrt IMMER zu einem
    Fehlergrund, niemals zu einem stillschweigenden "wird schon passen"."""
    reasons: List[str] = []

    if color_topic_age_s is None:
        reasons.append("rgb_topic_fehlt")
    elif color_topic_age_s > max_data_age_s:
        reasons.append("rgb_daten_veraltet")

    if depth_topic_age_s is None:
        reasons.append("depth_topic_fehlt")
    elif depth_topic_age_s > max_data_age_s:
        reasons.append("depth_daten_veraltet")

    if camera_info_topic_age_s is None:
        reasons.append("camera_info_topic_fehlt")
    elif camera_info_topic_age_s > max_data_age_s:
        reasons.append("camera_info_veraltet")

    if color_topic_age_s is None and depth_topic_age_s is None and camera_info_topic_age_s is None:
        reasons.append("kamera_nicht_vorhanden")

    if color_depth_sync_diff_s is not None and color_depth_sync_diff_s > max_sync_diff_s:
        reasons.append("zeitstempel_nicht_synchron")

    if measured_fps is not None and measured_fps < min_fps:
        reasons.append("bildrate_zu_niedrig")

    if invalid_depth_fraction is not None and invalid_depth_fraction > max_invalid_depth_fraction:
        reasons.append("ungueltiger_tiefenanteil_zu_hoch")

    if not tf_to_base_available:
        reasons.append("tf_zur_roboterbasis_fehlt")

    if require_usb3 and usb_type is not None and not usb_type.startswith("3"):
        reasons.append("usb_verbindung_ungeeignet")

    return RealsenseDiagnosticsResult(valid=(len(reasons) == 0), reasons=reasons)


def compute_invalid_depth_fraction(
    depth_image: np.ndarray,
    depth_scale_to_m: float = 1.0,
    min_valid_depth_m: float = DEFAULT_MIN_VALID_DEPTH_M,
    max_valid_depth_m: float = DEFAULT_MAX_VALID_DEPTH_M,
) -> float:
    """Anteil ungueltiger Pixel (0, NaN, Inf, ausserhalb des gueltigen
    Tiefenbereichs) am gesamten Tiefenbild -- gleiche Ungueltig-Kriterien
    wie ihk_pepper_perception/deprojection.py::estimate_patch_depth(), hier
    aber als Gesamtbild-Statistik fuer die Diagnose, nicht als
    Patch-Median fuer eine einzelne Personenposition."""
    if depth_image.size == 0:
        return 1.0
    depth_m = depth_image.astype(np.float64) * depth_scale_to_m
    finite = np.isfinite(depth_m)
    in_range = finite & (depth_m >= min_valid_depth_m) & (depth_m <= max_valid_depth_m)
    valid_count = np.count_nonzero(in_range)
    return 1.0 - (valid_count / depth_image.size)
