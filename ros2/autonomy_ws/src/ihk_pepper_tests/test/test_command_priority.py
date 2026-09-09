"""
Tests fuer command_priority.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 10).
"""
from ihk_pepper_interaction.command_priority import (
    COMMAND_PRIORITY_CODEWORD_INTERRUPT,
    COMMAND_PRIORITY_DIALOGUE_TEXT,
    COMMAND_PRIORITY_PRIVILEGED_MOTION,
    COMMAND_PRIORITY_STOP_CANCEL,
    priority_for_command,
)


def test_stop_and_cancel_share_the_same_priority():
    assert priority_for_command("stop") == priority_for_command("cancel") == COMMAND_PRIORITY_STOP_CANCEL


def test_codeword_interrupt_priority():
    assert priority_for_command("interrupt_and_look") == COMMAND_PRIORITY_CODEWORD_INTERRUPT


def test_follow_speaker_is_privileged_motion():
    assert priority_for_command("follow_speaker") == COMMAND_PRIORITY_PRIVILEGED_MOTION


def test_unknown_command_defaults_to_dialogue_text_never_higher():
    assert priority_for_command("dialogue_text") == COMMAND_PRIORITY_DIALOGUE_TEXT
    assert priority_for_command("something_made_up") == COMMAND_PRIORITY_DIALOGUE_TEXT


def test_priority_ordering_matches_the_order_exactly():
    # Niedrigerer Wert = hoehere Prioritaet (Auftrag Abschnitt 10:
    # Stopp/Abbrechen vor Codewort vor privilegiertem Befehl vor Dialogtext).
    assert COMMAND_PRIORITY_STOP_CANCEL < COMMAND_PRIORITY_CODEWORD_INTERRUPT
    assert COMMAND_PRIORITY_CODEWORD_INTERRUPT < COMMAND_PRIORITY_PRIVILEGED_MOTION
    assert COMMAND_PRIORITY_PRIVILEGED_MOTION < COMMAND_PRIORITY_DIALOGUE_TEXT
