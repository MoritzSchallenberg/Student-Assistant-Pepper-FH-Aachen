"""
Tests fuer codeword_config.py (Entwicklungsauftrag 04-B, AP7, Abschnitt
12/13).
"""
import pytest

from ihk_pepper_interaction.codeword_config import (
    default_codewords_path,
    detect_codeword,
    load_codewords,
    parse_codewords,
)


def _raw(entries):
    return {"codewords": entries}


def test_valid_config_parses_without_errors():
    raw = _raw([
        {"phrase": "eisenbahn", "command": "interrupt_and_look", "required_role": "student"},
        {"phrase": "pepper komm mal mit", "command": "follow_speaker", "required_role": "employee"},
    ])
    rules, errors = parse_codewords(raw)
    assert errors == []
    assert len(rules) == 2


def test_missing_root_key_is_an_error():
    rules, errors = parse_codewords({"not_codewords": []})
    assert rules == {}
    assert len(errors) == 1


def test_missing_phrase_is_rejected():
    rules, errors = parse_codewords(_raw([{"command": "interrupt_and_look"}]))
    assert rules == {}
    assert len(errors) == 1


def test_empty_phrase_is_rejected():
    rules, errors = parse_codewords(_raw([{"phrase": "", "command": "interrupt_and_look"}]))
    assert rules == {}
    assert len(errors) == 1


def test_unknown_command_is_rejected():
    rules, errors = parse_codewords(_raw([{"phrase": "eisenbahn", "command": "launch_missiles"}]))
    assert rules == {}
    assert "unbekannter command" in errors[0]


def test_unknown_required_role_is_rejected():
    rules, errors = parse_codewords(_raw([
        {"phrase": "eisenbahn", "command": "interrupt_and_look", "required_role": "superadmin"},
    ]))
    assert rules == {}
    assert "unbekannte required_role" in errors[0]


def test_duplicate_phrase_is_rejected():
    rules, errors = parse_codewords(_raw([
        {"phrase": "Eisenbahn", "command": "interrupt_and_look"},
        {"phrase": "eisenbahn", "command": "interrupt_and_look"},  # gleich nach Normalisierung
    ]))
    assert len(rules) == 1
    assert any("doppelte Phrase" in e for e in errors)


def test_non_boolean_flag_is_rejected():
    rules, errors = parse_codewords(_raw([
        {"phrase": "eisenbahn", "command": "interrupt_and_look", "stop_dialogue": "yes"},
    ]))
    assert rules == {}
    assert "muss ein Boolean sein" in errors[0]


def test_default_config_file_loads_and_validates_cleanly():
    # Die tatsaechlich ausgelieferte codewords.yaml muss sich selbst
    # gegen ihre eigenen Regeln validieren -- kein Beispiel/Platzhalter,
    # der die eigene Validierung nicht besteht.
    rules, errors = load_codewords(default_codewords_path())
    assert errors == []
    assert "eisenbahn" in rules
    assert rules["eisenbahn"].command == "interrupt_and_look"
    assert rules["eisenbahn"].required_role == "student"
    assert "pepper komm mal mit" in rules
    assert rules["pepper komm mal mit"].command == "follow_speaker"
    assert rules["pepper komm mal mit"].required_role == "employee"
    assert rules["pepper komm mal mit"].requires_secondary_confirmation is True


def test_missing_file_reports_error_not_exception():
    rules, errors = load_codewords("/nonexistent/path/codewords.yaml")
    assert rules == {}
    assert len(errors) == 1


# ---- detect_codeword ----

def test_detect_codeword_finds_a_known_phrase():
    rules, _ = parse_codewords(_raw([{"phrase": "eisenbahn", "command": "interrupt_and_look"}]))
    rule = detect_codeword("also Eisenbahn bitte sofort", rules)
    assert rule is not None
    assert rule.command == "interrupt_and_look"


def test_detect_codeword_returns_none_for_unrelated_text():
    rules, _ = parse_codewords(_raw([{"phrase": "eisenbahn", "command": "interrupt_and_look"}]))
    assert detect_codeword("wie ist das Wetter heute", rules) is None


def test_detect_codeword_picks_the_earliest_match_when_multiple_present():
    rules, _ = parse_codewords(_raw([
        {"phrase": "eisenbahn", "command": "interrupt_and_look"},
        {"phrase": "pepper komm mal mit", "command": "follow_speaker"},
    ]))
    rule = detect_codeword("pepper komm mal mit zur eisenbahn", rules)
    assert rule.command == "follow_speaker"
