"""
Tests fuer ihk_pepper_bridge/tts_guard.py (Entwicklungsauftrag 04-B,
AP5B, Abschnitt 9.2).
"""
import pytest

from ihk_pepper_bridge.tts_guard import TtsTextRejected, validate_tts_text


def test_normal_text_passes_unchanged():
    assert validate_tts_text("Die Ausbildung dauert drei Jahre.") == "Die Ausbildung dauert drei Jahre."


def test_empty_text_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text("")


def test_whitespace_only_text_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text("   ")


def test_none_text_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text(None)


def test_too_long_text_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text("a" * 500)


def test_text_at_exact_max_length_passes():
    text = "a" * 400
    assert validate_tts_text(text) == text


def test_naoqi_pause_tag_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text(r"Hallo \pau=5000\ Welt")


def test_naoqi_animation_start_tag_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text("Hallo ^start(animations/Stand/Gestures/Explain_1) Welt")


def test_ssml_like_speed_tag_rejected():
    with pytest.raises(TtsTextRejected):
        validate_tts_text("Hallo <speed=200> schnell")


@pytest.mark.parametrize("dangerous", [
    "Hallo `rm -rf /`", "Hallo $(echo pwned)", "Hallo; rm -rf /",
    "Hallo | cat /etc/passwd", "Hallo & background",
])
def test_shell_metacharacters_rejected(dangerous):
    with pytest.raises(TtsTextRejected):
        validate_tts_text(dangerous)


def test_text_is_trimmed():
    assert validate_tts_text("  Hallo  ") == "Hallo"
