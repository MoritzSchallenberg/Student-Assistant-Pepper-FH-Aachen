"""
Tests fuer origin_session.py (Entwicklungsauftrag 04-B, AP7, Abschnitt 9/12).
"""
from ihk_pepper_navigation.origin_session import OriginStore


def _store(now_s=1000.0):
    return OriginStore(now_fn=lambda: now_s)


def test_capture_returns_a_record_with_a_unique_id():
    store = _store()
    r1 = store.capture("s1", "map", 1.0, 2.0, 0.5, initial_track_id=7)
    r2 = store.capture("s1", "map", 1.0, 2.0, 0.5, initial_track_id=7)
    assert r1.origin_id != r2.origin_id
    assert r1.session_id == "s1"
    assert r1.frame_id == "map"
    assert r1.x == 1.0 and r1.y == 2.0 and r1.yaw_rad == 0.5
    assert r1.initial_track_id == 7


def test_validate_succeeds_for_a_fresh_matching_origin():
    store = _store()
    record = store.capture("s1", "map", 1.0, 2.0, 0.0, initial_track_id=1)
    ok, reason, got = store.validate(record.origin_id, "s1", max_age_s=60.0)
    assert ok is True
    assert reason == ""
    assert got == record


def test_validate_rejects_unknown_origin_id():
    store = _store()
    ok, reason, got = store.validate("ghost", "s1", max_age_s=60.0)
    assert ok is False
    assert reason == "ursprung_unbekannt"
    assert got is None


def test_validate_rejects_a_session_id_mismatch():
    store = _store()
    record = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    ok, reason, got = store.validate(record.origin_id, "s2", max_age_s=60.0)
    assert ok is False
    assert reason == "ursprung_gehoert_anderer_sitzung"


def test_validate_rejects_a_stale_origin():
    store = _store(now_s=1000.0)
    record = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    store._now_fn = lambda: 1000.0 + 100.0  # 100s spaeter
    ok, reason, got = store.validate(record.origin_id, "s1", max_age_s=60.0)
    assert ok is False
    assert reason == "ursprung_veraltet"


def test_validate_with_zero_max_age_disables_the_staleness_check():
    store = _store(now_s=1000.0)
    record = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    store._now_fn = lambda: 1000.0 + 999999.0
    ok, reason, got = store.validate(record.origin_id, "s1", max_age_s=0.0)
    assert ok is True


def test_validate_does_not_consume_the_origin():
    store = _store()
    record = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    store.validate(record.origin_id, "s1", max_age_s=60.0)
    ok, _, _ = store.validate(record.origin_id, "s1", max_age_s=60.0)
    assert ok is True  # ein zweiter Versuch nach einem Abbruch bleibt moeglich


def test_invalidate_session_only_removes_that_sessions_origins():
    store = _store()
    r1 = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    r2 = store.capture("s2", "map", 0.0, 0.0, 0.0, initial_track_id=2)
    removed = store.invalidate_session("s1")
    assert removed == 1
    assert store.get(r1.origin_id) is None
    assert store.get(r2.origin_id) is not None


def test_invalidate_all_removes_every_origin_regardless_of_session():
    store = _store()
    store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    store.capture("s2", "map", 0.0, 0.0, 0.0, initial_track_id=2)
    removed = store.invalidate_all()
    assert removed == 2
    ok, reason, _ = store.validate("anything", "s1", max_age_s=60.0)
    assert ok is False


# ---- Entwicklungsauftrag 04-B, AP7.1, Abschnitt 3.4: interaction_id/
#      map_generation_id-Bindung ----

def test_capture_stores_interaction_id_and_reason():
    store = _store()
    record = store.capture(
        "s1", "map", 0.0, 0.0, 0.0, initial_track_id=1,
        interaction_id="authorized_follow", reason="Pepper, komm mal mit",
    )
    assert record.interaction_id == "authorized_follow"
    assert record.reason == "Pepper, komm mal mit"


def test_validate_rejects_a_different_interaction_id():
    store = _store()
    record = store.capture(
        "s1", "map", 0.0, 0.0, 0.0, initial_track_id=1, interaction_id="authorized_follow")
    ok, reason, got = store.validate(
        record.origin_id, "s1", max_age_s=60.0, interaction_id="single_person_conversation")
    assert ok is False
    assert reason == "ursprung_gehoert_anderer_interaktion"


def test_validate_accepts_a_matching_interaction_id():
    store = _store()
    record = store.capture(
        "s1", "map", 0.0, 0.0, 0.0, initial_track_id=1, interaction_id="authorized_follow")
    ok, reason, got = store.validate(
        record.origin_id, "s1", max_age_s=60.0, interaction_id="authorized_follow")
    assert ok is True


def test_validate_ignores_interaction_id_when_not_provided_by_either_side():
    # Rueckwaertskompatibilitaet: bestehende Aufrufer ohne interaction_id
    # bleiben unveraendert funktionsfaehig.
    store = _store()
    record = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    ok, reason, got = store.validate(record.origin_id, "s1", max_age_s=60.0)
    assert ok is True


def test_validate_ignores_interaction_id_when_the_caller_does_not_pass_one():
    # Ein Ursprung MIT interaction_id bleibt fuer einen Aufrufer gueltig,
    # der (noch) keine interaction_id prueft (leer = "nicht pruefen").
    store = _store()
    record = store.capture(
        "s1", "map", 0.0, 0.0, 0.0, initial_track_id=1, interaction_id="authorized_follow")
    ok, reason, got = store.validate(record.origin_id, "s1", max_age_s=60.0)
    assert ok is True


def test_invalidate_all_increments_the_map_generation_and_rejects_old_records():
    store = _store()
    record = store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    # invalidate_all() loescht record bereits vollstaendig -- ein neuer
    # Ursprung mit derselben (hypothetisch wiederverwendeten) origin_id
    # kann in der Praxis nicht auftreten (uuid4), dieser Test prueft
    # daher direkt den Verteidigungs-in-der-Tiefe-Zweig ueber einen
    # manuell wiedereingefuegten, veralteten Datensatz.
    store.invalidate_all()
    store._origins[record.origin_id] = record  # simuliert einen uebersprungenen invalidate_all()
    ok, reason, got = store.validate(record.origin_id, "s1", max_age_s=60.0)
    assert ok is False
    assert reason == "karte_hat_sich_geaendert"
