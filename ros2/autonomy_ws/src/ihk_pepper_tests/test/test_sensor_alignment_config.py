"""
Tests fuer sensor_alignment_config.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 4). Gleiches Testmuster wie test_sound_ray_transform.py --
die TF-Lookup wird injiziert (ein direkt konstruiertes TransformStamped
oder eine Ausnahme), kein echter TF-Baum noetig.
"""
import math

import pytest
from geometry_msgs.msg import TransformStamped

from ihk_pepper_navigation.sensor_alignment_config import (
    SensorAlignmentConfig,
    check_sensor_alignment,
    default_sensor_alignment_path,
    load_sensor_alignment_config,
    parse_sensor_alignment,
)


def _config(**overrides):
    defaults = dict(
        camera_frame="camera_depth_optical_frame",
        microphone_frame="respeaker_link",
        head_frame="Head",
        maximum_forward_axis_error_deg=5.0,
        require_calibrated_alignment_in_production=True,
    )
    defaults.update(overrides)
    return SensorAlignmentConfig(**defaults)


def _identity_transform():
    t = TransformStamped()
    t.transform.rotation.w = 1.0
    return t


def _yaw_transform(yaw_rad):
    t = TransformStamped()
    t.transform.rotation.z = math.sin(yaw_rad / 2.0)
    t.transform.rotation.w = math.cos(yaw_rad / 2.0)
    return t


def _lookup(transform_by_source_frame):
    def fn(target_frame, source_frame, stamp):
        return transform_by_source_frame[source_frame]
    return fn


# ---- parse/load ----

def test_valid_config_parses_without_errors():
    raw = {"sensor_alignment": {
        "camera_frame": "camera_depth_optical_frame",
        "microphone_frame": "respeaker_link",
        "head_frame": "Head",
        "maximum_forward_axis_error_deg": 5.0,
    }}
    config, errors = parse_sensor_alignment(raw)
    assert errors == []
    assert config.camera_frame == "camera_depth_optical_frame"
    assert config.require_calibrated_alignment_in_production is True  # Default


def test_missing_root_key_is_an_error():
    config, errors = parse_sensor_alignment({"not_sensor_alignment": {}})
    assert config is None
    assert len(errors) == 1


def test_missing_required_field_is_rejected():
    raw = {"sensor_alignment": {"camera_frame": "x", "microphone_frame": "y"}}
    config, errors = parse_sensor_alignment(raw)
    assert config is None
    assert len(errors) >= 1


def test_non_positive_tolerance_is_rejected():
    raw = {"sensor_alignment": {
        "camera_frame": "x", "microphone_frame": "y", "head_frame": "z",
        "maximum_forward_axis_error_deg": 0.0,
    }}
    config, errors = parse_sensor_alignment(raw)
    assert config is None
    assert any("positive Zahl" in e for e in errors)


def test_default_config_file_loads_and_validates_cleanly():
    config, errors = load_sensor_alignment_config(default_sensor_alignment_path())
    assert errors == []
    assert config.camera_frame == "camera_depth_optical_frame"
    assert config.microphone_frame == "respeaker_link"
    assert config.head_frame == "Head"
    assert config.maximum_forward_axis_error_deg == 5.0
    assert config.require_calibrated_alignment_in_production is True


def test_missing_file_reports_error_not_exception():
    config, errors = load_sensor_alignment_config("/nonexistent/path/sensor_alignment.yaml")
    assert config is None
    assert len(errors) == 1


# ---- check_sensor_alignment ----

def test_perfectly_aligned_axes_report_zero_error():
    config = _config()
    lookup = _lookup({
        "camera_depth_optical_frame": _identity_transform(),
        # Kamera-Vorwaerts (0,0,1) und Mikrofon-Vorwaerts (1,0,0) zeigen
        # in UNTERSCHIEDLICHE Achsenrichtungen im Quellframe -- fuer
        # einen exakt Null Grad-Test wird die Mikrofon-TF hier so
        # gedreht, dass ihr (1,0,0)-Vektor auf denselben (0,0,1)-
        # Zielvektor wie die Kamera abgebildet wird (90 Grad um die
        # Y-Achse). Dieser Test prueft nur, dass GLEICHE Zielvektoren zu
        # exakt 0 Grad Fehler fuehren, nicht die reale Kamera-/Mikrofon-Geometrie.
        "respeaker_link": _rotation_mapping_x_to_z(),
    })
    result = check_sensor_alignment(config, "stamp", lookup)
    assert result.valid is True
    assert result.angle_error_deg == pytest.approx(0.0, abs=1e-4)
    assert result.within_tolerance is True


def test_perpendicular_axes_exceed_default_tolerance():
    config = _config(maximum_forward_axis_error_deg=5.0)
    lookup = _lookup({
        "camera_depth_optical_frame": _identity_transform(),
        "respeaker_link": _identity_transform(),
    })
    # Kamera-Vorwaerts (0,0,1) vs. Mikrofon-Vorwaerts (1,0,0), beide
    # unveraendert (Identitaets-TF) -- 90 Grad Winkel zwischen den Achsen.
    result = check_sensor_alignment(config, "stamp", lookup)
    assert result.valid is True
    assert result.angle_error_deg == pytest.approx(90.0, abs=1e-4)
    assert result.within_tolerance is False
    assert result.reason == "achsenfehler_ueberschritten"


def test_missing_camera_tf_is_fail_closed():
    def _raising(target_frame, source_frame, stamp):
        if source_frame == "camera_depth_optical_frame":
            raise LookupError("keine TF")
        return _identity_transform()

    result = check_sensor_alignment(_config(), "stamp", _raising)
    assert result.valid is False
    assert result.reason == "keine_tf_fuer_kamera"


def test_missing_microphone_tf_is_fail_closed():
    def _raising(target_frame, source_frame, stamp):
        if source_frame == "respeaker_link":
            raise LookupError("keine TF")
        return _identity_transform()

    result = check_sensor_alignment(_config(), "stamp", _raising)
    assert result.valid is False
    assert result.reason == "keine_tf_fuer_mikrofon"


def _rotation_mapping_x_to_z():
    # +90 Grad um die Y-Achse: (1,0,0) -> (0,0,-1)... fuer diesen Test
    # reicht eine feste, unabhaengig nachvollziehbare Rotation, die
    # beide Quellvektoren auf denselben Zielvektor abbildet (siehe
    # test_perfectly_aligned_axes_report_zero_error()). -90 Grad um Y
    # bildet (1,0,0) auf (0,0,1) ab -- identisch zum unveraenderten
    # Kamera-Vorwaertsvektor (0,0,1).
    t = TransformStamped()
    angle = -math.pi / 2
    t.transform.rotation.y = math.sin(angle / 2.0)
    t.transform.rotation.w = math.cos(angle / 2.0)
    return t
