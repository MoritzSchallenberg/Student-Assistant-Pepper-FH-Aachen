"""
Gesicht-/Emotion-Adapter-Vertraege (Entwicklungsauftrag 3, "Gesicht und
Emotion vorbereiten"). NUR Adapter/Mocks -- keine echte Gesichtserkennung,
keine automatische Namensidentifikation, keine produktive
Emotionserkennung in diesem Auftrag.

AffectObservation verallgemeinert mood_signal.py::MoodObservation auf
beliebige Emotionsquellen (nicht nur Peppers qicli-Stimmungs-API) --
MoodObservation bleibt fuer den bestehenden qicli-Anwendungsfall
erhalten, AffectObservation ist die Order-3-Erweiterung mit
Quellenangabe/Track-Zuordnung/Datenalter. Beide teilen dasselbe Prinzip:
is_reliable_fact()/is_usable_as_fact() liefern IMMER False.
"""
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class IdentityObservation:
    """Reiner Datencontainer -- NIE eine automatische Zuordnung. Ein
    Aufrufer (Test, spaeter ein echter Erkennungsdienst) liefert diese
    Beobachtung, entscheidet aber NICHT selbst ueber Speicherung/
    Vertrauenswuerdigkeit -- das bleibt Identity Registry + Consent
    vorbehalten (identity_registry_db.py)."""

    track_id: int
    confidence: float
    observed_at_iso: str
    confirmed_person_id: Optional[str] = None  # NUR gesetzt, wenn bereits extern bestaetigt


@dataclass
class AffectObservation:
    label: str
    confidence: float
    observed_at_iso: str
    source: str  # z.B. "pepper_mood_api", "future_vision_model"
    track_id: Optional[int] = None
    person_id: Optional[str] = None  # NUR wenn eine bestaetigte Identity-Zuordnung vorliegt

    def age_s(self, now_fn=time.time) -> float:
        observed_unix = time.mktime(time.strptime(self.observed_at_iso, "%Y-%m-%dT%H:%M:%SZ"))
        return max(0.0, now_fn() - observed_unix)

    def is_reliable_fact(self) -> bool:
        """Absichtlich IMMER False -- eine Emotionsbeobachtung gilt NIE
        als gesicherte Tatsache oder dauerhafte Eigenschaft (Auftrag-
        Vorgabe), unabhaengig von Quelle/Konfidenz."""
        return False


@dataclass
class PersonContext:
    """Erweiterter Personenkontext fuer Identitaets-/Affekt-Beobachtungen
    -- NICHT zu verwechseln mit
    ihk_pepper_llm_contracts/knowledge_planner.py::PersonContext (das
    bleibt die schlanke Pipeline-Schnittstelle, unveraendert). Diese
    Klasse ist die interne, ausfuehrlichere Sicht innerhalb von
    ihk_pepper_person_memory."""

    known: bool = False
    display_name: Optional[str] = None
    person_id: Optional[str] = None
    latest_affect: Optional[AffectObservation] = None
