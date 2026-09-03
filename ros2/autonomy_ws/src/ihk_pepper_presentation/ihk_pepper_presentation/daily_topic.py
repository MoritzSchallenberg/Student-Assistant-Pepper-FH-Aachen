"""
Datenmodell + Validierung fuer Tagesthemen (Arbeitspaket 18). Fehlerhafte
Themen-Dateien werden uebersprungen (mit Fehlermeldung), nicht das ganze
System blockieren -- gleiches Muster wie ihk_pepper_bridge/gesture_catalog.py.
"""
import glob
import os
from dataclasses import dataclass, field
from datetime import date, datetime

import yaml

REQUIRED_FIELDS = ("id", "title", "intro_text", "short_description")


class TopicValidationError(ValueError):
    pass


def _as_date(value) -> date:
    """valid_from/valid_to koennen aus YAML entweder als str ('2026-01-01')
    ODER -- wenn im YAML UNQUOTED geschrieben, z.B. 'valid_from: 2026-01-01'
    -- bereits als datetime.date/datetime.datetime ankommen, weil PyYAMLs
    safe_load ISO-Datumsformate automatisch erkennt und selbst umwandelt.
    Gefunden per Unit-Test (siehe ihk_pepper_tests/test_daily_topic.py) --
    ohne diese Normalisierung crasht is_valid_today() bei unquoted Daten
    mit 'TypeError: fromisoformat: argument must be str'."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value).date()


@dataclass
class DailyTopic:
    id: str
    title: str
    intro_text: str
    short_description: str
    valid_from: str = None
    valid_to: str = None
    priority: int = 0
    detailed_text: str = ""
    video_path: str = ""
    thumbnail_path: str = ""
    subtitle_path: str = ""
    anythingllm_workspace: str = ""
    faq_topic: str = ""
    quiz_questions: list = field(default_factory=list)
    closing_question: str = ""
    fallback_no_video: str = ""
    gesture_names: list = field(default_factory=list)
    summary_text: str = ""
    source_path: str = ""

    def is_valid_today(self, today: date = None) -> bool:
        today = today or date.today()
        if self.valid_from:
            if today < _as_date(self.valid_from):
                return False
        if self.valid_to:
            if today > _as_date(self.valid_to):
                return False
        return True

    def has_video(self) -> bool:
        return bool(self.video_path) and os.path.isfile(self.video_path)


def load_topic(path: str) -> DailyTopic:
    with open(path) as f:
        data = yaml.safe_load(f)
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise TopicValidationError(f"{path}: fehlende Pflichtfelder: {missing}")
    topic = DailyTopic(
        id=data["id"], title=data["title"], intro_text=data["intro_text"],
        short_description=data["short_description"],
        valid_from=data.get("valid_from"), valid_to=data.get("valid_to"),
        priority=data.get("priority", 0), detailed_text=data.get("detailed_text", ""),
        video_path=data.get("video_path", ""), thumbnail_path=data.get("thumbnail_path", ""),
        subtitle_path=data.get("subtitle_path", ""),
        anythingllm_workspace=data.get("anythingllm_workspace", ""),
        faq_topic=data.get("faq_topic", ""), quiz_questions=data.get("quiz_questions", []),
        closing_question=data.get("closing_question", ""),
        fallback_no_video=data.get("fallback_no_video", topic_fallback_text(data.get("title", ""))),
        gesture_names=data.get("gesture_names", []),
        summary_text=data.get("summary_text", data.get("short_description", "")),
        source_path=path,
    )
    return topic


def topic_fallback_text(title: str) -> str:
    return f"Leider kann ich das Video zu {title or 'diesem Thema'} gerade nicht zeigen."


def load_all_topics(directory: str):
    """Gibt (topics_dict, errors_list) zurueck -- laedt alles Ladbare,
    sammelt Fehler statt abzubrechen (Anforderung Abschnitt 18)."""
    topics = {}
    errors = []
    for path in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        try:
            topic = load_topic(path)
            topics[topic.id] = topic
        except Exception as e:
            errors.append(f"{path}: {e}")
    return topics, errors


def select_active_topic(topics: dict, today: date = None):
    """Waehlt das gueltige Thema mit hoechster Prioritaet fuer heute."""
    candidates = [t for t in topics.values() if t.is_valid_today(today)]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t.priority)
