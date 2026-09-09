"""
Tests fuer command_authorization_decision.py (Entwicklungsauftrag 04-B,
AP7, Abschnitt 8/10).
"""
from ihk_pepper_interaction.authorization_policy import (
    POLICY_DISABLED,
    POLICY_ROLE_ONLY_DEVELOPMENT,
    POLICY_ROLE_PLUS_CONFIRMATION,
)
from ihk_pepper_interaction.command_authorization_decision import decide_command_authorization
from ihk_pepper_interaction.roles import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_STUDENT


def _decide(command="follow_speaker", policy=POLICY_ROLE_PLUS_CONFIRMATION, known_identity=True,
            role=ROLE_EMPLOYEE, recognition_confidence=0.95, minimum_confidence=0.8,
            liveness_passed=True, speaking_track_id=5, identity_track_id=5,
            secondary_confirmation_valid=True, safety_state_valid=True):
    return decide_command_authorization(
        command=command, policy=policy, known_identity=known_identity, role=role,
        recognition_confidence=recognition_confidence, minimum_confidence=minimum_confidence,
        liveness_passed=liveness_passed, speaking_track_id=speaking_track_id,
        identity_track_id=identity_track_id,
        secondary_confirmation_valid=secondary_confirmation_valid,
        safety_state_valid=safety_state_valid,
    )


# ---- rollenfreie Befehle ----

def test_stop_is_never_required_regardless_of_identity():
    decision = _decide(command="stop", known_identity=False)
    assert decision.authorization_status == "not_required"


def test_interrupt_and_look_is_never_required_for_a_student():
    decision = _decide(command="interrupt_and_look", known_identity=True, role=ROLE_STUDENT)
    assert decision.authorization_status == "not_required"


def test_interrupt_and_look_role_defaults_to_student_for_unknown_identity():
    decision = _decide(command="interrupt_and_look", known_identity=False)
    assert decision.role == ROLE_STUDENT


# ---- follow_speaker: voll autorisiert ----

def test_follow_speaker_fully_authorized_is_granted():
    decision = _decide(command="follow_speaker")
    assert decision.authorization_status == "granted"


def test_follow_speaker_denied_for_student():
    decision = _decide(command="follow_speaker", role=ROLE_STUDENT)
    assert decision.authorization_status == "denied"
    assert decision.reason == "role_insufficient"


def test_follow_speaker_denied_without_known_identity():
    decision = _decide(command="follow_speaker", known_identity=False)
    assert decision.authorization_status == "denied"
    assert decision.reason == "identity_unknown"


def test_follow_speaker_denied_without_secondary_confirmation():
    decision = _decide(command="follow_speaker", secondary_confirmation_valid=False)
    assert decision.authorization_status == "denied"
    assert decision.reason == "keine_zusatzbestaetigung"


def test_follow_speaker_denied_without_liveness():
    decision = _decide(command="follow_speaker", liveness_passed=False)
    assert decision.authorization_status == "denied"
    assert decision.reason == "liveness_nicht_bestanden"


def test_follow_speaker_admin_also_satisfies_the_requirement():
    decision = _decide(command="follow_speaker", role=ROLE_ADMIN)
    assert decision.authorization_status == "granted"


def test_follow_speaker_disabled_policy_always_denies():
    decision = _decide(command="follow_speaker", policy=POLICY_DISABLED)
    assert decision.authorization_status == "denied"
    assert decision.reason == "privileged_motion_disabled"


def test_follow_speaker_development_policy_skips_liveness_and_confirmation():
    decision = _decide(
        command="follow_speaker", policy=POLICY_ROLE_ONLY_DEVELOPMENT,
        liveness_passed=False, secondary_confirmation_valid=False,
    )
    assert decision.authorization_status == "granted"


# ---- Befehle, die NIE per Sprache erlaubt sind ----

def test_change_system_mode_is_always_denied_regardless_of_role_or_policy():
    decision = _decide(command="change_system_mode", role=ROLE_ADMIN,
                        policy=POLICY_ROLE_ONLY_DEVELOPMENT)
    assert decision.authorization_status == "denied"
    assert decision.reason == "befehl_nie_per_sprache_erlaubt"
