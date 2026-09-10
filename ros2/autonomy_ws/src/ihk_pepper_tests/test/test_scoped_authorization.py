"""
Tests fuer scoped_authorization.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 9) -- deckt explizit alle im Auftrag genannten Angriffs-/
Fehlerfaelle ab: Wiederverwendung, falscher Befehl/Person/Track/
Sitzung, abgelaufen, doppelt bestaetigt, globales True ohne
passenden Request.
"""
import pytest

from ihk_pepper_interaction.scoped_authorization import CurrentContext, ScopedAuthorizationStore


def _store(now_s=1000.0, ids=None):
    ids = iter(ids or [f"id{i}" for i in range(1, 100)])
    return ScopedAuthorizationStore(now_fn=lambda: now_s, id_fn=lambda: next(ids))


def _current(track_id=5, person_id="p1", role="employee", command="follow_speaker",
             session_id="s1", safety_state_valid=True):
    return CurrentContext(
        track_id=track_id, person_id=person_id, role=role, command=command,
        session_id=session_id, safety_state_valid=safety_state_valid)


def _create(store, **overrides):
    defaults = dict(
        event_id="evt1", interaction_id="i1", session_id="s1", track_id=5,
        person_id="p1", role="employee", command="follow_speaker",
        requested_capability="follow_speaker", reason="privileged", validity_s=30.0,
    )
    defaults.update(overrides)
    return store.create_request(**defaults)


def test_create_request_has_a_unique_id_and_nonce():
    store = _store()
    r1 = _create(store)
    r2 = _create(store)
    assert r1.request_id != r2.request_id
    assert r1.nonce != r2.nonce


def test_valid_confirmation_succeeds():
    store = _store()
    record = _create(store)
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current())
    assert ok is True
    assert reason == ""


def test_reuse_of_an_already_confirmed_request_is_rejected():
    store = _store()
    record = _create(store)
    store.confirm(record.request_id, record.nonce, True, _current())
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current())
    assert ok is False
    assert reason == "request_unbekannt_oder_bereits_verwendet"


def test_unknown_request_id_is_rejected():
    store = _store()
    ok, reason = store.confirm("ghost", "nonce", True, _current())
    assert ok is False
    assert reason == "request_unbekannt_oder_bereits_verwendet"


def test_wrong_nonce_is_rejected_without_consuming_the_request():
    store = _store()
    record = _create(store)
    ok, reason = store.confirm(record.request_id, "wrong-nonce", True, _current())
    assert ok is False
    assert reason == "falscher_nonce"
    # Der echte Nonce funktioniert danach immer noch -- ein einzelner
    # Ratefehler darf die echte Anfrage nicht blockieren.
    ok2, _ = store.confirm(record.request_id, record.nonce, True, _current())
    assert ok2 is True


def test_expired_request_is_rejected():
    store = _store(now_s=1000.0)
    record = _create(store, validity_s=10.0)
    store._now_fn = lambda: 1000.0 + 11.0
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current())
    assert ok is False
    assert reason == "request_abgelaufen"


def test_explicit_denial_is_rejected_and_consumes_the_request():
    store = _store()
    record = _create(store)
    ok, reason = store.confirm(record.request_id, record.nonce, False, _current())
    assert ok is False
    assert reason == "abgelehnt"
    # Danach ist der Request verbraucht -- keine zweite Chance.
    ok2, reason2 = store.confirm(record.request_id, record.nonce, True, _current())
    assert ok2 is False
    assert reason2 == "request_unbekannt_oder_bereits_verwendet"


def test_confirmation_after_a_track_change_is_rejected():
    store = _store()
    record = _create(store, track_id=5)
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current(track_id=99))
    assert ok is False
    assert reason == "track_hat_sich_geaendert"


def test_confirmation_by_a_different_person_is_rejected():
    store = _store()
    record = _create(store, person_id="p1")
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current(person_id="p2"))
    assert ok is False
    assert reason == "person_hat_sich_geaendert"


def test_confirmation_for_a_different_command_is_rejected():
    store = _store()
    record = _create(store, command="follow_speaker")
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current(command="delete_person"))
    assert ok is False
    assert reason == "befehl_hat_sich_geaendert"


def test_confirmation_after_session_end_is_rejected():
    store = _store()
    record = _create(store, session_id="s1")
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current(session_id="s2"))
    assert ok is False
    assert reason == "sitzung_hat_sich_geaendert"


def test_confirmation_with_an_invalid_safety_state_is_rejected():
    store = _store()
    record = _create(store)
    ok, reason = store.confirm(
        record.request_id, record.nonce, True, _current(safety_state_valid=False))
    assert ok is False
    assert reason == "sicherheitszustand_ungueltig"


def test_role_change_since_the_request_is_rejected():
    store = _store()
    record = _create(store, role="employee")
    ok, reason = store.confirm(record.request_id, record.nonce, True, _current(role="student"))
    assert ok is False
    assert reason == "rolle_hat_sich_geaendert"


def test_purge_expired_removes_only_stale_requests_and_returns_their_ids():
    store = _store(now_s=1000.0)
    stale = _create(store, validity_s=1.0)
    fresh = _create(store, validity_s=1000.0)
    store._now_fn = lambda: 1000.0 + 5.0
    removed = store.purge_expired()
    assert removed == [stale.request_id]
    assert store.get(fresh.request_id) is not None
    assert store.get(stale.request_id) is None
