"""
Stufe 2 der spaeteren Drei-LLM-Pipeline: Gesture Planner
(Entwicklungsauftrag 1, Abschnitt 8). Referenziert AUSSCHLIESSLICH
Gestennamen aus einer zur Laufzeit uebergebenen Allowlist -- niemals
Gelenke, Winkel, Geschwindigkeiten oder ROS-Befehle. validate() ist das
Sicherheitsnetz dafuer, siehe docs/LLM_PIPELINE_DESIGN.md.
"""
from dataclasses import asdict, dataclass, field
from enum import Enum

SCHEMA_VERSION = 1


class GestureRelation(str, Enum):
    BEFORE_SEGMENT = "before_segment"
    WITH_SEGMENT_START = "with_segment_start"
    AFTER_SEGMENT = "after_segment"


@dataclass
class GestureOption:
    """EIN Kandidat aus der Gesten-Vektordatenbank, so wie LLM 2 ihn zu
    sehen bekommt (Entwicklungsauftrag 04-B, AP5A, Abschnitt 5) -- NUR
    beschreibende Felder. Bewusst KEIN Feld fuer Gelenke/Winkel/
    Zeitachsen/Trajektorien/ROS2-/qicli-Befehle; diese Klasse dient
    ausschliesslich der Prompt-Befuellung, nicht der Ausfuehrung."""

    name: str
    description: str = ""
    duration_s: float = 0.0
    score: float = 0.0
    allowed_interaction_states: list = field(default_factory=list)


@dataclass
class GesturePlanRequest:
    schema_version: int = SCHEMA_VERSION
    answer_brief: str = ""  # Kurzfassung aus Stufe 1 + gefundene Quellen
    robot_situation: str = ""  # z.B. "IDLE", "CONVERSATION_READY"
    allowed_gesture_names: list = field(default_factory=list)  # Allowlist von aussen (deterministische Validierungsgrundlage)
    # Entwicklungsauftrag 04-B, AP5A: strukturierte Kandidaten aus der
    # Gesten-Vektordatenbank (list[GestureOption]) -- gibt LLM 2 genug
    # Kontext (Beschreibung/Dauer/Aehnlichkeit/erlaubte Zustaende), um
    # sinnvoll auszuwaehlen, OHNE dass allowed_gesture_names als
    # deterministische Pruefgrundlage (siehe validate()) ersetzt wird.
    gesture_options: list = field(default_factory=list)  # list[GestureOption]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GestureSuggestion:
    gesture_name: str
    relation: str  # GestureRelation-Wert


@dataclass
class GesturePlanResponse:
    schema_version: int = SCHEMA_VERSION
    suggestions: list = field(default_factory=list)  # list[GestureSuggestion]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GesturePlanResponse":
        suggestions = [
            GestureSuggestion(
                gesture_name=s.get("gesture_name", ""),
                relation=s.get("relation", ""),
            )
            for s in data.get("suggestions", [])
        ]
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            suggestions=suggestions,
        )

    def validate(self, allowed_gesture_names) -> list:
        """Gibt eine Liste von Fehlermeldungen zurueck, leer = gueltig."""
        errors = []
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"unbekannte schema_version {self.schema_version}")
        allowed = set(allowed_gesture_names)
        valid_relations = {r.value for r in GestureRelation}
        for s in self.suggestions:
            if s.gesture_name not in allowed:
                errors.append(f"Geste '{s.gesture_name}' ist nicht in der Allowlist")
            if s.relation not in valid_relations:
                errors.append(f"unbekannte gesture_relation '{s.relation}'")
        return errors
