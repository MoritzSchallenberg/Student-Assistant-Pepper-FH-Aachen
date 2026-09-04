from dataclasses import dataclass, field

from ihk_pepper_llm_contracts.retriever import Fact, run_retrieval


@dataclass
class _FakePlan:
    search_queries: list = field(default_factory=list)
    required_data_kinds: list = field(default_factory=list)
    use_person_memory: bool = False


def test_exact_faq_hit_wins_over_semantic_and_memory():
    def faq_lookup(query, mode):
        if mode == "exact":
            return {"id": "42", "answer": "Drei Jahre.", "confidence": 1.0}
        return {"id": "99", "answer": "Sollte nicht verwendet werden.", "confidence": 0.8}

    plan = _FakePlan(search_queries=["Ausbildungsdauer"])
    brief = run_retrieval(plan, "Wie lange?", faq_lookup_fn=faq_lookup)
    assert len(brief.facts) == 1
    assert brief.facts[0].source_id == "faq:42"
    assert brief.facts[0].origin == "faq_exact"


def test_semantic_faq_hit_used_when_no_exact_match():
    def faq_lookup(query, mode):
        if mode == "exact":
            return None
        return {"id": "7", "answer": "Ungefaehr drei Jahre.", "confidence": 0.8}

    plan = _FakePlan(search_queries=["Dauer"])
    brief = run_retrieval(plan, "Wie lange?", faq_lookup_fn=faq_lookup)
    assert brief.facts[0].source_id == "faq:7"
    assert brief.facts[0].origin == "faq_semantic"


def test_person_memory_used_only_with_consent_and_use_flag():
    memory_calls = []

    def person_memory(person_id, topics):
        memory_calls.append(person_id)
        return [{"topic": "Weiterbildung", "summary": "Wir sprachen ueber Weiterbildung.", "confidence": 0.6}]

    plan = _FakePlan(use_person_memory=True)
    brief = run_retrieval(
        plan, "Frage", person_memory_fn=person_memory,
        person_context={"known": True, "person_id": "p1"},
    )
    assert memory_calls == ["p1"]
    assert brief.facts[0].source_id == "memory:topic:weiterbildung"
    assert brief.facts[0].origin == "person_memory"


def test_person_memory_not_used_without_consent():
    memory_calls = []

    def person_memory(person_id, topics):
        memory_calls.append(person_id)
        return [{"topic": "x", "summary": "y", "confidence": 0.5}]

    plan = _FakePlan(use_person_memory=True)
    brief = run_retrieval(
        plan, "Frage", person_memory_fn=person_memory,
        person_context={"known": False},
    )
    assert memory_calls == []
    assert brief.facts == []


def test_person_memory_not_used_without_use_person_memory_flag():
    memory_calls = []

    def person_memory(person_id, topics):
        memory_calls.append(person_id)
        return [{"topic": "x", "summary": "y", "confidence": 0.5}]

    plan = _FakePlan(use_person_memory=False, required_data_kinds=[])
    brief = run_retrieval(
        plan, "Frage", person_memory_fn=person_memory,
        person_context={"known": True, "person_id": "p1"},
    )
    assert memory_calls == []


def test_rag_used_as_last_resort_before_safe_fallback():
    class _Result:
        success = True
        text = "Generierte RAG-Antwort."

    plan = _FakePlan()
    brief = run_retrieval(plan, "Wie lange dauert es?", rag_fn=lambda q: _Result())
    assert brief.facts[0].origin == "rag"
    assert brief.facts[0].source_id.startswith("rag:")


def test_rag_failure_falls_through_to_no_information():
    class _FailedResult:
        success = False
        text = ""

    plan = _FakePlan()
    brief = run_retrieval(plan, "Frage", rag_fn=lambda q: _FailedResult())
    assert brief.facts == []
    assert "keine_verlaessliche_information" in brief.uncertainties


def test_no_sources_configured_gives_safe_no_information_answer():
    plan = _FakePlan()
    brief = run_retrieval(plan, "Frage ohne jede Quelle")
    assert brief.facts == []
    assert brief.uncertainties == ["keine_verlaessliche_information"]


def test_source_ids_are_only_ever_generated_never_invented():
    def faq_lookup(query, mode):
        return {"id": "1", "answer": "a", "confidence": 1.0} if mode == "exact" else None

    plan = _FakePlan(search_queries=["x"])
    brief = run_retrieval(plan, "Frage", faq_lookup_fn=faq_lookup)
    assert brief.source_ids() == ["faq:1"]


def test_answer_brief_contains_person_context_passthrough():
    plan = _FakePlan()
    ctx = {"known": True, "display_name": "Max"}
    brief = run_retrieval(plan, "Frage", person_context=ctx)
    assert brief.person_context == ctx


def test_fact_dataclass_fields():
    fact = Fact(text="t", source_id="faq:1", confidence=0.9)
    assert fact.origin == ""
    assert fact.confidence == 0.9
