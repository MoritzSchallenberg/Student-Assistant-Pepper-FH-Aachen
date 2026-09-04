import pytest

from ihk_pepper_person_memory.identity_registry import ConsentStatus
from ihk_pepper_person_memory.identity_registry_db import IdentityRegistryStore


@pytest.fixture
def store(tmp_path):
    s = IdentityRegistryStore(str(tmp_path / "identity.db"))
    yield s
    s.close()


def test_unknown_person_lookup_returns_none(store):
    assert store.lookup("p_unknown") is None


def test_create_or_touch_creates_with_not_asked_consent(store):
    record = store.create_or_touch("p1", confidence=0.8, reason="first_seen")
    assert record.person_id == "p1"
    assert record.consent_status == ConsentStatus.NOT_ASKED.value
    assert record.confidence == 0.8


def test_create_or_touch_second_call_updates_not_duplicates(store):
    store.create_or_touch("p1", confidence=0.5, reason="seen_1")
    updated = store.create_or_touch("p1", confidence=0.9, reason="seen_2")
    assert updated.confidence == 0.9


def test_set_consent_granted_allows_storage(store):
    store.create_or_touch("p1", reason="seen")
    record = store.set_consent("p1", ConsentStatus.GRANTED.value, reason="user_agreed_verbally")
    assert record.consent_status == ConsentStatus.GRANTED.value


def test_set_consent_invalid_value_rejected(store):
    store.create_or_touch("p1", reason="seen")
    with pytest.raises(ValueError):
        store.set_consent("p1", "maybe", reason="test")


def test_set_consent_unknown_person_rejected(store):
    with pytest.raises(KeyError):
        store.set_consent("p_ghost", ConsentStatus.GRANTED.value, reason="test")


def test_set_display_name_requires_existing_person(store):
    with pytest.raises(KeyError):
        store.set_display_name("p_ghost", "Max", reason="test")


def test_set_display_name_updates_record(store):
    store.create_or_touch("p1", reason="seen")
    record = store.set_display_name("p1", "Max", reason="user_provided_name")
    assert record.display_name == "Max"


def test_delete_removes_person_entirely(store):
    store.create_or_touch("p1", reason="seen")
    deleted = store.delete("p1", reason="user_requested_deletion")
    assert deleted is True
    assert store.lookup("p1") is None


def test_delete_unknown_person_returns_false(store):
    assert store.delete("p_ghost", reason="test") is False


def test_every_write_requires_a_reason(store):
    store.create_or_touch("p1", reason="seen")
    with pytest.raises(ValueError):
        store.set_display_name("p1", "Max", reason="")


def test_get_context_unknown_person_is_not_known(store):
    ctx = store.get_context("p_ghost")
    assert ctx == {"known": False, "display_name": None, "person_id": None}


def test_get_context_without_consent_stays_unknown(store):
    store.create_or_touch("p1", reason="seen")
    ctx = store.get_context("p1")
    assert ctx["known"] is False


def test_get_context_with_granted_consent_is_known(store):
    store.create_or_touch("p1", reason="seen")
    store.set_consent("p1", ConsentStatus.GRANTED.value, reason="agreed")
    store.set_display_name("p1", "Max", reason="provided")
    ctx = store.get_context("p1")
    assert ctx == {"known": True, "display_name": "Max", "person_id": "p1"}


def test_get_context_after_withdrawn_consent_no_longer_known(store):
    store.create_or_touch("p1", reason="seen")
    store.set_consent("p1", ConsentStatus.GRANTED.value, reason="agreed")
    store.set_consent("p1", ConsentStatus.WITHDRAWN.value, reason="user_withdrew")
    ctx = store.get_context("p1")
    assert ctx["known"] is False


def test_no_cross_person_leakage(store):
    store.create_or_touch("p1", reason="seen")
    store.set_consent("p1", ConsentStatus.GRANTED.value, reason="agreed")
    store.set_display_name("p1", "Max", reason="provided")
    store.create_or_touch("p2", reason="seen")
    assert store.get_context("p2")["known"] is False
    assert store.lookup("p2").display_name is None


def test_data_persists_after_reopening_store(tmp_path):
    db_path = str(tmp_path / "identity.db")
    store1 = IdentityRegistryStore(db_path)
    store1.create_or_touch("p1", reason="seen")
    store1.set_consent("p1", ConsentStatus.GRANTED.value, reason="agreed")
    store1.close()

    store2 = IdentityRegistryStore(db_path)
    record = store2.lookup("p1")
    assert record is not None
    assert record.consent_status == ConsentStatus.GRANTED.value
    store2.close()


def test_byte_track_id_is_never_used_as_person_id_implicitly(store):
    """Diese Klasse kennt keine Track-IDs -- ein Aufrufer MUSS explizit
    eine person_id uebergeben, es gibt keine automatische Ableitung."""
    import inspect
    sig = inspect.signature(store.create_or_touch)
    assert "track_id" not in sig.parameters
    assert "person_id" in sig.parameters
