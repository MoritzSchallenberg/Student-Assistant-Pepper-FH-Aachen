import json

from ihk_pepper_llm_contracts.gesture_planner import GesturePlanResponse, GestureSuggestion
from ihk_pepper_llm_contracts.pipeline import run_response_composer
from ihk_pepper_llm_contracts.providers import MockLLMProvider
from ihk_pepper_llm_contracts.retriever import AnswerBrief, Fact


def _brief_with_fact():
    return AnswerBrief(
        question="Wie lange dauert die Ausbildung?",
        facts=[Fact(text="Die Ausbildung dauert drei Jahre.", source_id="faq:42", confidence=0.96)],
    )


def _empty_brief():
    return AnswerBrief(question="Unbeantwortbare Frage", facts=[], uncertainties=["keine_verlaessliche_information"])


def test_valid_response_composer_output_passes_through():
    provider = MockLLMProvider(fixed_response=json.dumps({
        "schema_version": 1,
        "segments": [{"segment_id": "answer", "text": "Die Ausbildung dauert drei Jahre.",
                      "gesture_name": None, "gesture_relation": None}],
        "source_ids": ["faq:42"],
        "memory_summary_candidate": None,
    }))
    plan = run_response_composer(
        provider, "Wie lange dauert die Ausbildung?", _brief_with_fact(),
        GesturePlanResponse(suggestions=[]), ["open_arms"],
    )
    assert plan.segments[0].segment_id == "answer"
    assert plan.source_ids == ["faq:42"]


def test_provider_failure_falls_back_to_facts_as_sentences():
    provider = MockLLMProvider(fail=True)
    plan = run_response_composer(
        provider, "Frage", _brief_with_fact(), GesturePlanResponse(suggestions=[]), [],
    )
    assert len(plan.segments) == 1
    assert plan.segments[0].text == "Die Ausbildung dauert drei Jahre."
    assert plan.segments[0].gesture_name is None
    assert plan.source_ids == ["faq:42"]


def test_invalid_json_falls_back_to_facts_as_sentences():
    provider = MockLLMProvider(fixed_response="kein json {{{")
    plan = run_response_composer(
        provider, "Frage", _brief_with_fact(), GesturePlanResponse(suggestions=[]), [],
    )
    assert plan.segments[0].text == "Die Ausbildung dauert drei Jahre."


def test_no_facts_gives_safe_no_information_fallback():
    provider = MockLLMProvider(fail=True)
    plan = run_response_composer(
        provider, "Unbeantwortbare Frage", _empty_brief(), GesturePlanResponse(suggestions=[]), [],
    )
    assert len(plan.segments) == 1
    assert "keine verlaessliche Information" in plan.segments[0].text
    assert plan.source_ids == []


def test_fallback_segment_ids_are_unique():
    brief = AnswerBrief(
        question="Frage", facts=[
            Fact(text="Fakt A.", source_id="faq:1", confidence=0.9),
            Fact(text="Fakt B.", source_id="faq:2", confidence=0.8),
        ],
    )
    provider = MockLLMProvider(fail=True)
    plan = run_response_composer(provider, "Frage", brief, GesturePlanResponse(suggestions=[]), [])
    ids = [s.segment_id for s in plan.segments]
    assert len(ids) == len(set(ids))


def test_no_segments_in_llm_output_triggers_fallback():
    provider = MockLLMProvider(fixed_response=json.dumps({
        "schema_version": 1, "segments": [], "source_ids": [], "memory_summary_candidate": None,
    }))
    plan = run_response_composer(
        provider, "Frage", _brief_with_fact(), GesturePlanResponse(suggestions=[]), [],
    )
    assert len(plan.segments) == 1
    assert plan.segments[0].text == "Die Ausbildung dauert drei Jahre."


def test_prompt_never_contains_raw_answer_brief_source_ids_as_instruction():
    """source_ids duerfen nur aus answer_brief uebernommen werden -- der
    Prompt selbst stellt answer_brief_facts als reines Datenfeld dar."""
    provider = MockLLMProvider(fixed_response=json.dumps({
        "schema_version": 1,
        "segments": [{"segment_id": "a", "text": "Text.", "gesture_name": None, "gesture_relation": None}],
        "source_ids": [], "memory_summary_candidate": None,
    }))
    run_response_composer(
        provider, "Frage", _brief_with_fact(), GesturePlanResponse(suggestions=[]), ["open_arms"],
    )
    sent_prompt = provider.calls[0]
    assert "faq:42" in sent_prompt  # als Datenfeld enthalten
    assert "erfinde" not in sent_prompt.lower() or "NIEMALS" in sent_prompt  # Regeltext vorhanden


def test_suggested_gestures_from_gesture_plan_are_passed_as_context():
    provider = MockLLMProvider(fixed_response=json.dumps({
        "schema_version": 1,
        "segments": [{"segment_id": "a", "text": "Text.", "gesture_name": "open_arms",
                      "gesture_relation": "with_segment_start"}],
        "source_ids": [], "memory_summary_candidate": None,
    }))
    gesture_plan = GesturePlanResponse(suggestions=[
        GestureSuggestion(gesture_name="open_arms", relation="with_segment_start"),
    ])
    run_response_composer(
        provider, "Frage", _brief_with_fact(), gesture_plan, ["open_arms"],
    )
    sent_prompt = provider.calls[0]
    assert "open_arms" in sent_prompt
