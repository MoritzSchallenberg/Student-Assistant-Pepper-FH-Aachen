from ihk_pepper_dialog.tts_sanitizer import (
    strip_markdown, replace_urls, table_to_sentences, shorten, prepare_for_speech,
)


def test_strip_markdown_bold_header_link():
    text = "# Titel\nDas ist **wichtig** und [ein Link](http://example.com)."
    out = strip_markdown(text)
    assert "#" not in out
    assert "**" not in out
    assert "wichtig" in out
    assert "ein Link" in out
    assert "http://" not in out  # Link-URL selbst wird entfernt, nur Text bleibt


def test_replace_urls():
    out = replace_urls("Siehe https://example.com/seite fuer mehr Infos.")
    assert "https://" not in out
    assert "ein Link auf dem Tablet" in out


def test_table_to_sentences():
    table = "| Name | Wert |\n|---|---|\n| A | 1 |\n| B | 2 |\n"
    out = table_to_sentences(table)
    assert "Name: A, Wert: 1." in out
    assert "Name: B, Wert: 2." in out


def test_shorten_truncates_at_sentence_boundary():
    text = "Erster Satz. " + ("Wort " * 200) + "Letzter Satz."
    short, truncated = shorten(text, max_chars=50)
    assert truncated is True
    assert len(short) <= 55  # etwas Toleranz fuer "..."-Suffix


def test_shorten_no_truncation_when_short_enough():
    short, truncated = shorten("Kurzer Text.", max_chars=400)
    assert truncated is False
    assert short == "Kurzer Text."


def test_prepare_for_speech_full_pipeline():
    text = "# Info\nDas ist **fett**. Siehe https://example.com fuer mehr."
    spoken, full, truncated = prepare_for_speech(text, max_chars=400)
    assert "#" not in spoken
    assert "**" not in spoken
    assert "https://" not in spoken
    assert truncated is False
