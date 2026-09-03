"""
Vertrag fuer eine spaetere Identity Registry (Entwicklungsauftrag 1,
Abschnitt 9). Nur Datenmodell + Regelvalidierung -- KEINE echte
Gesichtsdatenbank, KEINE Implementierung eines Speichers in diesem
Auftrag. Siehe docs/PERSON_MEMORY_DESIGN.md.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ConsentStatus(str, Enum):
    NOT_ASKED = "not_asked"
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"


@dataclass
class IdentityRecord:
    """Freigegebene, strukturierte Daten zu EINER wiedererkannten Person.
    person_id ist eine interne, stabile ID -- NIEMALS eine rohe
    ByteTrack-track_id (die gilt nur pro Sitzung/Sichtbarkeit, siehe
    ihk_pepper_interfaces/msg/PersonTrack.msg)."""

    person_id: str
    display_name: Optional[str] = None
    consent_status: str = ConsentStatus.NOT_ASKED.value
    last_seen_iso: Optional[str] = None
    retention_deadline_iso: Optional[str] = None
    confidence: float = 0.0  # Wiedererkennungs-Konfidenz der letzten Zuordnung


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
