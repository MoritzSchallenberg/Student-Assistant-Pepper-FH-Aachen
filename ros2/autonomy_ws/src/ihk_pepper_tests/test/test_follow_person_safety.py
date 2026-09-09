"""
Tests fuer follow_person_safety.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 19/20).
"""
import pytest

from ihk_pepper_navigation.follow_person_safety import (
    FollowPersonSafetyContext,
    check_follow_person_safety,
    is_crowd_ambiguous,
)


def _ctx(**overrides):
    defaults = dict(
        authorization_valid=True, allow_motion=True, allow_person_approach=True,
        localization_valid=True, obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, bumper_active=False, emergency_stop=False,
        base_lease_valid=True, target_track_fresh=True, target_not_in_keepout=True,
        crowd_ambiguous=False, battery_percent=80.0, minimum_battery_percent=20.0,
    )
    defaults.update(overrides)
    return FollowPersonSafetyContext(**defaults)


def test_all_conditions_satisfied_is_ok():
    ok, reason = check_follow_person_safety(_ctx())
    assert ok is True
    assert reason == ""


@pytest.mark.parametrize("field,value,expected_reason", [
    ("authorization_valid", False, "autorisierung_ungueltig"),
    ("emergency_stop", True, "not_stopp_aktiv"),
    ("bumper_active", True, "bumper_ausgeloest"),
    ("charging_cable_connected", True, "ladekabel_angeschlossen"),
    ("allow_motion", False, "allow_motion_false"),
    ("allow_person_approach", False, "allow_person_approach_false"),
    ("localization_valid", False, "lokalisierung_ungueltig"),
    ("obstacle_data_valid", False, "hindernisdaten_veraltet"),
    ("person_depth_valid", False, "personentiefe_ungueltig"),
    ("base_lease_valid", False, "base_lease_verloren"),
    ("target_track_fresh", False, "ziel_track_veraltet"),
    ("target_not_in_keepout", False, "ziel_in_keepout_zone"),
    ("crowd_ambiguous", True, "menschenmenge_mehrdeutig"),
])
def test_each_condition_individually_blocks_follow(field, value, expected_reason):
    ok, reason = check_follow_person_safety(_ctx(**{field: value}))
    assert ok is False
    assert reason == expected_reason


def test_low_battery_blocks_follow():
    ok, reason = check_follow_person_safety(_ctx(battery_percent=10.0, minimum_battery_percent=20.0))
    assert ok is False
    assert reason == "akku_niedrig"


def test_unknown_battery_reading_does_not_block():
    # -1.0 = "kein aktueller Messwert" (siehe bridge_node.py-Konvention) --
    # KEIN erfundenes "niedrig", einfach uebersprungen.
    ok, reason = check_follow_person_safety(_ctx(battery_percent=-1.0, minimum_battery_percent=20.0))
    assert ok is True


def test_first_violated_condition_wins_deterministically():
    ok, reason = check_follow_person_safety(_ctx(emergency_stop=True, bumper_active=True))
    assert ok is False
    assert reason == "not_stopp_aktiv"  # steht in der Liste vor bumper_active


# ---- is_crowd_ambiguous ----

def test_no_other_tracks_is_never_ambiguous():
    assert is_crowd_ambiguous(1.0, 0.0, [], crowd_proximity_m=1.0, allow_in_crowds=False) is False


def test_a_nearby_other_person_is_ambiguous():
    assert is_crowd_ambiguous(
        1.0, 0.0, [(1.2, 0.0)], crowd_proximity_m=0.5, allow_in_crowds=False) is True


def test_a_far_other_person_is_not_ambiguous():
    assert is_crowd_ambiguous(
        1.0, 0.0, [(10.0, 0.0)], crowd_proximity_m=0.5, allow_in_crowds=False) is False


def test_allow_in_crowds_disables_the_check():
    assert is_crowd_ambiguous(
        1.0, 0.0, [(1.2, 0.0)], crowd_proximity_m=0.5, allow_in_crowds=True) is False
