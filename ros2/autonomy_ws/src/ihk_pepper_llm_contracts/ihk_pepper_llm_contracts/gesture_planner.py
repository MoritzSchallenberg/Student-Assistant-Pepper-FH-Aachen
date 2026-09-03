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
class GesturePlanRequest:
    schema_version: int = SCHEMA_VERSION
    answer_brief: str = ""  # Kurzfassung aus Stufe 1 + gefundene Quellen
    robot_situation: str = ""  # z.B. "IDLE", "CONVERSATION_READY"
    allowed_gesture_names: list = field(default_factory=list)  # Allowlist von aussen

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
