"""
Tests fuer privacy_filter.py (Ergaenzungsauftrag 04-A, Abschnitt 1.7):
deterministischer Datenschutzfilter vor jedem externen LLM-Aufruf
(KI:connect oder jeder andere externe Provider).
"""
import pytest

from ihk_pepper_llm_contracts.privacy_filter import (
    DisallowedContentError,
    RedactedAnswerContext,
    redact_for_external_llm,
    reinsert_display_name,
)
from ihk_pepper_llm_contracts.retriever import AnswerBrief, Fact


def _brief(question="Wie spaet ist es?", facts=None):
    return AnswerBrief(question=question, facts=facts or [])


# ---- Grundschema ----

def test_redacted_context_has_no_field_for_forbidden_data():
    """Strukturausschluss, nicht nur Konvention: person_id/track_id/
    session_id/Name/Gesichtsdaten/Roh-Audio duerfen als Dataclass-Feld
    gar nicht existieren."""
    field_names = set(RedactedAnswerContext.__dataclass_fields__.keys())
    forbidden = {
        "person_id", "track_id", "session_id", "display_name", "name",
        "first_name", "last_name", "face_embedding", "raw_audio",
        "conversation_history", "internal_ip", "credentials",
    }
    assert field_names.isdisjoint(forbidden)


def test_redact_drops_raw_question():
    brief = _brief(question="Mein Name ist Max Mustermann, wie spaet ist es?")
    redacted = redact_for_external_llm(brief)
    dumped = str(redacted.to_dict())
    assert "Max Mustermann" not in dumped
    assert "Mein Name ist" not in dumped


def test_redact_extracts_only_fact_text():
    facts = [Fact(text="Pepper wurde 2014 von Aldebaran vorgestellt.", source_id="faq_1", confidence=0.9)]
    redacted = redact_for_external_llm(_brief(facts=facts))
    assert redacted.answer_facts == ["Pepper wurde 2014 von Aldebaran vorgestellt."]
    assert redacted.source_ids == ["faq_1"]


def test_redact_source_ids_only_from_answer_brief():
    facts = [
        Fact(text="Fakt A", source_id="src_a", confidence=0.9),
        Fact(text="Fakt B", source_id="src_b", confidence=0.8),
    ]
    redacted = redact_for_external_llm(_brief(facts=facts))
    assert redacted.source_ids == ["src_a", "src_b"]


def test_redact_person_context_only_known_boolean_dict():
    redacted = redact_for_external_llm(_brief(), person_context={
        "known": True, "display_name": "Max Mustermann", "session_id": "abc123",
    })
    assert redacted.interaction_context.person_known is True
    dumped = str(redacted.to_dict())
    assert "Max Mustermann" not in dumped
    assert "abc123" not in dumped


def test_redact_person_context_only_known_boolean_object():
    class _PersonContext:
        known = True
        display_name = "Max Mustermann"
        session_id = "abc123"

    redacted = redact_for_external_llm(_brief(), person_context=_PersonContext())
    assert redacted.interaction_context.person_known is True
    dumped = str(redacted.to_dict())
    assert "Max Mustermann" not in dumped


def test_redact_no_person_context_defaults_to_unknown():
    redacted = redact_for_external_llm(_brief(), person_context=None)
    assert redacted.interaction_context.person_known is False


def test_redact_allowed_gestures_passed_through():
    redacted = redact_for_external_llm(_brief(), allowed_gesture_names=["wave_right", "nod"])
    assert redacted.allowed_gestures == ["wave_right", "nod"]


def test_redact_schema_version_and_language():
    redacted = redact_for_external_llm(_brief(), language="de")
    d = redacted.to_dict()
    assert d["schema_version"] == 1
    assert d["language"] == "de"


# ---- Interne IP / zugangsdatenaehnliche Muster ----

def test_redact_rejects_internal_ip_in_fact_text():
    facts = [Fact(text="Der NUC hat die Adresse 192.168.1.42.", source_id="s1", confidence=0.9)]
    with pytest.raises(DisallowedContentError):
        redact_for_external_llm(_brief(facts=facts))


def test_redact_rejects_10_range_internal_ip():
    facts = [Fact(text="Verbindung zu 10.0.0.5 fehlgeschlagen.", source_id="s1", confidence=0.9)]
    with pytest.raises(DisallowedContentError):
        redact_for_external_llm(_brief(facts=facts))


def test_redact_rejects_credential_like_pattern():
    facts = [Fact(text="api_key: abc123def456", source_id="s1", confidence=0.9)]
    with pytest.raises(DisallowedContentError):
        redact_for_external_llm(_brief(facts=facts))


def test_redact_allows_normal_fact_text():
    facts = [Fact(text="Pepper ist 1,20 Meter gross.", source_id="s1", confidence=0.9)]
    redacted = redact_for_external_llm(_brief(facts=facts))
    assert redacted.answer_facts == ["Pepper ist 1,20 Meter gross."]


# ---- reinsert_display_name (Nachbereitung, nicht Teil des externen Prompts) ----

def test_reinsert_display_name_requires_consent():
    text = reinsert_display_name("Hallo {name}, schoen dich zu sehen.", "{name}", "Max", consent_granted=False)
    assert "Max" not in text
    assert text == "Hallo {name}, schoen dich zu sehen."


def test_reinsert_display_name_with_consent():
    text = reinsert_display_name("Hallo {name}, schoen dich zu sehen.", "{name}", "Max", consent_granted=True)
    assert text == "Hallo Max, schoen dich zu sehen."


def test_reinsert_display_name_no_placeholder_no_op():
    text = reinsert_display_name("Hallo, schoen dich zu sehen.", "{name}", "Max", consent_granted=True)
    assert text == "Hallo, schoen dich zu sehen."


def test_reinsert_display_name_no_display_name_no_op():
    text = reinsert_display_name("Hallo {name}.", "{name}", None, consent_granted=True)
    assert text == "Hallo {name}."
