"""
Vertrag fuer ein spaeteres Vector Memory (freigegebene
Gespraechszusammenfassungen + Embeddings, Entwicklungsauftrag 1,
Abschnitt 9). Nur Datenmodell + Schreibregeln -- keine echte Vektor-DB
in diesem Auftrag. Siehe docs/PERSON_MEMORY_DESIGN.md.
"""
from dataclasses import dataclass, field
from typing import Optional

from .identity_registry import IdentityRecord, is_storage_allowed

# Grobe Plausibilitaetsgrenze: embedding_ref MUSS eine kurze Referenz
# (ID/Pfad in eine getrennt zugriffsgeschuetzte Ablage) sein, niemals ein
# Inline-Datenblob (Rohbild/rohes Embedding).
MAX_EMBEDDING_REF_CHARS = 512


@dataclass
class MemoryEntry:
    """EIN freigegebener Gespraechszusammenfassungs-Eintrag. Enthaelt
    NIEMALS Rohbilder oder Gesichts-Embeddings als Klartext-/Chat-Feld --
    embedding_ref verweist nur auf eine separate Ablage, nie auf die
    Rohdaten selbst."""

    person_id: str
    source: str  # z.B. "dialog_session", "presentation_qa"
    timestamp_iso: str
    topics: list = field(default_factory=list)
    text_summary: str = ""
    embedding_ref: Optional[str] = None
    valid_until_iso: Optional[str] = None


def validate_memory_write(entry: MemoryEntry, identity: Optional[IdentityRecord]) -> list:
    """Gibt eine Liste von Fehlermeldungen zurueck, leer = Schreiben
    erlaubt. Reine Regelpruefung, kein echter Speicherzugriff."""
    errors = []

    if identity is None or identity.person_id != entry.person_id:
        errors.append("kein passender Identity-Record fuer diesen Eintrag")
    elif not is_storage_allowed(identity):
        errors.append(
            f"keine dokumentierte Einwilligung fuer person_id={entry.person_id} "
            f"(consent_status={identity.consent_status})"
        )

    if not entry.text_summary and not entry.topics:
        errors.append("weder text_summary noch topics gesetzt")

    if entry.embedding_ref and len(entry.embedding_ref) > MAX_EMBEDDING_REF_CHARS:
        errors.append("embedding_ref wirkt zu lang fuer eine reine Referenz (Rohdaten?)")

    if not entry.valid_until_iso:
        errors.append("valid_until_iso fehlt -- Eintraege brauchen eine Gueltigkeits-/Loeschregel")

    return errors
