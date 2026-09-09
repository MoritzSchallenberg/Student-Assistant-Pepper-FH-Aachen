"""
Tests fuer sound_ray_transform.py (Entwicklungsauftrag 04-B, AP6.1,
Abschnitt 3.1/12/16): reine TF-Mathematik ohne echten TF-Baum -- die
Lookup selbst wird ueber tf_lookup_fn injiziert (mal ein direkt
konstruiertes TransformStamped, mal eine Ausnahme), damit die Pruefkette
(Quaternion-Validitaet, Vektor- statt Punkt-Transformation, Fail-Closed-
Pfade) ohne rclpy/tf2_ros-Laufzeit getestet werden kann.
"""
import math

import pytest
from geometry_msgs.msg import TransformStamped

from ihk_pepper_audio.sound_ray_transform import (
    azimuth_to_unit_vector,
    is_measurement_too_old,
    transform_direction,
    unit_vector_to_azimuth,
)


def _yaw_transform(yaw_rad, tx=0.0, ty=0.0, tz=0.0):
    """Reine Z-Rotation (Yaw) -- ausreichend fuer alle hier geprueften
    Faelle, echte Kopf-Neigung (Pitch/Roll) waere fuer eine HORIZONTALE
    Schallrichtung (siehe SoundDirection.msg-Doku) ohnehin nicht
    relevant."""
    t = TransformStamped()
    t.transform.translation.x = tx
    t.transform.translation.y = ty
    t.transform.translation.z = tz
    t.transform.rotation.z = math.sin(yaw_rad / 2.0)
    t.transform.rotation.w = math.cos(yaw_rad / 2.0)
    return t


def _lookup_returning(transform):
    def fn(target_frame, source_frame, stamp):
        return transform
    return fn


def _lookup_raising(exc):
    def fn(target_frame, source_frame, stamp):
        raise exc
    return fn


def test_azimuth_unit_vector_roundtrip():
    for az in (0.0, 0.3, -0.3, math.pi / 2, -math.pi / 2, 3.0, -3.0):
        x, y, z = azimuth_to_unit_vector(az)
        assert z == 0.0
        assert unit_vector_to_azimuth(x, y, z) == pytest.approx(az, abs=1e-9)


def test_identity_transform_preserves_azimuth():
    result = transform_direction(
        azimuth_rad=0.4, confidence=0.9,
        source_frame="respeaker_link", target_frame="base_link",
        stamp="stamp-irrelevant-for-identity",
        tf_lookup_fn=_lookup_returning(_yaw_transform(0.0)),
    )
    assert result.valid is True
    assert result.azimuth_rad == pytest.approx(0.4, abs=1e-6)
    assert result.confidence == 0.9
    assert result.reason == "ok"


def test_90_degree_yaw_rotation_shifts_azimuth():
    # Transform-Rotation um +90 Grad um Z -- ein im Quellframe geradeaus
    # (0.0) gemessener Schall wird im Zielframe um denselben Winkel
    # weitergedreht (do_transform_vector3 wendet die Transform-Rotation
    # direkt auf den Vektor an, keine Translation).
    result = transform_direction(
        azimuth_rad=0.0, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link",
        stamp="s",
        tf_lookup_fn=_lookup_returning(_yaw_transform(math.pi / 2)),
    )
    assert result.valid is True
    assert result.azimuth_rad == pytest.approx(math.pi / 2, abs=1e-6)


def test_wraparound_near_pi_stays_in_valid_range():
    result = transform_direction(
        azimuth_rad=3.0, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link",
        stamp="s",
        tf_lookup_fn=_lookup_returning(_yaw_transform(1.0)),
    )
    assert result.valid is True
    assert -math.pi <= result.azimuth_rad <= math.pi
    # 3.0 + 1.0 = 4.0, gewickelt auf (-pi, pi]: 4.0 - 2*pi.
    assert result.azimuth_rad == pytest.approx(4.0 - 2 * math.pi, abs=1e-6)


def test_translation_does_not_affect_a_pure_direction():
    # Eine Richtung hat keine Position -- eine (beliebig grosse)
    # Translation im TransformStamped darf das Ergebnis NICHT
    # verschieben (Unterschied zu do_transform_point).
    no_translation = transform_direction(
        azimuth_rad=0.2, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link", stamp="s",
        tf_lookup_fn=_lookup_returning(_yaw_transform(0.3, tx=0.0, ty=0.0, tz=0.0)),
    )
    with_translation = transform_direction(
        azimuth_rad=0.2, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link", stamp="s",
        tf_lookup_fn=_lookup_returning(_yaw_transform(0.3, tx=100.0, ty=-50.0, tz=3.0)),
    )
    assert no_translation.azimuth_rad == pytest.approx(with_translation.azimuth_rad, abs=1e-9)


def test_invalid_quaternion_norm_is_rejected():
    bad = _yaw_transform(0.0)
    bad.transform.rotation.x = 5.0  # Norm weit ab von 1.0
    result = transform_direction(
        azimuth_rad=0.1, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link", stamp="s",
        tf_lookup_fn=_lookup_returning(bad),
    )
    assert result.valid is False
    assert "invalide_quaternion" in result.reason


def test_missing_tf_lookup_exception_is_fail_closed():
    result = transform_direction(
        azimuth_rad=0.1, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link", stamp="s",
        tf_lookup_fn=_lookup_raising(LookupError("keine TF")),
    )
    assert result.valid is False
    assert result.reason.startswith("tf_fehler_")
    assert result.azimuth_rad == 0.0
    assert result.confidence == 0.0


def test_none_transform_is_fail_closed():
    result = transform_direction(
        azimuth_rad=0.1, confidence=0.5,
        source_frame="respeaker_link", target_frame="base_link", stamp="s",
        tf_lookup_fn=_lookup_returning(None),
    )
    assert result.valid is False
    assert result.reason == "keine_tf"


def test_empty_source_frame_is_rejected():
    result = transform_direction(
        azimuth_rad=0.1, confidence=0.5,
        source_frame="", target_frame="base_link", stamp="s",
        tf_lookup_fn=_lookup_returning(_yaw_transform(0.0)),
    )
    assert result.valid is False
    assert result.reason == "leerer_frame_id"


def test_empty_target_frame_is_rejected():
    result = transform_direction(
        azimuth_rad=0.1, confidence=0.5,
        source_frame="respeaker_link", target_frame="", stamp="s",
        tf_lookup_fn=_lookup_returning(_yaw_transform(0.0)),
    )
    assert result.valid is False
    assert result.reason == "leerer_frame_id"


def test_is_measurement_too_old_true_when_older_than_max():
    now_ns = 10_000_000_000
    old_stamp_ns = now_ns - int(5.0 * 1e9)
    assert is_measurement_too_old(old_stamp_ns, now_ns, max_age_s=2.0) is True


def test_is_measurement_too_old_false_within_max():
    now_ns = 10_000_000_000
    recent_stamp_ns = now_ns - int(0.5 * 1e9)
    assert is_measurement_too_old(recent_stamp_ns, now_ns, max_age_s=2.0) is False


@pytest.mark.parametrize("max_age_s", [None, 0.0, -1.0])
def test_is_measurement_too_old_disabled_for_non_positive_max_age(max_age_s):
    now_ns = 10_000_000_000
    ancient_stamp_ns = 0
    assert is_measurement_too_old(ancient_stamp_ns, now_ns, max_age_s=max_age_s) is False
