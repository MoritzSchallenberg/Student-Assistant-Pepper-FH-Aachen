"""
Tests fuer authorization_policy.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 8).
"""
import pytest

from ihk_pepper_interaction.authorization_policy import (
    POLICY_DISABLED,
    POLICY_ROLE_ONLY_DEVELOPMENT,
    POLICY_ROLE_PLUS_CONFIRMATION,
    AuthorizationPolicyError,
    PrivilegedCommandRequest,
    check_authorization,
    validate_policy,
)
from ihk_pepper_interaction.roles import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_STUDENT


def _full_request(**overrides):
    defaults = dict(
        known_identity=True,
        role=ROLE_EMPLOYEE,
        recognition_confidence=0.95,
        minimum_confidence=0.8,
        liveness_passed=True,
        speaking_track_id=5,
        identity_track_id=5,
        secondary_confirmation_valid=True,
        safety_state_valid=True,
        required_min_role=ROLE_EMPLOYEE,
    )
    defaults.update(overrides)
    return PrivilegedCommandRequest(**defaults)


# ---- validate_policy ----

def test_validate_policy_accepts_all_valid_values():
    validate_policy(POLICY_DISABLED, production_mode=True)
    validate_policy(POLICY_ROLE_PLUS_CONFIRMATION, production_mode=True)
    validate_policy(POLICY_ROLE_ONLY_DEVELOPMENT, production_mode=False)


def test_validate_policy_rejects_unknown_value():
    with pytest.raises(AuthorizationPolicyError):
        validate_policy("anything_goes", production_mode=False)


def test_validate_policy_forbids_role_only_development_in_production():
    with pytest.raises(AuthorizationPolicyError):
        validate_policy(POLICY_ROLE_ONLY_DEVELOPMENT, production_mode=True)


# ---- check_authorization: disabled ----

def test_disabled_policy_never_authorizes():
    authorized, reason = check_authorization(POLICY_DISABLED, _full_request())
    assert authorized is False
    assert reason == "privileged_motion_disabled"


# ---- check_authorization: role_plus_confirmation (production) ----

def test_full_request_is_authorized():
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, _full_request())
    assert authorized is True
    assert reason == ""


def test_student_is_rejected_even_with_everything_else_valid():
    req = _full_request(role=ROLE_STUDENT)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "role_insufficient"


def test_unknown_identity_is_rejected():
    req = _full_request(known_identity=False)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "identity_unknown"


def test_low_confidence_is_rejected():
    req = _full_request(recognition_confidence=0.5)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "recognition_confidence_zu_niedrig"


def test_missing_liveness_is_rejected():
    req = _full_request(liveness_passed=False)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "liveness_nicht_bestanden"


def test_mismatched_track_id_is_rejected():
    req = _full_request(speaking_track_id=5, identity_track_id=99)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "track_id_stimmt_nicht_mit_identitaet_ueberein"


def test_missing_secondary_confirmation_is_rejected():
    req = _full_request(secondary_confirmation_valid=False)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "keine_zusatzbestaetigung"


def test_invalid_safety_state_is_rejected():
    req = _full_request(safety_state_valid=False)
    authorized, reason = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is False
    assert reason == "safety_state_ungueltig"


def test_admin_role_also_satisfies_employee_requirement():
    req = _full_request(role=ROLE_ADMIN, required_min_role=ROLE_EMPLOYEE)
    authorized, _ = check_authorization(POLICY_ROLE_PLUS_CONFIRMATION, req)
    assert authorized is True


# ---- check_authorization: role_only_development ----

def test_role_only_development_skips_liveness_and_confirmation():
    req = _full_request(liveness_passed=False, secondary_confirmation_valid=False)
    authorized, reason = check_authorization(POLICY_ROLE_ONLY_DEVELOPMENT, req)
    assert authorized is True
    assert reason == ""


def test_role_only_development_still_requires_the_role():
    req = _full_request(role=ROLE_STUDENT, liveness_passed=False,
                         secondary_confirmation_valid=False)
    authorized, reason = check_authorization(POLICY_ROLE_ONLY_DEVELOPMENT, req)
    assert authorized is False
    assert reason == "role_insufficient"
