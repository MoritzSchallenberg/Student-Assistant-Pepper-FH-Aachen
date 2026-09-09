"""
Personenrollen (Entwicklungsauftrag 04-B, AP7, Abschnitt 5/6). Reine
Konstanten + Hilfsfunktionen, KEINE ROS-Abhaengigkeit -- von
identity_registry_db.py (Speicherung), peoplectl (Verwaltung),
audiovisual_association_node.py/command_router_node.py (Laufzeit-
Entscheidung) gleichermassen genutzt.

Sicherer Default (Auftrag Abschnitt 5): "unbekannte Person",
"nicht eingewilligte Person", "mehrdeutige Erkennung" und
"abgelaufene Erkennung" fuehren IMMER zu ROLE_STUDENT -- nie zu einer
erratenen hoeheren Rolle. Rollen werden NIE hier zugewiesen (das macht
ausschliesslich peoplectl, siehe identity_registry_db.py) -- dieses
Modul beantwortet nur "was darf Rolle X" und "welche Werte sind
gueltig".
"""
from __future__ import annotations

ROLE_STUDENT = "student"
ROLE_EMPLOYEE = "employee"
ROLE_ADMIN = "admin"

VALID_ROLES = (ROLE_STUDENT, ROLE_EMPLOYEE, ROLE_ADMIN)

# Rangfolge fuer "mindestens Rolle X"-Pruefungen (hoeherer Wert = mehr
# Rechte) -- KEINE automatische Vererbung von Berechtigungen ausserhalb
# der unten in PRIVILEGED_COMMAND_MIN_ROLE explizit gelisteten Befehle.
_ROLE_RANK = {ROLE_STUDENT: 0, ROLE_EMPLOYEE: 1, ROLE_ADMIN: 2}

# Entwicklungsauftrag 04-B, AP7, Abschnitt 5: Rechtetabelle je
# priviligiertem Befehl -- normales Gespraech/Praesentation/"Stopp"/
# "Eisenbahn" brauchen KEINE Rolle (nicht in dieser Tabelle, siehe
# command_router_node.py: fehlt ein Befehl hier, gilt er als frei
# verfuegbar, sofern er ueberhaupt privilegiert sein KOENNTE -- die
# Tabelle listet nur tatsaechlich rollen-gebundene Befehle).
PRIVILEGED_COMMAND_MIN_ROLE = {
    "follow_speaker": ROLE_EMPLOYEE,
    "guide_person": ROLE_EMPLOYEE,  # Auftrag Abschnitt 5: "konfigurierbar" -- Default employee
    "change_system_mode": None,  # NIE per Sprache, siehe Abschnitt 5 Tabelle unten
}

# Diese Werte darf KEIN Sprachbefehl je setzen -- unabhaengig von Rolle,
# unabhaengig von jeder zukuenftigen Erweiterung dieses Moduls (Auftrag
# Abschnitt 5: "Diese Werte bleiben ausschliesslich beim Supervisor").
SAFETY_FIELDS_NEVER_VOICE_SETTABLE = frozenset({
    "allow_motion",
    "allow_person_approach",
    "localization_valid",
    "obstacle_data_valid",
})


def is_valid_role(role: str) -> bool:
    return role in VALID_ROLES


def role_rank(role: str) -> int:
    """Unbekannte/ungueltige Rollen ranken wie ROLE_STUDENT (0) --
    fail-closed, nie hoeher als tatsaechlich bekannt."""
    return _ROLE_RANK.get(role, 0)


def role_at_least(role: str, minimum_role: str) -> bool:
    return role_rank(role) >= role_rank(minimum_role)


def min_role_for_command(command: str):
    """None, wenn der Befehl fuer JEDE Rolle (auch Student) verfuegbar
    ist, oder wenn er NIEMALS per Sprache erlaubt ist -- der Aufrufer
    muss diese beiden Faelle getrennt behandeln (siehe
    command_router_node.py: change_system_mode ist explizit gesperrt,
    nicht einfach "immer erlaubt"). Ein Befehl, der nicht in der Tabelle
    steht, gilt als rollenfrei (kein privilegierter Befehl)."""
    return PRIVILEGED_COMMAND_MIN_ROLE.get(command)


def is_command_voice_forbidden(command: str) -> bool:
    """True fuer Befehle, die PRIVILEGED_COMMAND_MIN_ROLE explizit auf
    None gesetzt hat -- NIE per Sprache erlaubt, unabhaengig von Rolle
    (Auftrag Abschnitt 5: Systemmodus/Sicherheitsfreigaben)."""
    return command in PRIVILEGED_COMMAND_MIN_ROLE and PRIVILEGED_COMMAND_MIN_ROLE[command] is None
