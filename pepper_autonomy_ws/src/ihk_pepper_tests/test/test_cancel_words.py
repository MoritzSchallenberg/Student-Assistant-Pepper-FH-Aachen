from ihk_pepper_audio.cancel_words import detect_command, is_hard_stop


def test_detect_stop():
    assert detect_command("Stopp bitte!") == "stop"


def test_detect_case_and_umlaut_insensitive():
    assert detect_command("Bitte sei LEISE jetzt") == "quiet"


def test_detect_none_when_no_match():
    assert detect_command("Erzaehl mir mehr ueber die Ausbildung") is None


def test_first_match_wins_on_multiple_words():
    # "abbrechen" kommt vor "lauter" im Text
    assert detect_command("abbrechen und dann lauter machen") == "cancel"


def test_is_hard_stop():
    assert is_hard_stop("stop") is True
    assert is_hard_stop("cancel") is True
    assert is_hard_stop("repeat") is False
    assert is_hard_stop("volume_up") is False
