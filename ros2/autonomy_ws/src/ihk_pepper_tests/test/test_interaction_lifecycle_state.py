"""
Tests fuer interaction_lifecycle_state.py (Entwicklungsauftrag 04-B,
AP7, Abschnitt 9/23).
"""
from ihk_pepper_interaction.interaction_lifecycle_state import (
    InteractionLifecycleState,
    state_name,
)


def test_all_seventeen_states_present_with_expected_values():
    expected = {
        "IDLE": 0, "WAKEWORD_RECEIVED": 1, "TARGET_CONFIRMING": 2, "GREETING": 3,
        "APPROACHING": 4, "GROUP_POSITIONING": 5, "CONVERSATION": 6, "INTERRUPTING": 7,
        "FOLLOW_AUTHORIZATION": 8, "FOLLOWING": 9, "PERSON_LOST": 10, "GROUP_LOST": 11,
        "ENDING": 12, "RETURNING_TO_ORIGIN": 13, "SAFE_STOP": 14, "ERROR": 15,
    }
    for name, value in expected.items():
        assert InteractionLifecycleState[name] == value


def test_state_name_returns_the_enum_member_name():
    assert state_name(InteractionLifecycleState.CONVERSATION) == "CONVERSATION"
    assert state_name(InteractionLifecycleState.IDLE) == "IDLE"
