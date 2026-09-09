"""
Tests fuer return_to_origin_safety.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 9/12).
"""
import pytest

from ihk_pepper_navigation.return_to_origin_safety import (
    ReturnToOriginSafetyContext,
    check_return_to_origin_safety,
)


def _ctx(**overrides):
    defaults = dict(
        origin_valid=True, allow_motion=True, localization_valid=True,
        obstacle_data_valid=True, charging_cable_connected=False,
        bumper_active=False, emergency_stop=False, base_lease_valid=True,
        mapping_active=False,
    )
    defaults.update(overrides)
    return ReturnToOriginSafetyContext(**defaults)


def test_all_conditions_satisfied_is_ok():
    ok, reason = check_return_to_origin_safety(_ctx())
    assert ok is True
    assert reason == ""


@pytest.mark.parametrize("field,value,expected_reason", [
    ("origin_valid", False, "ursprung_ungueltig"),
    ("emergency_stop", True, "not_stopp_aktiv"),
    ("bumper_active", True, "bumper_ausgeloest"),
    ("charging_cable_connected", True, "ladekabel_angeschlossen"),
    ("mapping_active", True, "kartierung_aktiv"),
    ("allow_motion", False, "allow_motion_false"),
    ("localization_valid", False, "lokalisierung_ungueltig"),
    ("obstacle_data_valid", False, "hindernisdaten_veraltet"),
    ("base_lease_valid", False, "base_lease_verloren"),
])
def test_each_condition_individually_blocks_return(field, value, expected_reason):
    ok, reason = check_return_to_origin_safety(_ctx(**{field: value}))
    assert ok is False
    assert reason == expected_reason


def test_first_violated_condition_wins_deterministically():
    ok, reason = check_return_to_origin_safety(_ctx(emergency_stop=True, bumper_active=True))
    assert ok is False
    assert reason == "not_stopp_aktiv"  # steht in der Liste vor bumper_active
