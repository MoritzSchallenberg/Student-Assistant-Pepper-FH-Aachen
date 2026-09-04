"""
Stufe 3 der spaeteren Drei-LLM-Pipeline: Response Composer -- Ausgabe als
strukturierter ResponsePlan (Entwicklungsauftrag 1, Abschnitt 8). Ein
deterministischer ResponsePlanValidator (diese Datei) prueft jeden Plan,
bevor ein spaeterer ResponsePlanExecutor TTS-/PlayGesture-Actions
synchronisiert. Das LLM selbst fuehrt nichts aus -- kein ROS2-Aufruf,
kein Shell-Befehl, kein Gelenkwinkel verlaesst je diese Schicht ohne
diese Pruefung. Siehe docs/LLM_PIPELINE_DESIGN.md.
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

SCHEMA_VERSION = 1

MAX_SEGMENT_TEXT_CHARS = 400  # an ihk_pepper_dialog max_speech_chars angelehnt
MAX_SEGMENTS_PER_PLAN = 6
MIN_SEGMENT_TEXT_CHARS = 1
# Entwicklungsauftrag 3, AP9: grobe Sprechdauer-Heuristik (Zeichen/Sekunde),
# NICHT praezise -- nur ein zusaetzliches Sicherheitsnetz gegen einen
# unrealistisch langen Gesamtplan, keine echte TTS-Zeitmessung.
ESTIMATED_CHARS_PER_SECOND = 15.0
MAX_TOTAL_ESTIMATED_DURATION_S = 90.0

VALID_GESTURE_RELATIONS = ("before_segment", "with_segment_start", "after_segment")

# Grobe Heuristik, welche Formulierungen typischerweise einen Faktenanspruch
# signalisieren -- Ziel ist NICHT perfekte NLP, sondern ein zusaetzliches
# Sicherheitsnetz, das im Zweifel eher zu viel als zu wenig eine Quelle
# verlangt.
FACT_CLAIM_MARKERS = (
    "laut", "gemaess", "unsere ", "unser ", "wir bieten",
    "die ausbildung", "das programm", "der kurs", "kostet", "dauert",
)

# Grobes Sicherheitsnetz gegen versehentlich/absichtlich durchgereichte
# rohe Befehle im TTS-Text -- ersetzt KEINE Ausfuehrungs-Sandbox. Der
# eigentliche Punkt: ein ResponsePlan besteht semantisch NUR aus
# TTS-Text + Gestennamen, alles andere ist per Definition ungueltig.
FORBIDDEN_TEXT_SUBSTRINGS = (
    "ros2 ", "ssh ", "qicli ", "sudo ", "rm -rf", "$(", "`",
    "os.system", "subprocess", "import os", "setmotionpermission",
)


@dataclass
class ResponseSegment:
    text: str
    segment_id: str = ""  # Entwicklungsauftrag 3, AP9: Pflichtfeld, muss eindeutig sein
    gesture_name: Optional[str] = None
    gesture_relation: Optional[str] = None  # siehe gesture_planner.GestureRelation

    def estimated_duration_s(self) -> float:
        return len(self.text) / ESTIMATED_CHARS_PER_SECOND


@dataclass
class ResponsePlan:
    schema_version: int = SCHEMA_VERSION
    segments: list = field(default_factory=list)  # list[ResponseSegment]
    source_ids: list = field(default_factory=list)  # list[str]
    memory_summary_candidate: Optional[str] = None  # nur Vorschlag, siehe ihk_pepper_person_memory

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ResponsePlan":
        segments = [
            ResponseSegment(
                text=s.get("text", ""),
                segment_id=s.get("segment_id", ""),
                gesture_name=s.get("gesture_name"),
                gesture_relation=s.get("gesture_relation"),
            )
            for s in data.get("segments", [])
        ]
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            segments=segments,
            source_ids=list(data.get("source_ids", [])),
            memory_summary_candidate=data.get("memory_summary_candidate"),
        )


@dataclass
class PlanContext:
    """Alles, was der Validator zusaetzlich zum reinen ResponsePlan
    braucht -- wird deterministisch vom aufrufenden System befuellt,
    NIE vom LLM."""

    allowed_gesture_names: list = field(default_factory=list)
    current_interaction_state: str = "IDLE"
    # gesture_name -> erlaubte Zustaende (leer/fehlend = ueberall erlaubt)
    allowed_interaction_states_for_gestures: dict = field(default_factory=dict)
    safety_ok: bool = True
    known_source_ids: list = field(default_factory=list)  # tatsaechlich vom Retriever gefundene Quellen
    # Entwicklungsauftrag 3, AP9: zusaetzliche Laufzeit-Bedingungen, vom
    # aufrufenden System (RunDialogue-Action-Server) verantwortlich befuellt
    # -- KEINE "sicherer Default bei fehlendem Topic"-Semantik wie bei
    # ROS-Sensoreingaengen, sondern ein vollstaendig vom Aufrufer befuellter
    # Kontext (analog zu safety_ok oben). nav2_moving/mapping_active/
    # gesture_in_progress blockieren NUR Segmente MIT gesture_name (die
    # Rede selbst kann trotzdem weiterlaufen, siehe Fallback-Prinzip
    # "Fehler im Gestenplayer: Sprache fortsetzen, wenn sicher").
    nav2_moving: bool = False
    mapping_active: bool = False
    gesture_in_progress: bool = False
    pepper_reachable: bool = True
    tts_available: bool = True
    # gesture_name -> bewegt Kopfgelenke (aus GestureCatalog.affects_head())
    # -- nur diese werden bei mapping_active blockiert, nicht jede Geste.
    head_gesture_names: list = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: bool
    errors: list = field(default_factory=list)


class ResponsePlanValidator:
    """Deterministisch, kein LLM-Aufruf, keine Seiteneffekte. Prueft
    Laenge, TTS-Text, Quellen, Geste, aktuellen Zustand und Safety."""

    def validate(self, plan: ResponsePlan, context: PlanContext) -> ValidationResult:
        errors = []

        if plan.schema_version != SCHEMA_VERSION:
            errors.append(f"unbekannte schema_version {plan.schema_version}")

        if not context.safety_ok:
            errors.append("Safety meldet aktuell keinen sicheren Zustand -- Plan abgelehnt")

        if not plan.segments:
            errors.append("ResponsePlan hat keine Segmente")
        if len(plan.segments) > MAX_SEGMENTS_PER_PLAN:
            errors.append(f"zu viele Segmente ({len(plan.segments)} > {MAX_SEGMENTS_PER_PLAN})")

        if not context.tts_available:
            errors.append("TTS nicht verfuegbar -- Plan kann nicht ausgefuehrt werden")

        # Entwicklungsauftrag 3, AP9: eindeutige, nicht-leere segment_ids.
        seen_segment_ids = set()
        for i, seg in enumerate(plan.segments):
            seg_id = (seg.segment_id or "").strip()
            if not seg_id:
                errors.append(f"Segment {i}: segment_id fehlt")
            elif seg_id in seen_segment_ids:
                errors.append(f"Segment {i}: segment_id '{seg_id}' ist nicht eindeutig")
            else:
                seen_segment_ids.add(seg_id)

        total_estimated_s = sum(seg.estimated_duration_s() for seg in plan.segments)
        if total_estimated_s > MAX_TOTAL_ESTIMATED_DURATION_S:
            errors.append(
                f"geschaetzte Gesamtdauer zu lang ({total_estimated_s:.0f}s > "
                f"{MAX_TOTAL_ESTIMATED_DURATION_S:.0f}s)"
            )

        for i, seg in enumerate(plan.segments):
            text = (seg.text or "").strip()
            lowered = text.lower()

            if len(text) < MIN_SEGMENT_TEXT_CHARS:
                errors.append(f"Segment {i}: leerer Text")
            if len(text) > MAX_SEGMENT_TEXT_CHARS:
                errors.append(f"Segment {i}: Text zu lang ({len(text)} > {MAX_SEGMENT_TEXT_CHARS})")

            for forbidden in FORBIDDEN_TEXT_SUBSTRINGS:
                if forbidden in lowered:
                    errors.append(f"Segment {i}: enthaelt verbotene rohe Anweisung ('{forbidden.strip()}')")

            if seg.gesture_name is not None:
                if seg.gesture_name not in context.allowed_gesture_names:
                    errors.append(f"Segment {i}: Geste '{seg.gesture_name}' nicht in der Allowlist")
                else:
                    allowed_states = context.allowed_interaction_states_for_gestures.get(seg.gesture_name)
                    if allowed_states and context.current_interaction_state not in allowed_states:
                        errors.append(
                            f"Segment {i}: Geste '{seg.gesture_name}' im Zustand "
                            f"'{context.current_interaction_state}' nicht erlaubt"
                        )
                if seg.gesture_relation not in VALID_GESTURE_RELATIONS:
                    errors.append(f"Segment {i}: unbekannte gesture_relation '{seg.gesture_relation}'")

                # Entwicklungsauftrag 3, AP9: Geste blockieren (nicht die
                # Rede!), wenn Nav2 faehrt/Mapping laeuft/schon eine Geste
                # aktiv ist/Pepper nicht erreichbar ist.
                if context.nav2_moving:
                    errors.append(f"Segment {i}: Geste waehrend Nav2-Bewegung gesperrt")
                if context.mapping_active and seg.gesture_name in context.head_gesture_names:
                    errors.append(f"Segment {i}: Kopfgeste waehrend Mapping gesperrt")
                if context.gesture_in_progress:
                    errors.append(f"Segment {i}: bereits eine laufende Geste -- kein Doppelstart")
                if not context.pepper_reachable:
                    errors.append(f"Segment {i}: Pepper nicht erreichbar -- Geste nicht ausfuehrbar")

            if any(marker in lowered for marker in FACT_CLAIM_MARKERS) and not plan.source_ids:
                errors.append(f"Segment {i}: klingt nach Faktenanspruch, aber source_ids ist leer")

        for source_id in plan.source_ids:
            if source_id not in context.known_source_ids:
                errors.append(f"source_id '{source_id}' stammt nicht vom Retriever (moeglich erfunden)")

        return ValidationResult(valid=(len(errors) == 0), errors=errors)
