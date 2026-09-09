"""
Reine Transformationslogik fuer Schallrichtungen (Entwicklungsauftrag
04-B, AP6.1, Abschnitt 3.1/12): transformiert einen horizontalen
Richtungs-EINHEITSVEKTOR (KEINEN Punkt) vom Mikrofonarray-Frame
(respeaker_link) in Peppers Basis-Frame (base_link), zum ORIGINALEN
Messzeitpunkt -- nicht zum aktuellen Zeitpunkt. Eine Richtung hat keine
Position, deshalb tf2_geometry_msgs.do_transform_vector3() (reine
Rotation) statt do_transform_point() (das bereits an anderer Stelle,
perception_node.py::_transform_to_base_frame, fuer echte Personen-
positionen verwendet wird und dort korrekt ist -- hier waere es falsch,
weil es faelschlich eine Translation einrechnen wuerde).

Bestaetigter Fund (Auftrag Abschnitt 3.1): der von audio_node.py
gelieferte Rohwinkel wurde bislang UNVERAENDERT als bereits-in-base_link-
Winkel an den Behavior Tree weitergereicht -- ohne jede Transformation.

Die eigentliche TF-Lookup wird als injizierte Funktion (tf_lookup_fn)
uebergeben -- dieses Modul importiert damit zwar ROS-Nachrichtentypen
(fuer tf2_geometry_msgs.do_transform_vector3/Vector3Stamped), aber
KEINEN rclpy.node.Node und braucht keinen echten TF-Baum, um getestet
zu werden (siehe sound_direction_transform_node.py fuer die duenne
ROS-Anbindung, die tf_lookup_fn an tf2_ros.Buffer.lookup_transform
bindet -- gleiche Ausnahme-Konvention wie
person_approach_node.py::_get_robot_position_in_frame/
perception_node.py::_transform_to_base_frame:
LookupException/ConnectivityException/ExtrapolationException).
"""
import math
from dataclasses import dataclass
from typing import Callable, Optional

import tf2_geometry_msgs  # noqa: F401 -- registriert do_transform_vector3 fuer Vector3Stamped
from geometry_msgs.msg import Vector3Stamped

# Ein Rotations-Quaternion muss (annaehernd) Einheitslaenge haben -- ein
# deutlich abweichender Wert deutet auf eine kaputte/erfundene TF hin
# (Auftrag Abschnitt 3.1: "invalide Quaternion darf nie stillschweigend
# verwendet werden").
QUATERNION_NORM_TOLERANCE = 0.05


@dataclass(frozen=True)
class TransformResult:
    azimuth_rad: float
    confidence: float
    valid: bool
    reason: str


def azimuth_to_unit_vector(azimuth_rad: float):
    """0.0 = geradeaus, positiv = nach links (REP-103/Rechte-Hand-Regel
    um die Z-Achse) -- dieselbe Konvention wie SoundDirection.msg."""
    return math.cos(azimuth_rad), math.sin(azimuth_rad), 0.0


def unit_vector_to_azimuth(x: float, y: float, z: float) -> float:
    return math.atan2(y, x)


def is_measurement_too_old(stamp_ns: int, now_ns: int, max_age_s: Optional[float]) -> bool:
    """Fail-closed-Kriterium fuer ein zu altes Original-Mass (Auftrag
    Abschnitt 3.1: eine spaete Ankunft/verzoegerte Verarbeitung darf
    keine laengst veraltete Richtung als aktuell ausgeben). max_age_s<=0
    oder None deaktiviert die Pruefung nicht heimlich -- es bedeutet
    explizit 'keine Altersgrenze', muss also bewusst so konfiguriert
    werden."""
    if max_age_s is None or max_age_s <= 0:
        return False
    age_s = (now_ns - stamp_ns) / 1e9
    return age_s > max_age_s


def _quaternion_norm(q) -> float:
    return math.sqrt(q.x ** 2 + q.y ** 2 + q.z ** 2 + q.w ** 2)


def transform_direction(
    azimuth_rad: float,
    confidence: float,
    source_frame: str,
    target_frame: str,
    stamp,
    tf_lookup_fn: Callable[[str, str, object], object],
) -> TransformResult:
    """tf_lookup_fn(target_frame, source_frame, stamp) -> TransformStamped,
    MUSS bei fehlender/veralteter/zukuenftiger TF eine Ausnahme werfen
    (in der echten ROS-Anbindung: tf2_ros.LookupException/
    ConnectivityException/ExtrapolationException) -- hier bewusst
    breit als Exception abgefangen, damit dieses Modul selbst KEINE
    tf2_ros-Abhaengigkeit fuer den Ausnahmetyp braucht."""
    if not source_frame or not target_frame:
        return TransformResult(0.0, 0.0, False, "leerer_frame_id")

    try:
        transform = tf_lookup_fn(target_frame, source_frame, stamp)
    except Exception as e:
        return TransformResult(0.0, 0.0, False, f"tf_fehler_{type(e).__name__}")

    if transform is None:
        return TransformResult(0.0, 0.0, False, "keine_tf")

    q = transform.transform.rotation
    norm = _quaternion_norm(q)
    if not math.isfinite(norm) or abs(norm - 1.0) > QUATERNION_NORM_TOLERANCE:
        return TransformResult(0.0, 0.0, False, f"invalide_quaternion_norm_{norm:.3f}")

    vec = Vector3Stamped()
    vec.header.frame_id = source_frame
    vec.header.stamp = stamp
    vx, vy, vz = azimuth_to_unit_vector(azimuth_rad)
    vec.vector.x, vec.vector.y, vec.vector.z = vx, vy, vz

    try:
        transformed = tf2_geometry_msgs.do_transform_vector3(vec, transform)
    except Exception as e:
        return TransformResult(0.0, 0.0, False, f"transform_fehlgeschlagen_{type(e).__name__}")

    tx, ty, tz = transformed.vector.x, transformed.vector.y, transformed.vector.z
    if not all(math.isfinite(v) for v in (tx, ty, tz)):
        return TransformResult(0.0, 0.0, False, "nicht_endliches_ergebnis")

    new_azimuth = unit_vector_to_azimuth(tx, ty, tz)
    if not math.isfinite(new_azimuth):
        return TransformResult(0.0, 0.0, False, "nicht_endlicher_winkel")

    return TransformResult(new_azimuth, confidence, True, "ok")
