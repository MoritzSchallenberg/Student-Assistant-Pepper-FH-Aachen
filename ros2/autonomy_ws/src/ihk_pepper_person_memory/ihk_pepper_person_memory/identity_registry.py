"""
Vertrag fuer eine spaetere Identity Registry (Entwicklungsauftrag 1,
Abschnitt 9). Nur Datenmodell + Regelvalidierung -- KEINE echte
Gesichtsdatenbank, KEINE Implementierung eines Speichers in diesem
Auftrag. Siehe docs/PERSON_MEMORY_DESIGN.md.

Entwicklungsauftrag 04-B, AP7, Abschnitt 6: um eine Rolle erweitert.
Rollen werden NIEMALS hier oder in identity_registry_db.py zugewiesen --
das macht ausschliesslich peoplectl (siehe docs/PERSON_ROLES_AND_AUTHORIZATION.md),
ein lokales Verwaltungswerkzeug ausserhalb jedes ROS2-Service/LLM-Zugriffs.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ihk_pepper_interaction.roles import ROLE_STUDENT, VALID_ROLES


class ConsentStatus(str, Enum):
    NOT_ASKED = "not_asked"
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"


def effective_role(role: str, role_valid_until_ts: Optional[float], now: float) -> str:
    """Reine Funktion -- fail-closed auf ROLE_STUDENT bei ungueltiger
    Rolle ODER abgelaufener role_valid_until_ts (Auftrag Abschnitt 6:
    "abgelaufene Rolle faellt auf STUDENT zurueck"). Wird von
    identity_registry_db.py::get_effective_role() UND von peoplectl
    genutzt, damit beide dieselbe Ablaufregel anwenden."""
    if role not in VALID_ROLES:
        return ROLE_STUDENT
    if role_valid_until_ts is not None and now > role_valid_until_ts:
        return ROLE_STUDENT
    return role


@dataclass
class IdentityRecord:
    """Freigegebene, strukturierte Daten zu EINER wiedererkannten Person.
    person_id ist eine interne, stabile ID -- NIEMALS eine rohe
    ByteTrack-track_id (die gilt nur pro Sitzung/Sichtbarkeit, siehe
    ihk_pepper_interfaces/msg/PersonTrack.msg).

    role/role_assigned_at_iso/role_assigned_by/role_valid_until_iso sind
    die ROH gespeicherten Werte (fuer peoplectl show/Audit) -- NICHT die
    nach Ablauf angewendete effektive Rolle, siehe effective_role()
    dafuer."""

    person_id: str
    display_name: Optional[str] = None
    consent_status: str = ConsentStatus.NOT_ASKED.value
    last_seen_iso: Optional[str] = None
    retention_deadline_iso: Optional[str] = None
    confidence: float = 0.0  # Wiedererkennungs-Konfidenz der letzten Zuordnung
    role: str = ROLE_STUDENT
    role_assigned_at_iso: Optional[str] = None
    role_assigned_by: Optional[str] = None
    role_valid_until_iso: Optional[str] = None


@dataclass
class IdentityLookupResult:
    """Antwort eines (spaeteren) Identity-Service auf 'wer ist das?'.
    known=False ist der SICHERE Default -- wird niemals durch ein LLM
    oder allein aus einer aktuellen track_id gesetzt."""

    known: bool = False
    record: Optional[IdentityRecord] = None
    confidence: float = 0.0
    as_of_iso: Optional[str] = None  # Aktualitaet der Aussage


def is_storage_allowed(record: IdentityRecord) -> bool:
    """Personenbezogene Speicherung nur mit dokumentierter Freigabe."""
    return record.consent_status == ConsentStatus.GRANTED.value


def effective_session_key(record: Optional[IdentityRecord], fallback_session_id: str) -> str:
    """Bei fehlender/widerrufener Freigabe bleibt NUR eine fluechtige
    Session-ID uebrig -- niemals die dauerhafte person_id."""
    if record is not None and is_storage_allowed(record):
        return record.person_id
    return fallback_session_id
