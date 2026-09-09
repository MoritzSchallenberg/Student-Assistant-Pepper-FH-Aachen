"""
Text-Sicherheitsgrenze fuer Sprachausgabe AN DER BRIDGE
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 9.2). Reine Funktion, kein
ROS -- geprueft wird jeder Text, der die Bridge erreicht, unabhaengig
davon, ob der Dialogserver ihn bereits durch
ihk_pepper_dialog/tts_sanitizer.py::prepare_for_speech() geschickt hat.
"Nicht ausschliesslich darauf vertrauen, dass der Dialogserver den Text
bereits bereinigt hat" (Auftrag-Vorgabe) -- Verteidigung in der Tiefe.

Die eigentliche Ausfuehrungssicherheit gegen Shell-Injection kommt aus
shlex.quote() in qicli.py::say()/say_text_only() -- diese Pruefung hier
ist ein ZUSAETZLICHES inhaltliches Sicherheitsnetz (z.B. gegen NAOqi-
Animationsanweisungen, die syntaktisch gueltiger Text waeren, aber
unerwuenschtes Verhalten ausloesen wuerden)."""
import re

MAX_TTS_TEXT_CHARS = 400

# NAOqi-ALAnimatedSpeech-/ALTextToSpeech-Steuer-Tags (z.B. "\pau=500\",
# "\rspd=80\", "^start(animation)", "<...>"-artige SSML-Fragmente) --
# sollen nie unbeabsichtigt in einem von einem LLM/Retriever erzeugten
# Antworttext landen und als Steuerbefehl statt als Sprache interpretiert
# werden.
_NAOQI_TAG_RE = re.compile(r"\\[a-zA-Z]+=[^\\]*\\|\^(start|stop|wait)\(|<\s*(speed|vct|vol|silence)\b", re.IGNORECASE)

# Shell-Metazeichen, die in einem Sprachtext strukturell nichts verloren
# haben -- kommt NICHT anstelle von shlex.quote() (das bleibt die
# eigentliche Ausfuehrungssicherheit), sondern zusaetzlich: ein Text mit
# diesen Zeichen deutet eher auf einen fehlgeleiteten/erfundenen Befehl
# als auf echte gesprochene Sprache hin.
_SHELL_METACHAR_RE = re.compile(r"[`$;|&<>]")


class TtsTextRejected(ValueError):
    """Text an der Bridge-Grenze abgelehnt -- nie stillschweigend
    bereinigt und trotzdem gesendet."""


def validate_tts_text(text, max_chars: int = MAX_TTS_TEXT_CHARS) -> str:
    """Wirft TtsTextRejected bei leerem/zu langem/verdaechtigem Text.
    Gibt sonst den getrimmten Text zurueck."""
    if text is None or not str(text).strip():
        raise TtsTextRejected("leerer Text abgelehnt")
    text = str(text)
    if len(text) > max_chars:
        raise TtsTextRejected(f"Text zu lang ({len(text)} > {max_chars} Zeichen)")
    if _NAOQI_TAG_RE.search(text):
        raise TtsTextRejected("enthaelt eine NAOqi-Animationsanweisung/ein Steuer-Tag")
    if _SHELL_METACHAR_RE.search(text):
        raise TtsTextRejected("enthaelt ein Shell-Metazeichen")
    return text.strip()
