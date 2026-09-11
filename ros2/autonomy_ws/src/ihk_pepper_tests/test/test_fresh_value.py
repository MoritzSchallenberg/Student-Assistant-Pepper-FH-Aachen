"""
Tests fuer safety_topics.py::FreshValue (Entwicklungsauftrag 04-B,
AP8.2) -- dieselbe Aktualitaetslogik wie FreshBool, nur fuer
nicht-boolsche Werte (z.B. current_interaction_state).
"""
from ihk_pepper_bridge.safety_topics import FreshValue


def test_never_received_is_never_fresh():
    v = FreshValue(None)
    assert v.is_fresh(now=100.0, max_age_s=2.0) is False
    assert v.effective(now=100.0, max_age_s=2.0, fail_closed_value="UNKNOWN") == "UNKNOWN"


def test_recently_received_value_is_fresh():
    v = FreshValue(None)
    v.update("IDLE", now=100.0)
    assert v.is_fresh(now=101.0, max_age_s=2.0) is True
    assert v.effective(now=101.0, max_age_s=2.0, fail_closed_value="UNKNOWN") == "IDLE"


def test_stale_value_falls_back_to_the_fail_closed_value():
    v = FreshValue(None)
    v.update("CONVERSATION_READY", now=100.0)
    assert v.is_fresh(now=105.0, max_age_s=2.0) is False
    assert v.effective(now=105.0, max_age_s=2.0, fail_closed_value=None) is None


def test_default_fail_closed_value_is_none():
    v = FreshValue(None)
    v.update("ATTRACT", now=100.0)
    assert v.effective(now=200.0, max_age_s=2.0) is None
