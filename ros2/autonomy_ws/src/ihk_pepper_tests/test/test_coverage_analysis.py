import math

import pytest

from ihk_pepper_navigation.coverage_analysis import (
    analyze_ground_coverage,
    is_coverage_sufficient_for_live_motion,
)


def test_camera_looking_straight_down_has_zero_blind_zone():
    result = analyze_ground_coverage(
        mount_height_m=1.2, vertical_fov_deg=58.0, downward_tilt_deg=90.0,
        horizontal_fov_deg=87.0,
    )
    assert result.blind_zone_radius_m == pytest.approx(0.0, abs=1e-6)


def test_camera_looking_forward_has_large_blind_zone():
    # Pepper-typische Kopfhoehe ~1.2m, RealSense D435 Referenzwerte
    # (Intel-Datenblatt: horizontal ~87 deg, vertikal ~58 deg), Kamera
    # leicht nach unten geneigt (10 deg), sonst horizontal.
    result = analyze_ground_coverage(
        mount_height_m=1.2, vertical_fov_deg=58.0, downward_tilt_deg=10.0,
        horizontal_fov_deg=87.0,
    )
    # unterer Sichtfeldrand bei 10+29=39 deg -> blind zone = 1.2/tan(39deg)
    expected = 1.2 / math.tan(math.radians(39.0))
    assert result.blind_zone_radius_m == pytest.approx(expected, rel=1e-6)
    assert result.blind_zone_radius_m > 1.0  # deutlich groesser als Peppers Fussabdruck


def test_camera_tilted_upward_never_sees_the_ground():
    result = analyze_ground_coverage(
        mount_height_m=1.2, vertical_fov_deg=10.0, downward_tilt_deg=-20.0,
        horizontal_fov_deg=87.0,
    )
    assert result.blind_zone_radius_m == math.inf


def test_single_forward_camera_never_covers_full_circle():
    result = analyze_ground_coverage(
        mount_height_m=1.2, vertical_fov_deg=58.0, downward_tilt_deg=10.0,
        horizontal_fov_deg=87.0,
    )
    assert result.covers_full_circle is False
    assert result.uncovered_horizontal_deg == pytest.approx(273.0)


def test_hypothetical_360_camera_covers_full_circle():
    result = analyze_ground_coverage(
        mount_height_m=1.2, vertical_fov_deg=58.0, downward_tilt_deg=10.0,
        horizontal_fov_deg=360.0,
    )
    assert result.covers_full_circle is True
    assert result.uncovered_horizontal_deg == 0.0


def test_coverage_insufficient_when_horizontal_gap_exists():
    # Selbst bei einem winzigen Blindfleck-Radius: ein Restwinkel ohne
    # jede Abdeckung reicht, um "nicht ausreichend" zu erzwingen (Auftrag:
    # nicht schoenreden).
    assert is_coverage_sufficient_for_live_motion(
        blind_zone_radius_m=0.01, footprint_radius_m=0.30,
        uncovered_horizontal_deg=1.0,
    ) is False


def test_coverage_insufficient_when_blind_zone_exceeds_footprint():
    assert is_coverage_sufficient_for_live_motion(
        blind_zone_radius_m=1.5, footprint_radius_m=0.30,
        uncovered_horizontal_deg=0.0,
    ) is False


def test_coverage_sufficient_only_when_both_conditions_pass():
    assert is_coverage_sufficient_for_live_motion(
        blind_zone_radius_m=0.2, footprint_radius_m=0.30,
        uncovered_horizontal_deg=0.0,
    ) is True


def test_single_realsense_on_pepper_head_is_not_sufficient_for_live_motion():
    """Der eigentliche Abdeckungsnachweis aus Auftrag 2, Abschnitt 9:
    mit realistischen Pepper-/RealSense-Referenzwerten reicht EINE
    kopfmontierte Kamera nicht aus -- Livebewegung muss zusaetzlich
    abgesichert bleiben (Collision-Monitor-BumperStop, Motion Guard)."""
    coverage = analyze_ground_coverage(
        mount_height_m=1.2, vertical_fov_deg=58.0, downward_tilt_deg=10.0,
        horizontal_fov_deg=87.0,
    )
    sufficient = is_coverage_sufficient_for_live_motion(
        blind_zone_radius_m=coverage.blind_zone_radius_m,
        footprint_radius_m=0.30,
        uncovered_horizontal_deg=coverage.uncovered_horizontal_deg,
    )
    assert sufficient is False
