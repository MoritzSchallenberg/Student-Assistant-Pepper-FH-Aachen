"""Text-Aufbereitung vor der TTS-Ausgabe (Arbeitspaket 14)."""
import re

MAX_SPOKEN_CHARS_DEFAULT = 400

_MD_BOLD_ITALIC = re.compile(r"[*_]{1,3}([^*_]+)[*_]{1,3}")
_MD_HEADER = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_URL = re.compile(r"https?://\S+")
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def strip_markdown(text: str) -> str:
    text = _CODE_FENCE.sub("", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)  # "[Text](url)" -> "Text"
    text = _MD_BOLD_ITALIC.sub(lambda m: m.group(1), text)
    text = _INLINE_CODE.sub(lambda m: m.group(1), text)
    return text


def replace_urls(text: str, placeholder: str = "ein Link auf dem Tablet") -> str:
    """URLs nicht vollstaendig vorlesen -- durch Platzhalter ersetzen."""
    return _URL.sub(placeholder, text)


def table_to_sentences(text: str) -> str:
    """Sehr einfache Markdown-Tabellen-Erkennung -> Aufzaehlungssaetze.
    Kein vollstaendiger Markdown-Parser, deckt den ueblichen Pipe-Table-Fall ab."""
    lines = text.split("\n")
    out_lines = []
    table_block = []

    def flush_table():
        if not table_block:
            return
        rows = [
            [c.strip() for c in row.strip("|").split("|")]
            for row in table_block
            if not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", row)  # Trennzeile ueberspringen
        ]
        if len(rows) >= 2:
            header = rows[0]
            for row in rows[1:]:
                parts = [f"{h}: {v}" for h, v in zip(header, row)]
                out_lines.append(", ".join(parts) + ".")
        table_block.clear()

    for line in lines:
        if "|" in line and line.strip().startswith("|"):
            table_block.append(line)
        else:
            flush_table()
            out_lines.append(line)
    flush_table()
    return "\n".join(out_lines)


def remove_control_chars(text: str) -> str:
    return _CONTROL_CHARS.sub("", text)


def shorten(text: str, max_chars: int = MAX_SPOKEN_CHARS_DEFAULT):
    """Gibt (kurzfassung, wurde_gekuerzt) zurueck. Kuerzt an Satzgrenzen,
    wenn moeglich, statt hart mitten im Wort abzuschneiden."""
    if len(text) <= max_chars:
        return text, False
    truncated = text[:max_chars]
    last_period = truncated.rfind(". ")
    if last_period > max_chars * 0.5:
        truncated = truncated[:last_period + 1]
    else:
        truncated = truncated.rstrip() + "..."
    return truncated, True


def prepare_for_speech(text: str, max_chars: int = MAX_SPOKEN_CHARS_DEFAULT):
    """Volle Pipeline. Gibt (sprechtext, volltext_fuers_tablet, wurde_gekuerzt) zurueck."""
    full = strip_markdown(text)
    full = table_to_sentences(full)
    full = replace_urls(full)
    full = remove_control_chars(full)
    full = re.sub(r"\n{2,}", "\n", full).strip()

    spoken, truncated = shorten(full, max_chars)
    return spoken, full, truncated
