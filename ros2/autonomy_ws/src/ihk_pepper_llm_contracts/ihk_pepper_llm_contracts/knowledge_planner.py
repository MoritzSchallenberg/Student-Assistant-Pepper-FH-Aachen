"""
Stufe 1 der spaeteren Drei-LLM-Pipeline: Knowledge Planner
(Entwicklungsauftrag 1, Abschnitt 8). Reiner Vertrag -- kein LLM-Aufruf
hier, kein Retriever. Das LLM bekommt in dieser Stufe NIE direkten
Datenbank-/Vektorsuche-Zugriff, es erzeugt nur Suchanfragen und
Unsicherheiten; ein spaeterer, deterministischer Retriever fuehrt die
eigentliche Suche aus (siehe docs/LLM_PIPELINE_DESIGN.md).
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

SCHEMA_VERSION = 1


@dataclass
class ConversationTurn:
    role: str  # "user" | "assistant"
    text: str


@dataclass
class PersonContext:
    """Nur freigegebene, bereits validierte Daten -- niemals vom LLM
    selbst erfunden und niemals allein aus einer ByteTrack-ID abgeleitet.
    Kommt aus ihk_pepper_person_memory (Identity Registry), nicht aus
    dieser Pipeline-Stufe."""

    known: bool = False
    display_name: Optional[str] = None
    session_id: str = ""


@dataclass
class KnowledgePlanRequest:
    schema_version: int = SCHEMA_VERSION
    normalized_question: str = ""
    person_context: PersonContext = field(default_factory=PersonContext)
    conversation_history: list = field(default_factory=list)  # list[ConversationTurn]
    mode: str = "faq"  # z.B. "faq" | "smalltalk" | "presentation_followup"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgePlanResponse:
    """Ausgabe von LLM 1. Enthaelt AUSSCHLIESSLICH Suchanfragen/Metadaten
    -- keine fertige Antwort, kein Wissen, das nicht durch den Retriever
    bestaetigt wurde."""

    schema_version: int = SCHEMA_VERSION
    normalized_intent: str = ""  # z.B. "information_request" (Entwicklungsauftrag 3, AP3)
    search_queries: list = field(default_factory=list)  # list[str]
    required_data_kinds: list = field(default_factory=list)  # z.B. ["faq"]
    use_person_memory: bool = False  # Entwicklungsauftrag 3: darf NUR eine Anfrage sein,
                                      # der eigentliche Zugriff bleibt dem Retriever + Consent-Pruefung vorbehalten
    uncertainties: list = field(default_factory=list)  # vom LLM benannte Unsicherheiten
    assumes_known_identity: bool = False  # MUSS False sein, siehe validate()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgePlanResponse":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            normalized_intent=str(data.get("normalized_intent", "")),
            search_queries=list(data.get("search_queries", [])),
            required_data_kinds=list(data.get("required_data_kinds", [])),
            use_person_memory=bool(data.get("use_person_memory", False)),
            uncertainties=list(data.get("uncertainties", [])),
            assumes_known_identity=bool(data.get("assumes_known_identity", False)),
        )

    def validate(self) -> list:
        """Reine Formatvalidierung -- diese Stufe fuehrt nichts aus, das
        eigentliche Sicherheitsnetz sitzt in ResponsePlanValidator.
        Gibt eine Liste von Fehlermeldungen zurueck, leer = gueltig."""
        errors = []
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"unbekannte schema_version {self.schema_version}")
        if self.assumes_known_identity:
            errors.append(
                "LLM 1 darf keine Personenidentitaet annehmen/erfinden "
                "(assumes_known_identity muss False sein)"
            )
        if not self.search_queries and not self.required_data_kinds:
            errors.append("weder search_queries noch required_data_kinds gesetzt")
        return errors
