"""
Sicherheitsbedingungen fuer ReturnToOrigin (Entwicklungsauftrag 04-B,
AP7, Abschnitt 9/12). Reine Logik, KEIN ROS -- gleiches Muster wie
follow_person_safety.py, hier ohne die personenspezifischen Felder
(kein Zieltrack, keine Menschenmenge waehrend der Rueckkehr relevant),
dafuer mit mapping_active (Auftrag: waehrend einer laufenden Kartierung
ist die gespeicherte Ursprungspose nicht vertrauenswuerdig)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ReturnToOriginSafetyContext:
    origin_valid: bool
    allow_motion: bool
    localization_valid: bool
    obstacle_data_valid: bool
    charging_cable_connected: bool
    bumper_active: bool
    emergency_stop: bool
    base_lease_valid: bool
    mapping_active: bool


# Fail-closed: die ERSTE nicht erfuellte Bedingung entscheidet den
# Ablehnungsgrund (gleiche Reihenfolge wie follow_person_safety.py:
# Sicherheitsstatus zuerst, dann Positions-/Umgebungsdaten).
_BOOLEAN_CHECKS: List[Tuple[str, bool, str]] = [
    ("origin_valid", True, "ursprung_ungueltig"),
    ("emergency_stop", False, "not_stopp_aktiv"),
    ("bumper_active", False, "bumper_ausgeloest"),
    ("charging_cable_connected", False, "ladekabel_angeschlossen"),
    ("mapping_active", False, "kartierung_aktiv"),
    ("allow_motion", True, "allow_motion_false"),
    ("localization_valid", True, "lokalisierung_ungueltig"),
    ("obstacle_data_valid", True, "hindernisdaten_veraltet"),
    ("base_lease_valid", True, "base_lease_verloren"),
]


def check_return_to_origin_safety(ctx: ReturnToOriginSafetyContext) -> Tuple[bool, str]:
    """Reine Funktion. Gibt (ok, reason) zurueck -- ok=True NUR, wenn ALLE
    Bedingungen erfuellt sind (fail-closed: ein einzelner fehlender
    Nachweis reicht fuer eine Ablehnung -- niemals eine Schaetzfahrt bei
    Unsicherheit, siehe Auftrag Abschnitt 12 'safe failure behavior')."""
    for field_name, expected, reason in _BOOLEAN_CHECKS:
        if getattr(ctx, field_name) != expected:
            return False, reason
    return True, ""
