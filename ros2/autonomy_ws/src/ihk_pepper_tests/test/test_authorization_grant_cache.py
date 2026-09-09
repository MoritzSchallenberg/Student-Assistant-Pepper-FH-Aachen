"""
Tests fuer authorization_grant_cache.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 8/9/19).
"""
from ihk_pepper_navigation.authorization_grant_cache import AuthorizationGrantCache


def _cache(now_s=1000.0):
    return AuthorizationGrantCache(now_fn=lambda: now_s)


def test_valid_grant_is_accepted_and_consumed():
    cache = _cache()
    cache.add("g1", "p1", 5, "follow_speaker", expires_at_s=2000.0)
    ok, reason = cache.validate_and_consume("g1", 5, "follow_speaker")
    assert ok is True
    assert reason == ""


def test_grant_can_only_be_used_once():
    cache = _cache()
    cache.add("g1", "p1", 5, "follow_speaker", expires_at_s=2000.0)
    cache.validate_and_consume("g1", 5, "follow_speaker")
    ok, reason = cache.validate_and_consume("g1", 5, "follow_speaker")
    assert ok is False
    assert reason == "grant_unbekannt_oder_bereits_verwendet"


def test_unknown_grant_id_is_rejected():
    cache = _cache()
    ok, reason = cache.validate_and_consume("g_ghost", 5, "follow_speaker")
    assert ok is False
    assert reason == "grant_unbekannt_oder_bereits_verwendet"


def test_empty_grant_id_is_rejected():
    cache = _cache()
    ok, reason = cache.validate_and_consume("", 5, "follow_speaker")
    assert ok is False
    assert reason == "keine_grant_id"


def test_expired_grant_is_rejected():
    cache = _cache(now_s=3000.0)
    cache.add("g1", "p1", 5, "follow_speaker", expires_at_s=2000.0)
    ok, reason = cache.validate_and_consume("g1", 5, "follow_speaker")
    assert ok is False
    assert reason == "grant_abgelaufen"


def test_grant_for_wrong_track_id_is_rejected():
    cache = _cache()
    cache.add("g1", "p1", 5, "follow_speaker", expires_at_s=2000.0)
    ok, reason = cache.validate_and_consume("g1", 99, "follow_speaker")
    assert ok is False
    assert reason == "grant_falscher_track"
    # Der Grant bleibt fuer den RICHTIGEN Track weiterhin gueltig.
    ok2, _ = cache.validate_and_consume("g1", 5, "follow_speaker")
    assert ok2 is True


def test_grant_for_wrong_command_is_rejected():
    cache = _cache()
    cache.add("g1", "p1", 5, "follow_speaker", expires_at_s=2000.0)
    ok, reason = cache.validate_and_consume("g1", 5, "guide_person")
    assert ok is False
    assert reason == "grant_falscher_befehl"


def test_purge_expired_removes_only_stale_entries():
    cache = _cache(now_s=3000.0)
    cache.add("g1", "p1", 5, "follow_speaker", expires_at_s=2000.0)  # abgelaufen
    cache.add("g2", "p2", 6, "follow_speaker", expires_at_s=4000.0)  # gueltig
    removed = cache.purge_expired()
    assert removed == 1
    ok, _ = cache.validate_and_consume("g2", 6, "follow_speaker")
    assert ok is True
