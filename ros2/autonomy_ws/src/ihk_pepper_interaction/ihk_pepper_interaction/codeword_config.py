"""
Konfigurierbare Codewoerter (Entwicklungsauftrag 04-B, AP7, Abschnitt
12/13). Eigenes, einfaches YAML-Format -- gleiches Prinzip/Validierungs-
stil wie ihk_pepper_navigation/zone_config.py: reine Ladefunktion +
Dataclass, KEINE ROS-Abhaengigkeit, gesondert unit-getestet.

Sicherheitsanforderungen aus dem Auftrag, alle hier durchgesetzt:
    - keine doppelten Phrasen
    - keine leeren Befehle
    - Rollen nur aus der Allowlist (roles.py::VALID_ROLES)
    - unbekannte Actions abgelehnt (VALID_COMMANDS-Allowlist unten --
      die YAML-Datei kann NIEMALS einen neuen, beliebigen Befehl
      erfinden, der nicht bereits im Code als bekannte Aktion existiert)
    - kein beliebiger ROS2-Befehl/Shellcode/LLM-Prompt in YAML moeglich,
      weil `command` ausschliesslich einer von VALID_COMMANDS sein darf
      und alle anderen Felder Booleans/Strings aus einer festen Menge
      sind -- die YAML-Datei kann strukturell keinen Code ausfuehren.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml

from .roles import VALID_ROLES


def default_codewords_path() -> str:
    """Gleiches Fallback-Muster wie zone_config.py's
    _default_zones_dir() -- installierter Share-Pfad, sonst der
    Quellordner (fuer direkte Tests ohne colcon-Install)."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(
            get_package_share_directory("ihk_pepper_interaction"), "config", "codewords.yaml")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "codewords.yaml")

# Entwicklungsauftrag 04-B, AP7, Abschnitt 10/13: die einzigen Befehle,
# die ein Codewort ausloesen darf -- jede unbekannte Aktion in der YAML
# wird abgelehnt (siehe validate()). "dialogue_text" gehoert NICHT hier
# rein (das ist der Nicht-Befehl-Fall, kein Codewort).
VALID_COMMANDS = frozenset({
    "interrupt_and_look",  # "Eisenbahn" -- Auftrag Abschnitt 12
    "follow_speaker",      # "Pepper, komm mal mit" -- Auftrag Abschnitt 11
    "stop",
    "cancel",
})

REQUIRED_FIELDS = ("phrase", "command")


class CodewordValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CodewordRule:
    phrase: str
    command: str
    required_role: str = "student"
    stop_dialogue: bool = False
    stop_navigation: bool = False
    orient_to_source: bool = False
    requires_secondary_confirmation: bool = False


def _normalize(text: str) -> str:
    """Dieselbe einfache Normalisierung wie
    ihk_pepper_audio/cancel_words.py::_normalize() -- bewusst hier
    dupliziert statt importiert (ihk_pepper_interaction haengt nicht von
    ihk_pepper_audio ab, keine neue Paketabhaengigkeit fuer eine
    Ein-Zeilen-Funktion, gleiches Vorbild wie embedding_backend.py
    zwischen ihk_pepper_dialog/ihk_pepper_person_memory)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^a-z0-9äöüß\s]", "", text)
    return text.strip()


def _validate_entry(entry: dict, index: int) -> Optional[str]:
    for f in REQUIRED_FIELDS:
        if f not in entry or entry[f] in (None, ""):
            return f"Eintrag {index}: Pflichtfeld '{f}' fehlt oder ist leer"
    if not isinstance(entry["phrase"], str) or not entry["phrase"].strip():
        return f"Eintrag {index}: 'phrase' muss ein nicht-leerer String sein"
    if entry["command"] not in VALID_COMMANDS:
        return (
            f"Eintrag {index}: unbekannter command '{entry['command']}' -- "
            f"erlaubt: {', '.join(sorted(VALID_COMMANDS))}"
        )
    required_role = entry.get("required_role", "student")
    if required_role not in VALID_ROLES:
        return (
            f"Eintrag {index}: unbekannte required_role '{required_role}' -- "
            f"erlaubt: {', '.join(VALID_ROLES)}"
        )
    for bool_field in ("stop_dialogue", "stop_navigation", "orient_to_source",
                       "requires_secondary_confirmation"):
        if bool_field in entry and not isinstance(entry[bool_field], bool):
            return f"Eintrag {index}: '{bool_field}' muss ein Boolean sein"
    return None


def parse_codewords(raw: dict) -> Tuple[Dict[str, CodewordRule], List[str]]:
    """Reine Funktion (kein Dateizugriff) -- nimmt das bereits per
    yaml.safe_load() geparste dict entgegen, gibt (rules_by_normalized_phrase,
    errors) zurueck. Rules sind nach der NORMALISIERTEN Phrase indiziert
    (gleiche Normalisierung wie bei der Laufzeit-Erkennung), damit
    Duplikate zuverlaessig erkannt werden (z.B. "Eisenbahn" vs.
    "eisenbahn" waeren sonst zwei verschiedene Schluessel)."""
    entries = raw.get("codewords") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return {}, ["Wurzel-Schluessel 'codewords' fehlt oder ist keine Liste"]

    rules: Dict[str, CodewordRule] = {}
    errors: List[str] = []
    seen_phrases = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"Eintrag {i}: kein Objekt/Dictionary")
            continue
        err = _validate_entry(entry, i)
        if err:
            errors.append(err)
            continue
        normalized_phrase = _normalize(entry["phrase"])
        if not normalized_phrase:
            errors.append(f"Eintrag {i}: 'phrase' ist nach Normalisierung leer")
            continue
        if normalized_phrase in seen_phrases:
            errors.append(f"Eintrag {i}: doppelte Phrase '{entry['phrase']}'")
            continue
        seen_phrases.add(normalized_phrase)
        rules[normalized_phrase] = CodewordRule(
            phrase=entry["phrase"],
            command=entry["command"],
            required_role=entry.get("required_role", "student"),
            stop_dialogue=entry.get("stop_dialogue", False),
            stop_navigation=entry.get("stop_navigation", False),
            orient_to_source=entry.get("orient_to_source", False),
            requires_secondary_confirmation=entry.get("requires_secondary_confirmation", False),
        )
    return rules, errors


def load_codewords(path: str) -> Tuple[Dict[str, CodewordRule], List[str]]:
    try:
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}, [f"Datei nicht gefunden: {path}"]
    except yaml.YAMLError as e:
        return {}, [f"YAML-Fehler in {path}: {e}"]
    return parse_codewords(raw)


def detect_codeword(text: str, rules: Dict[str, CodewordRule]) -> Optional[CodewordRule]:
    """Substring-Suche auf dem normalisierten Text -- gleiches Prinzip
    wie cancel_words.py::detect_command() (Robustheit gegen Whisper-
    Tippfehler wichtiger als Praezision). Bei mehreren Treffern gewinnt
    der zuerst im Text vorkommende. Gibt None zurueck, wenn kein
    Codewort erkannt wurde -- NIE eine erfundene Regel."""
    normalized = _normalize(text)
    best = None
    best_pos = len(normalized) + 1
    for phrase, rule in rules.items():
        pos = normalized.find(phrase)
        if pos != -1 and pos < best_pos:
            best = rule
            best_pos = pos
    return best
