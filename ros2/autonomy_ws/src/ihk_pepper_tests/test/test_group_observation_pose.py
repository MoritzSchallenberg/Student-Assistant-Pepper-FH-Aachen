"""
Tests fuer group_observation_pose.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 16).
"""
import math

import pytest

from ihk_pepper_navigation.group_observation_pose import compute_group_observation_pose


def _default(**overrides):
    defaults = dict(
        robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0,
        member_positions=[(3.0, 0.3), (3.0, -0.3)],
        camera_horizontal_fov_deg=87.0,
        minimum_person_distance_m=1.0,
        maximum_travel_distance_m=10.0,
    )
    defaults.update(overrides)
    return compute_group_observation_pose(**defaults)


def test_valid_pose_for_a_narrow_group_straight_ahead():
    result = _default()
    assert result.valid is True
    assert result.all_members_expected_visible is True
    assert result.reason == "ok"


def test_never_drives_onto_the_group_center():
    result = _default()
    center = (3.0, 0.0)
    dist_to_center = math.hypot(result.target_x - center[0], result.target_y - center[1])
    spread_radius = 0.3
    assert dist_to_center >= spread_radius


def test_minimum_distance_applies_to_the_nearest_member_not_just_the_center():
    # Asymmetrische Gruppe: ein Mitglied deutlich naeher am Roboter als
    # das Zentrum vermuten liesse.
    result = _default(member_positions=[(2.0, 0.0), (4.0, 0.0)], minimum_person_distance_m=1.5)
    assert result.valid is True
    assert result.distance_to_nearest_person_m >= 1.5 - 1e-6


def test_too_few_members_is_rejected():
    result = _default(member_positions=[(3.0, 0.0)])
    assert result.valid is False
    assert result.reason == "zu_wenige_mitglieder"


def test_empty_members_is_rejected():
    result = _default(member_positions=[])
    assert result.valid is False


def test_group_too_wide_for_the_camera_fov_within_travel_budget():
    result = _default(
        member_positions=[(3.0, 5.0), (3.0, -5.0)],  # 10m auseinander
        camera_horizontal_fov_deg=60.0,
        maximum_travel_distance_m=2.0,  # zu wenig Spielraum, um weit genug zurueckzuweichen
    )
    assert result.valid is False
    assert result.reason == "gruppe_zu_breit"


def test_wide_group_becomes_valid_with_enough_travel_budget():
    result = _default(
        member_positions=[(3.0, 5.0), (3.0, -5.0)],
        camera_horizontal_fov_deg=60.0,
        maximum_travel_distance_m=100.0,
    )
    assert result.valid is True
    assert result.all_members_expected_visible is True


def test_target_outside_maximum_travel_distance_is_rejected():
    result = _default(
        member_positions=[(3.0, 0.1), (3.0, -0.1)],  # sehr schmal -> geringe FOV-Distanz
        minimum_person_distance_m=50.0,  # aber riesiger Sicherheitsabstand erzwingt weite Entfernung
        maximum_travel_distance_m=5.0,
    )
    assert result.valid is False
    assert result.reason in ("ziel_ausserhalb_maximaler_fahrstrecke", "gruppe_zu_breit")


def test_keepout_zone_rejects_the_target_pose():
    from ihk_pepper_navigation.zone_config import Zone
    # Eine riesige Keepout-Zone, die garantiert JEDE Zielpose einschliesst.
    zones = {"z1": Zone(id="z1", type="keepout",
                         polygon=[[-100, -100], [100, -100], [100, 100], [-100, 100]])}
    result = _default(zones=zones)
    assert result.valid is False
    assert result.reason == "zielpose_in_keepout_zone"


def test_costmap_free_fn_rejects_an_occupied_target():
    result = _default(costmap_free_fn=lambda x, y: False)
    assert result.valid is False
    assert result.reason == "zielpose_ausserhalb_karte_oder_in_hindernis"


def test_costmap_free_fn_accepts_a_free_target():
    result = _default(costmap_free_fn=lambda x, y: True)
    assert result.valid is True


def test_a_group_behind_the_robot_still_yields_a_valid_pose():
    # Bewusste Design-Entscheidung (siehe Moduldoku): diese Funktion
    # lehnt eine Zielpose NICHT allein deshalb ab, weil sie "hinter" der
    # aktuellen Blickrichtung liegt -- ein normales Nav2-Ziel dreht sich
    # zuerst und faehrt dann vorwaerts dorthin.
    result = _default(member_positions=[(-3.0, 0.3), (-3.0, -0.3)], robot_yaw_rad=0.0)
    assert result.valid is True


def test_robot_exactly_at_group_center_does_not_crash():
    result = compute_group_observation_pose(
        robot_x=3.0, robot_y=0.0, robot_yaw_rad=0.0,
        member_positions=[(3.0, 0.3), (3.0, -0.3)],
        camera_horizontal_fov_deg=87.0, minimum_person_distance_m=1.0,
        maximum_travel_distance_m=10.0,
    )
    # Kein Crash -- valid haengt vom degenerierten Rueckzugspfad ab,
    # aber die Funktion muss in jedem Fall ein Ergebnis liefern.
    assert isinstance(result.valid, bool)


def test_target_yaw_faces_the_group_center():
    result = _default()
    yaw_to_center = math.atan2(0.0 - result.target_y, 3.0 - result.target_x)
    assert result.target_yaw_rad == pytest.approx(yaw_to_center, abs=1e-6)


def test_expected_angular_span_is_within_the_configured_fov():
    result = _default(camera_horizontal_fov_deg=87.0)
    assert result.valid is True
    assert result.expected_angular_span_rad <= math.radians(87.0) + 1e-6
