"""
Tests fuer die reine Filter-/Rangierungslogik der Gesten-Vektorsuche
(Ergaenzungsauftrag 04-A, gesture_search.py). Kein ROS, keine
Datenbank, kein echtes Embedding-Modell -- ein einfacher Fake-Backend
reicht, um die Reihenfolge deterministisch zu pruefen.
"""
from ihk_pepper_gesture_memory.gesture_search import (
    GestureIndexEntry,
    GestureSearchRequest,
    passes_hard_filters,
    rank_candidates,
)


class _FakeEmbeddingBackend:
    """encode() gibt den Text selbst zurueck, similarity() zaehlt
    gemeinsame Woerter -- ausreichend, um eine deterministische
    Rangfolge in Tests zu erzwingen, ohne ein echtes Modell zu laden."""

    name = "fake"

    def encode(self, text):
        return set(text.lower().split())

    def similarity(self, a, b):
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)


def _entry(name, **overrides):
    base = dict(
        name=name, description=name.replace("_", " "), tested_status="live_validated",
        duration_s=2.0, allowed_interaction_states=[], requires_stationary=False,
        affects_head=False, system_only=False, selectable_by_llm=True,
        embedding={name.replace("_", " ")},
    )
    base.update(overrides)
    return GestureIndexEntry(**base)


# ---- Harte Filter ----

def test_production_mode_requires_live_validated():
    entry = _entry("draft_gesture", tested_status="draft")
    request = GestureSearchRequest(production_mode=True)
    assert passes_hard_filters(entry, request) is False


def test_production_mode_allows_live_validated():
    entry = _entry("wave_right", tested_status="live_validated")
    request = GestureSearchRequest(production_mode=True)
    assert passes_hard_filters(entry, request) is True


def test_production_mode_cannot_be_lowered_by_minimum_tested_status():
    """production_mode=true darf durch KEIN request-Feld unterlaufen
    werden -- auch nicht durch ein explizit gesetztes
    minimum_tested_status='draft'."""
    entry = _entry("draft_gesture", tested_status="dry_run_validated")
    request = GestureSearchRequest(production_mode=True, minimum_tested_status="draft")
    assert passes_hard_filters(entry, request) is False


def test_non_production_default_allows_draft():
    entry = _entry("draft_gesture", tested_status="draft")
    request = GestureSearchRequest(production_mode=False)
    assert passes_hard_filters(entry, request) is True


def test_non_production_minimum_tested_status_respected():
    entry = _entry("draft_gesture", tested_status="draft")
    request = GestureSearchRequest(production_mode=False, minimum_tested_status="dry_run_validated")
    assert passes_hard_filters(entry, request) is False


def test_interaction_state_filter_rejects_wrong_state():
    entry = _entry("greeting", allowed_interaction_states=["IDLE", "ATTRACT"])
    request = GestureSearchRequest(interaction_state="CONVERSATION_READY")
    assert passes_hard_filters(entry, request) is False


def test_interaction_state_filter_allows_matching_state():
    entry = _entry("greeting", allowed_interaction_states=["IDLE", "ATTRACT"])
    request = GestureSearchRequest(interaction_state="ATTRACT")
    assert passes_hard_filters(entry, request) is True


def test_empty_allowed_interaction_states_means_always_allowed():
    entry = _entry("nod", allowed_interaction_states=[])
    request = GestureSearchRequest(interaction_state="ANYTHING")
    assert passes_hard_filters(entry, request) is True


def test_nav2_moving_blocks_requires_stationary():
    entry = _entry("open_arms", requires_stationary=True)
    request = GestureSearchRequest(nav2_moving=True)
    assert passes_hard_filters(entry, request) is False


def test_mapping_active_blocks_head_affecting_gesture():
    entry = _entry("look_around", affects_head=True)
    request = GestureSearchRequest(mapping_active=True)
    assert passes_hard_filters(entry, request) is False


def test_max_duration_filters_too_long_gesture():
    entry = _entry("long_bow", duration_s=5.0)
    request = GestureSearchRequest(max_duration_s=2.0)
    assert passes_hard_filters(entry, request) is False


def test_max_duration_zero_means_no_limit():
    entry = _entry("long_bow", duration_s=100.0)
    request = GestureSearchRequest(max_duration_s=0.0)
    assert passes_hard_filters(entry, request) is True


def test_exclude_recent_filters_cooldown_gesture():
    entry = _entry("wave_right")
    request = GestureSearchRequest(exclude_recent=["wave_right", "nod"])
    assert passes_hard_filters(entry, request) is False


def test_system_only_excluded_by_default():
    entry = _entry("thinking_loop_subtle", system_only=True)
    request = GestureSearchRequest(include_system_only=False)
    assert passes_hard_filters(entry, request) is False


def test_system_only_included_when_explicitly_requested():
    entry = _entry("thinking_loop_subtle", system_only=True)
    request = GestureSearchRequest(include_system_only=True)
    assert passes_hard_filters(entry, request) is True


def test_not_selectable_by_llm_excluded_from_llm_style_query():
    entry = _entry("thinking_loop_subtle", selectable_by_llm=False)
    request = GestureSearchRequest(query="denken", include_system_only=False)
    assert passes_hard_filters(entry, request) is False


def test_not_selectable_by_llm_included_for_internal_query_without_search_text():
    """Ohne Suchtext (z.B. gesturectl list-artige Introspektion) wird
    selectable_by_llm=False nicht zusaetzlich blockiert -- nur
    system_only blockt unabhaengig vom Suchtext."""
    entry = _entry("thinking_loop_subtle", selectable_by_llm=False, system_only=False)
    request = GestureSearchRequest(query="")
    assert passes_hard_filters(entry, request) is True


# ---- Rangierung ----

def test_rank_candidates_orders_by_similarity():
    entries = [
        _entry("wave_hello", description="wave hello greeting", embedding={"wave", "hello", "greeting"}),
        _entry("small_bow", description="small bow greeting", embedding={"small", "bow", "greeting"}),
        _entry("point_to_self", description="point to self", embedding={"point", "to", "self"}),
    ]
    request = GestureSearchRequest(query="hello greeting")
    ranked = rank_candidates(entries, request, _FakeEmbeddingBackend())

    names_in_order = [entry.name for entry, _score in ranked]
    assert names_in_order[0] == "wave_hello"
    assert "point_to_self" in names_in_order  # niedrigster Score, aber nicht hart gefiltert


def test_rank_candidates_respects_top_k():
    entries = [_entry(f"gesture_{i}", embedding={f"word{i}"}) for i in range(10)]
    request = GestureSearchRequest(query="", top_k=3)
    ranked = rank_candidates(entries, request, _FakeEmbeddingBackend())
    assert len(ranked) == 3


def test_rank_candidates_default_top_k_is_five():
    entries = [_entry(f"gesture_{i}", embedding={f"word{i}"}) for i in range(10)]
    request = GestureSearchRequest(query="")
    ranked = rank_candidates(entries, request, _FakeEmbeddingBackend())
    assert len(ranked) == 5


def test_rank_candidates_without_query_is_alphabetically_stable():
    entries = [_entry("zebra_gesture"), _entry("alpha_gesture"), _entry("mid_gesture")]
    request = GestureSearchRequest(query="", top_k=10)
    ranked = rank_candidates(entries, request, _FakeEmbeddingBackend())
    names_in_order = [entry.name for entry, _score in ranked]
    assert names_in_order == ["alpha_gesture", "mid_gesture", "zebra_gesture"]


def test_rank_candidates_excludes_hard_filtered_entries_entirely():
    entries = [
        _entry("draft_only", tested_status="draft", embedding={"greeting"}),
        _entry("live_gesture", tested_status="live_validated", embedding={"greeting"}),
    ]
    request = GestureSearchRequest(query="greeting", production_mode=True, top_k=10)
    ranked = rank_candidates(entries, request, _FakeEmbeddingBackend())
    names_in_order = [entry.name for entry, _score in ranked]
    assert names_in_order == ["live_gesture"]
