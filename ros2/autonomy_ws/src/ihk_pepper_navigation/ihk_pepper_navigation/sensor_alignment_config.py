"""
Gemeinsame Blickrichtung von Kamera und Mikrofon (Entwicklungsauftrag
04-B, AP7, Abschnitt 4). Kamera und ReSpeaker sind gemeinsam auf Peppers
Kopf montiert (siehe pepper_robot_state.launch.py/
respeaker_static_tf.launch.py/realsense_static_tf.launch.py,
Entwicklungsauftrag 04-B, AP6.1) -- es wird KEINE zweite, unabhaengig
geregelte Mikrofonorientierung erfunden. Dieses Modul prueft nur, ob die
beiden tatsaechlich montierten Vorwaerts-Achsen (Kamera: `+Z` optisch,
ReSpeaker: `+X`) zueinander passen -- Achsenvergleich, KEIN Ersatz fuer
die TF-Kette selbst.

Reine Logik + YAML-Laden, KEINE ROS-Node-Abhaengigkeit (gleiches Prinzip
wie zone_config.py/extrinsics_plausibility.py) -- die TF-Lookup selbst
wird injiziert (tf_lookup_fn(target_frame, source_frame, stamp) ->
TransformStamped, dieselbe Signatur wie
ihk_pepper_audio/sound_ray_transform.py::transform_direction()),
gebunden von sensor_alignment_node.py an einen echten tf2_ros.Buffer.

WARUM VEKTOR- statt Punkt-Transformation: eine Vorwaertsrichtung ist
keine Position -- do_transform_vector3 (reine Rotation, keine
Translation) ist hier korrekt, genau wie bei der Schallrichtungs-
Transformation in AP6.1 (sound_ray_transform.py), NICHT wie bei einer
echten Personenposition (audio_focus_node.py::
transform_person_position_to_azimuth, dort IST Translation korrekt)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Callable, List, Tuple

import tf2_geometry_msgs  # noqa: F401 -- registriert do_transform_vector3 fuer Vector3Stamped
import yaml
from geometry_msgs.msg import Vector3Stamped


def default_sensor_alignment_path() -> str:
    """Gleiches Fallback-Muster wie zone_config.py's
    _default_zones_dir()."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(
            get_package_share_directory("ihk_pepper_navigation"), "config", "sensor_alignment.yaml")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config",
            "sensor_alignment.yaml")

REQUIRED_FIELDS = ("camera_frame", "microphone_frame", "head_frame",
                    "maximum_forward_axis_error_deg")


class SensorAlignmentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SensorAlignmentConfig:
    camera_frame: str
    microphone_frame: str
    head_frame: str
    maximum_forward_axis_error_deg: float
    require_calibrated_alignment_in_production: bool = True
    # Auftrag Abschnitt 4: "camera_depth_optical_frame: Vorwaertsvektor
    # (0, 0, 1)" / "respeaker_link: Vorwaertsvektor (1, 0, 0)" -- als
    # Konfigurationswerte statt hart kodiert, falls eine andere
    # Kamera-/Mikrofon-Konvention je verwendet wird.
    camera_forward_vector: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    microphone_forward_vector: Tuple[float, float, float] = (1.0, 0.0, 0.0)


@dataclass(frozen=True)
class AlignmentCheckResult:
    angle_error_deg: float
    within_tolerance: bool
    valid: bool
    reason: str = ""


def _validate_entry(entry: dict) -> List[str]:
    errors = []
    for f in REQUIRED_FIELDS:
        if f not in entry or entry[f] in (None, ""):
            errors.append(f"Pflichtfeld '{f}' fehlt oder ist leer")
    for f in ("camera_frame", "microphone_frame", "head_frame"):
        if f in entry and not isinstance(entry[f], str):
            errors.append(f"'{f}' muss ein String sein")
    if "maximum_forward_axis_error_deg" in entry:
        value = entry["maximum_forward_axis_error_deg"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append("'maximum_forward_axis_error_deg' muss eine positive Zahl sein")
    if "require_calibrated_alignment_in_production" in entry and not isinstance(
            entry["require_calibrated_alignment_in_production"], bool):
        errors.append("'require_calibrated_alignment_in_production' muss ein Boolean sein")
    return errors


def parse_sensor_alignment(raw: dict) -> Tuple[SensorAlignmentConfig, List[str]]:
    entry = raw.get("sensor_alignment") if isinstance(raw, dict) else None
    if not isinstance(entry, dict):
        return None, ["Wurzel-Schluessel 'sensor_alignment' fehlt oder ist kein Objekt"]
    errors = _validate_entry(entry)
    if errors:
        return None, errors
    return SensorAlignmentConfig(
        camera_frame=entry["camera_frame"],
        microphone_frame=entry["microphone_frame"],
        head_frame=entry["head_frame"],
        maximum_forward_axis_error_deg=float(entry["maximum_forward_axis_error_deg"]),
        require_calibrated_alignment_in_production=entry.get(
            "require_calibrated_alignment_in_production", True),
    ), []


def load_sensor_alignment_config(path: str) -> Tuple[SensorAlignmentConfig, List[str]]:
    try:
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return None, [f"Datei nicht gefunden: {path}"]
    except yaml.YAMLError as e:
        return None, [f"YAML-Fehler in {path}: {e}"]
    return parse_sensor_alignment(raw)


def check_sensor_alignment(
    config: SensorAlignmentConfig,
    stamp,
    tf_lookup_fn: Callable[[str, str, object], object],
) -> AlignmentCheckResult:
    """Transformiert beide Vorwaerts-Vektoren nach head_frame und
    vergleicht die Winkeldifferenz. Fail-closed (valid=False, NIE eine
    erfundene Ausrichtung) bei fehlender/veralteter TF oder nicht-
    endlichem Ergebnis -- dieselbe Ausnahme-Konvention wie
    sound_ray_transform.py::transform_direction()."""
    camera_vec = _transform_vector(
        config.camera_forward_vector, config.camera_frame, config.head_frame, stamp, tf_lookup_fn)
    if camera_vec is None:
        return AlignmentCheckResult(0.0, False, False, "keine_tf_fuer_kamera")

    mic_vec = _transform_vector(
        config.microphone_forward_vector, config.microphone_frame, config.head_frame, stamp,
        tf_lookup_fn)
    if mic_vec is None:
        return AlignmentCheckResult(0.0, False, False, "keine_tf_fuer_mikrofon")

    angle_deg = _angle_between_deg(camera_vec, mic_vec)
    if angle_deg is None:
        return AlignmentCheckResult(0.0, False, False, "nicht_endliches_ergebnis")

    within = angle_deg <= config.maximum_forward_axis_error_deg
    return AlignmentCheckResult(
        angle_error_deg=angle_deg, within_tolerance=within, valid=True,
        reason="" if within else "achsenfehler_ueberschritten",
    )


def _transform_vector(vector_xyz, source_frame, target_frame, stamp, tf_lookup_fn):
    if not source_frame or not target_frame:
        return None
    try:
        transform = tf_lookup_fn(target_frame, source_frame, stamp)
    except Exception:
        return None
    if transform is None:
        return None
    vec = Vector3Stamped()
    vec.header.frame_id = source_frame
    vec.header.stamp = stamp
    vec.vector.x, vec.vector.y, vec.vector.z = vector_xyz
    try:
        transformed = tf2_geometry_msgs.do_transform_vector3(vec, transform)
    except Exception:
        return None
    x, y, z = transformed.vector.x, transformed.vector.y, transformed.vector.z
    if not all(math.isfinite(v) for v in (x, y, z)):
        return None
    norm = math.sqrt(x * x + y * y + z * z)
    if norm < 1e-9:
        return None
    return (x / norm, y / norm, z / norm)


def _angle_between_deg(a, b):
    dot = sum(ai * bi for ai, bi in zip(a, b))
    dot = max(-1.0, min(1.0, dot))
    angle = math.degrees(math.acos(dot))
    if not math.isfinite(angle):
        return None
    return angle
