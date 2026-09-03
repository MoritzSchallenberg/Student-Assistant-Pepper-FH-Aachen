"""
Lokale Abbruchwort-Erkennung -- laeuft direkt auf dem Transkript, OHNE
LLM-Umweg (schnelle Reaktion, siehe Auftrag Abschnitt 10).

Bewusst simpel (Substring-Matching auf normalisiertem Text) statt NLU --
fuer Sicherheits-/Steuerbefehle ist Robustheit gegen Whisper-Tippfehler
wichtiger als Praezision, false positives sind hier weniger kritisch als
ein verpasstes "Stopp".
"""
import re
import unicodedata

CANCEL_WORDS = {
    "stopp": "stop",
    "stop": "stop",
    "abbrechen": "cancel",
    "sei leise": "quiet",
    "wiederholen": "repeat",
    "lauter": "volume_up",
    "leiser": "volume_down",
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^a-z0-9äöüß\s]", "", text)
    return text.strip()


def detect_command(text: str):
    """Gibt den erkannten Befehl (stop/cancel/quiet/repeat/volume_up/
    volume_down) zurueck, oder None. Bei mehreren Treffern gewinnt der
    zuerst im Text vorkommende."""
    normalized = _normalize(text)
    best = None
    best_pos = len(normalized) + 1
    for phrase, command in CANCEL_WORDS.items():
        pos = normalized.find(phrase)
        if pos != -1 and pos < best_pos:
            best = command
            best_pos = pos
    return best


def is_hard_stop(command: str) -> bool:
    """'Stopp'/'Abbrechen' muessen OHNE LLM laufende Sprachausgabe,
    Praesentation oder Navigation abbrechen koennen (Anforderung)."""
    return command in ("stop", "cancel")
