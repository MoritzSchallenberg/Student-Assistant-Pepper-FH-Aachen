"""
Sicherheitsbedingungen fuer FollowPerson (Entwicklungsauftrag 04-B, AP7,
Abschnitt 19/20). Reine Logik, KEIN ROS -- person_approach_node.py baut
FollowPersonSafetyContext aus den ihm bereits bekannten Topics/Zustaenden
und ruft check_follow_person_safety() vor JEDEM Nav2-Zielsegment auf
(nicht nur einmalig beim Start).

Verteidigung in der Tiefe: Motion Guard blockiert einen Fahrbefehl
ohnehin, wenn allow_motion/allow_person_approach falsch sind -- diese
Pruefung stoppt die FollowPerson-Logik zusaetzlich VORHER, auf der
hoeheren Ebene (gleiches Prinzip wie ApproachPerson::
_safety_ok_for_approach(), hier nur um die zusaetzlichen, FollowPerson-
spezifischen Bedingungen aus Auftrag Abschnitt 20 erweitert)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class FollowPersonSafetyContext:
    authorization_valid: bool
    allow_motion: bool
    allow_person_approach: bool
    localization_valid: bool
    obstacle_data_valid: bool
    person_depth_valid: bool
    charging_cable_connected: bool
    bumper_active: bool
    emergency_stop: bool
    base_lease_valid: bool
    target_track_fresh: bool
    target_not_in_keepout: bool
    crowd_ambiguous: bool
    battery_percent: float
    minimum_battery_percent: float


# Jeder Eintrag: (Feldname, ERWARTETER sicherer Wert, Grund-String).
# Fail-closed: die ERSTE nicht erfuellte Bedingung entscheidet den
# Ablehnungsgrund -- dieselbe Reihenfolge wie in Auftrag Abschnitt 20
# aufgelistet (Sicherheitsstatus zuerst, dann Positions-/Umgebungsdaten).
_BOOLEAN_CHECKS: List[Tuple[str, bool, str]] = [
    ("authorization_valid", True, "autorisierung_ungueltig"),
    ("emergency_stop", False, "not_stopp_aktiv"),
    ("bumper_active", False, "bumper_ausgeloest"),
    ("charging_cable_connected", False, "ladekabel_angeschlossen"),
    ("allow_motion", True, "allow_motion_false"),
    ("allow_person_approach", True, "allow_person_approach_false"),
    ("localization_valid", True, "lokalisierung_ungueltig"),
    ("obstacle_data_valid", True, "hindernisdaten_veraltet"),
    ("person_depth_valid", True, "personentiefe_ungueltig"),
    ("base_lease_valid", True, "base_lease_verloren"),
    ("target_track_fresh", True, "ziel_track_veraltet"),
    ("target_not_in_keepout", True, "ziel_in_keepout_zone"),
    ("crowd_ambiguous", False, "menschenmenge_mehrdeutig"),
]


def check_follow_person_safety(ctx: FollowPersonSafetyContext) -> Tuple[bool, str]:
    """Reine Funktion. Gibt (ok, reason) zurueck -- ok=True NUR, wenn
    ALLE Bedingungen erfuellt sind (fail-closed: ein einzelner
    fehlender Nachweis reicht fuer eine Ablehnung)."""
    for field_name, expected, reason in _BOOLEAN_CHECKS:
        if getattr(ctx, field_name) != expected:
            return False, reason
    if ctx.battery_percent >= 0.0 and ctx.battery_percent < ctx.minimum_battery_percent:
        return False, "akku_niedrig"
    return True, ""


def is_crowd_ambiguous(
    target_x_m: float,
    target_y_m: float,
    other_track_positions: List[Tuple[float, float]],
    crowd_proximity_m: float,
    allow_in_crowds: bool,
) -> bool:
    """Reine Geometrie: True, wenn OHNE allow_in_crowds mindestens eine
    ANDERE Person innerhalb crowd_proximity_m der Zielperson steht --
    zu nah beieinander stehende Personen machen die Zuordnung "wer wird
    gerade gefolgt" unsicher (Auftrag Abschnitt 19/20: "Crowd erkannt").
    allow_in_crowds=True deaktiviert diese Pruefung NICHT heimlich --
    es ist eine bewusste, im Voraus konfigurierte Freigabe."""
    if allow_in_crowds:
        return False
    for x, y in other_track_positions:
        if math.hypot(x - target_x_m, y - target_y_m) <= crowd_proximity_m:
            return True
    return False
