"""
Tests fuer roles.py (Entwicklungsauftrag 04-B, AP7, Abschnitt 5/6).
"""
from ihk_pepper_interaction.roles import (
    PRIVILEGED_COMMAND_MIN_ROLE,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    ROLE_STUDENT,
    SAFETY_FIELDS_NEVER_VOICE_SETTABLE,
    VALID_ROLES,
    is_command_voice_forbidden,
    is_valid_role,
    min_role_for_command,
    role_at_least,
    role_rank,
)


def test_valid_roles_contains_exactly_three():
    assert VALID_ROLES == (ROLE_STUDENT, ROLE_EMPLOYEE, ROLE_ADMIN)


def test_is_valid_role():
    assert is_valid_role(ROLE_STUDENT) is True
    assert is_valid_role(ROLE_EMPLOYEE) is True
    assert is_valid_role(ROLE_ADMIN) is True
    assert is_valid_role("superadmin") is False
    assert is_valid_role("") is False


def test_role_rank_orders_student_below_employee_below_admin():
    assert role_rank(ROLE_STUDENT) < role_rank(ROLE_EMPLOYEE) < role_rank(ROLE_ADMIN)


def test_unknown_role_ranks_as_student_fail_closed():
    assert role_rank("gibberish") == role_rank(ROLE_STUDENT)


def test_role_at_least():
    assert role_at_least(ROLE_ADMIN, ROLE_EMPLOYEE) is True
    assert role_at_least(ROLE_EMPLOYEE, ROLE_EMPLOYEE) is True
    assert role_at_least(ROLE_STUDENT, ROLE_EMPLOYEE) is False


def test_follow_speaker_requires_employee():
    assert min_role_for_command("follow_speaker") == ROLE_EMPLOYEE


def test_unknown_command_has_no_minimum_role():
    assert min_role_for_command("dialogue_text") is None
    assert is_command_voice_forbidden("dialogue_text") is False


def test_change_system_mode_is_voice_forbidden_regardless_of_role():
    assert is_command_voice_forbidden("change_system_mode") is True
    assert min_role_for_command("change_system_mode") is None


def test_safety_fields_never_voice_settable_matches_the_order_exactly():
    assert SAFETY_FIELDS_NEVER_VOICE_SETTABLE == frozenset({
        "allow_motion", "allow_person_approach", "localization_valid", "obstacle_data_valid",
    })
