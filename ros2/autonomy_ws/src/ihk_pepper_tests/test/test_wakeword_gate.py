"""
Tests fuer wakeword_gate.py (Entwicklungsauftrag 04-B, AP6, Abschnitt 8).
"""
from ihk_pepper_audio.wakeword_gate import WakewordGate, is_event_fresh


def _make_gate(cooldown_s=3.0, start=1000.0):
    time_box = {"t": start}
    gate = WakewordGate(cooldown_s=cooldown_s, now_fn=lambda: time_box["t"],
                         id_fn=lambda: "fixed-id")
    return gate, time_box


def test_pepper_in_idle_produces_exactly_one_event():
    gate, _ = _make_gate()
    event = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    assert event is not None
    assert event.keyword == "pepper"


def test_repeat_within_cooldown_produces_no_second_event():
    gate, t = _make_gate(cooldown_s=3.0)
    first = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    assert first is not None
    t["t"] += 1.0  # innerhalb des Cooldowns
    second = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    assert second is None


def test_repeat_after_cooldown_produces_a_new_event():
    gate, t = _make_gate(cooldown_s=3.0)
    gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    t["t"] += 3.5  # ueber dem Cooldown
    second = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    assert second is not None


def test_other_word_produces_no_event():
    gate, _ = _make_gate()
    event = gate.evaluate(keyword_detected=False, keyword_confidence=0.0, conversation_active=False)
    assert event is None


def test_active_conversation_blocks_wakeword():
    gate, _ = _make_gate()
    event = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=True)
    assert event is None


def test_low_confidence_below_threshold_produces_no_event():
    gate, _ = _make_gate()
    event = gate.evaluate(
        keyword_detected=True, keyword_confidence=0.2, conversation_active=False,
        min_keyword_confidence=0.5,
    )
    assert event is None


def test_event_carries_direction_fields_through():
    gate, _ = _make_gate()
    event = gate.evaluate(
        keyword_detected=True, keyword_confidence=0.9, conversation_active=False,
        azimuth_rad=0.7, direction_confidence=0.85, direction_valid=True,
    )
    assert event.azimuth_rad == 0.7
    assert event.direction_confidence == 0.85
    assert event.direction_valid is True


def test_event_id_is_unique_per_event(monkeypatch):
    import itertools
    counter = itertools.count()
    gate = WakewordGate(cooldown_s=0.0, now_fn=lambda: 1000.0 + next(counter),
                         id_fn=lambda: f"event-{next(counter)}")
    first = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    second = gate.evaluate(keyword_detected=True, keyword_confidence=0.9, conversation_active=False)
    assert first.event_id != second.event_id


def test_is_event_fresh_within_bound():
    assert is_event_fresh(event_monotonic_timestamp=100.0, now=100.5, max_age_s=1.0) is True


def test_is_event_fresh_exceeds_bound():
    assert is_event_fresh(event_monotonic_timestamp=100.0, now=105.0, max_age_s=1.0) is False
