"""
Tests fuer gesture_execution_policy.py (Entwicklungsauftrag 04-B,
AP8.1: autoritative Gesten-Ausfuehrungsrichtlinie).
"""
import os

import pytest
import yaml

from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_bridge.gesture_execution_policy import (
    GestureExecutionPolicy,
    PROFILE_OFFLINE_MOCK,
    PROFILE_OFFLINE_PREVIEW,
    PROFILE_PRODUCTION,
    PROFILE_SUPERVISED_HARDWARE_TEST,
    RuntimeContext,
)


def _write_yaml(directory, name, data):
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


def _catalog(tmp_path, **gestures):
    for name, data in gestures.items():
        data.setdefault("name", name)
        _write_yaml(tmp_path, name, data)
    return GestureCatalog(str(tmp_path))


def _v1_gesture(tested_status="draft", **overrides):
    data = {
        "steps": [{"joint": "RShoulderPitch", "angle": 0.5, "duration": 1.0}],
        "tested_status": tested_status,
    }
    data.update(overrides)
    return data


def _v2_gesture(tested_status="draft", **overrides):
    data = {
        "schema_version": 2,
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 1.0, "joints": {"RShoulderPitch": 0.5}},
        ],
        "tested_status": tested_status,
    }
    data.update(overrides)
    return data


_FRESH_HARDWARE_OK = RuntimeContext(
    safety_ok=True, nav2_moving=False, mapping_active=False,
    current_interaction_state=None, pepper_reachable=True, lease_revoked=False,
)


# ---- tested_status je Profil ----

def test_draft_is_allowed_in_offline_mock(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="draft"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(), PROFILE_OFFLINE_MOCK)
    assert decision.allowed is True


def test_draft_is_allowed_in_offline_preview(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="draft"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(), PROFILE_OFFLINE_PREVIEW)
    assert decision.allowed is True


def test_draft_is_rejected_in_supervised_hardware_test(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="draft"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), _FRESH_HARDWARE_OK, PROFILE_SUPERVISED_HARDWARE_TEST)
    assert decision.allowed is False
    assert decision.reason_code == "tested_status_unzureichend"


def test_dry_run_validated_is_allowed_in_supervised_hardware_test(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="dry_run_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), _FRESH_HARDWARE_OK, PROFILE_SUPERVISED_HARDWARE_TEST)
    assert decision.allowed is True


def test_dry_run_validated_is_rejected_in_production(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="dry_run_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), _FRESH_HARDWARE_OK, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "tested_status_unzureichend"


def test_only_live_validated_is_allowed_in_production(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), _FRESH_HARDWARE_OK, PROFILE_PRODUCTION)
    assert decision.allowed is True


# ---- keine Umgehung ----

def test_system_only_gesture_does_not_bypass_tested_status(tmp_path):
    catalog = _catalog(tmp_path, sys_gesture=_v1_gesture(
        tested_status="draft", metadata={"system_only": True}))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("sys_gesture"), _FRESH_HARDWARE_OK, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "tested_status_unzureichend"


def test_unknown_execution_profile_is_rejected(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), _FRESH_HARDWARE_OK, "made_up_profile")
    assert decision.allowed is False
    assert decision.reason_code == "unbekanntes_profil"


def test_production_requirement_cannot_be_lowered_by_a_parameter_like_argument(tmp_path):
    # Es gibt keinen Parameter in authorize(), der die Mindestanforderung
    # je Profil aendert -- dieser Test belegt es strukturell: derselbe
    # Aufruf mit denselben Argumenten liefert IMMER dieselbe Ablehnung.
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="dry_run_validated"))
    for _ in range(3):
        decision = GestureExecutionPolicy().authorize(
            catalog.get("wave"), _FRESH_HARDWARE_OK, PROFILE_PRODUCTION)
        assert decision.allowed is False


# ---- max_duration_s ----

def test_max_duration_exceeded_is_rejected_even_offline(tmp_path):
    catalog = _catalog(tmp_path, slow=_v1_gesture(
        tested_status="draft",
        steps=[{"joint": "RShoulderPitch", "angle": 0.5, "duration": 5.0}],
        max_duration_s=1.0,
    ))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("slow"), RuntimeContext(), PROFILE_OFFLINE_MOCK)
    assert decision.allowed is False
    assert decision.reason_code == "max_duration_ueberschritten"


def test_max_duration_respected_passes(tmp_path):
    catalog = _catalog(tmp_path, slow=_v1_gesture(
        tested_status="draft",
        steps=[{"joint": "RShoulderPitch", "angle": 0.5, "duration": 0.5}],
        max_duration_s=1.0,
    ))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("slow"), RuntimeContext(), PROFILE_OFFLINE_MOCK)
    assert decision.allowed is True


# ---- NaN/inf speed_scale ----

def test_nan_speed_scale_is_rejected(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="draft"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(), PROFILE_OFFLINE_MOCK,
        requested_speed_scale=float("nan"))
    assert decision.allowed is False
    assert decision.reason_code == "speed_scale_ungueltig"


def test_inf_speed_scale_is_rejected(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="draft"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(), PROFILE_OFFLINE_MOCK,
        requested_speed_scale=float("inf"))
    assert decision.allowed is False
    assert decision.reason_code == "speed_scale_ungueltig"


def test_zero_or_negative_speed_scale_uses_catalog_default(tmp_path):
    catalog = _catalog(tmp_path, wave=_v2_gesture(
        tested_status="draft", speed_scale_default=0.6))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(), PROFILE_OFFLINE_MOCK, requested_speed_scale=0.0)
    assert decision.allowed is True
    assert decision.effective_speed_scale == pytest.approx(0.6)


# ---- Laufzeitkontext (nur hardwarefaehige Profile) ----

def test_missing_safety_state_blocks_hardware_profile(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(safety_ok=None), PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "safety_state_ungueltig_oder_unbekannt"


def test_safety_state_false_blocks_hardware_profile(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(safety_ok=False), PROFILE_PRODUCTION)
    assert decision.allowed is False


def test_runtime_context_is_ignored_for_offline_profiles(tmp_path):
    # offline_mock/offline_preview beruehren nie Hardware -- ein
    # ungueltiger/fehlender Laufzeitkontext darf sie nicht blockieren.
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="draft"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), RuntimeContext(safety_ok=None, pepper_reachable=None),
        PROFILE_OFFLINE_MOCK)
    assert decision.allowed is True


def test_pepper_unreachable_blocks_hardware_profile(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    ctx = RuntimeContext(safety_ok=True, pepper_reachable=False)
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "pepper_nicht_erreichbar"


def test_unknown_nav2_moving_blocks_a_stationary_gesture(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(
        tested_status="live_validated", requires_stationary=True))
    ctx = RuntimeContext(safety_ok=True, pepper_reachable=True, nav2_moving=None)
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "nav2_moving_unklar_oder_aktiv"


def test_nav2_moving_true_blocks_a_v2_gesture(tmp_path):
    catalog = _catalog(tmp_path, wave=_v2_gesture(tested_status="live_validated"))
    ctx = RuntimeContext(safety_ok=True, pepper_reachable=True, nav2_moving=True, mapping_active=False)
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "nav2_moving_unklar_oder_aktiv"


def test_a_non_stationary_v1_gesture_is_allowed_while_nav2_moves(tmp_path):
    # v1 ohne requires_stationary bleibt erlaubt (Reuse bestehender
    # gesture_catalog.py-Semantik, keine neue Regel erfunden).
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    ctx = RuntimeContext(safety_ok=True, pepper_reachable=True, nav2_moving=True, mapping_active=False)
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is True


def test_unknown_mapping_active_blocks_a_head_gesture(tmp_path):
    catalog = _catalog(tmp_path, look=_v1_gesture(
        tested_status="live_validated",
        steps=[{"joint": "HeadYaw", "angle": 0.2, "duration": 1.0}],
    ))
    ctx = RuntimeContext(safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=None)
    decision = GestureExecutionPolicy().authorize(catalog.get("look"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "mapping_unklar_oder_aktiv"


def test_disallowed_interaction_state_is_rejected(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(
        tested_status="live_validated", allowed_interaction_states=["IDLE"]))
    ctx = RuntimeContext(
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        current_interaction_state="ATTRACT")
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "interaktionszustand_unzulaessig"


def test_missing_interaction_state_is_rejected_when_gesture_restricts_it(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(
        tested_status="live_validated", allowed_interaction_states=["IDLE"]))
    ctx = RuntimeContext(
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        current_interaction_state=None)
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False


def test_revoked_lease_blocks_the_second_authorization_check(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    ctx = RuntimeContext(safety_ok=True, pepper_reachable=True, lease_revoked=True)
    decision = GestureExecutionPolicy().authorize(catalog.get("wave"), ctx, PROFILE_PRODUCTION)
    assert decision.allowed is False
    assert decision.reason_code == "lease_widerrufen"


def test_a_fully_valid_production_request_is_allowed(tmp_path):
    catalog = _catalog(tmp_path, wave=_v1_gesture(tested_status="live_validated"))
    decision = GestureExecutionPolicy().authorize(
        catalog.get("wave"), _FRESH_HARDWARE_OK, PROFILE_PRODUCTION)
    assert decision.allowed is True
    assert decision.reason_code == "erlaubt"
    assert "RIGHT_ARM" in decision.resources
