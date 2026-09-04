import time

import pytest

from ihk_pepper_person_memory.embedding_backend import DifflibFallbackBackend
from ihk_pepper_person_memory.identity_registry import ConsentStatus, IdentityRecord
from ihk_pepper_person_memory.vector_memory import MemoryEntry
from ihk_pepper_person_memory.vector_memory_db import VectorMemoryStore


def _future_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))


def _past_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))


@pytest.fixture
def store(tmp_path):
    # Difflib-Backend explizit erzwungen -- Tests sollen nicht davon
    # abhaengen, ob sentence-transformers in dieser Umgebung installiert ist.
    s = VectorMemoryStore(str(tmp_path / "memory.db"), embedding_backend=DifflibFallbackBackend())
    yield s
    s.close()


def _granted_identity(person_id="p1"):
    return IdentityRecord(person_id=person_id, consent_status=ConsentStatus.GRANTED.value)


def test_write_known_person_with_consent_succeeds(store):
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-04T10:00:00Z",
        topics=["Weiterbildung"], text_summary="Gespraech ueber Weiterbildung.",
        valid_until_iso=_future_iso(),
    )
    errors = store.write_validated_summary(entry, _granted_identity())
    assert errors == []


def test_write_unknown_person_rejected(store):
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-04T10:00:00Z",
        topics=["x"], text_summary="y", valid_until_iso=_future_iso(),
    )
    errors = store.write_validated_summary(entry, None)
    assert errors != []
    assert store.query_by_topic("p1", "x") == []


def test_write_denied_consent_rejected(store):
    identity = IdentityRecord(person_id="p1", consent_status=ConsentStatus.DENIED.value)
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="t",
        topics=["x"], text_summary="y", valid_until_iso=_future_iso(),
    )
    errors = store.write_validated_summary(entry, identity)
    assert errors != []


def test_write_withdrawn_consent_rejected(store):
    identity = IdentityRecord(person_id="p1", consent_status=ConsentStatus.WITHDRAWN.value)
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="t",
        topics=["x"], text_summary="y", valid_until_iso=_future_iso(),
    )
    errors = store.write_validated_summary(entry, identity)
    assert errors != []


def test_query_by_topic_finds_matching_entry(store):
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="t",
        topics=["Weiterbildung", "Ausbildung"], text_summary="Gespraech ueber Weiterbildung.",
        valid_until_iso=_future_iso(),
    )
    store.write_validated_summary(entry, _granted_identity())
    hits = store.query_by_topic("p1", "Weiterbildung")
    assert len(hits) == 1
    assert "Weiterbildung" in hits[0]["summary"]


def test_query_by_topic_is_case_insensitive_via_normalization(store):
    entry = MemoryEntry(
        person_id="p1", source="s", timestamp_iso="t", topics=["Weiterbildung"],
        text_summary="x", valid_until_iso=_future_iso(),
    )
    store.write_validated_summary(entry, _granted_identity())
    hits = store.query_by_topic("p1", "WEITERBILDUNG")
    assert len(hits) == 1


def test_no_memory_across_different_person_ids(store):
    store.write_validated_summary(
        MemoryEntry(person_id="p1", source="s", timestamp_iso="t", topics=["thema"],
                    text_summary="p1s Geheimnis", valid_until_iso=_future_iso()),
        _granted_identity("p1"),
    )
    hits = store.query_by_topic("p2", "thema")
    assert hits == []


def test_expired_entry_not_returned(store):
    store.write_validated_summary(
        MemoryEntry(person_id="p1", source="s", timestamp_iso="t", topics=["thema"],
                    text_summary="x", valid_until_iso=_past_iso()),
        _granted_identity(),
    )
    assert store.query_by_topic("p1", "thema") == []


def test_delete_for_person_removes_all_entries(store):
    store.write_validated_summary(
        MemoryEntry(person_id="p1", source="s", timestamp_iso="t", topics=["a"],
                    text_summary="x", valid_until_iso=_future_iso()),
        _granted_identity(),
    )
    deleted = store.delete_for_person("p1")
    assert deleted == 1
    assert store.query_by_topic("p1", "a") == []


def test_query_semantic_without_embedding_model_uses_text_fallback(store):
    store.write_validated_summary(
        MemoryEntry(person_id="p1", source="s", timestamp_iso="t", topics=["weiterbildung"],
                    text_summary="wir sprachen ueber weiterbildung und karriere",
                    valid_until_iso=_future_iso()),
        _granted_identity(),
    )
    hits = store.query_semantic("p1", "wir sprachen ueber weiterbildung und karriere", threshold=0.5)
    assert len(hits) >= 1


def test_query_semantic_never_returns_foreign_person_id(store):
    store.write_validated_summary(
        MemoryEntry(person_id="p1", source="s", timestamp_iso="t", topics=["a"],
                    text_summary="ein identischer text als test", valid_until_iso=_future_iso()),
        _granted_identity("p1"),
    )
    hits = store.query_semantic("p2", "ein identischer text als test", threshold=0.1)
    assert hits == []


def test_no_raw_llm_prompt_field_exists_on_memory_entry():
    """Strukturelle Garantie: MemoryEntry hat kein Feld fuer rohe Prompts/
    Chain-of-Thought -- text_summary ist die einzige Textquelle."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(MemoryEntry)}
    assert "raw_prompt" not in field_names
    assert "chain_of_thought" not in field_names
    assert "raw_llm_output" not in field_names


def test_data_persists_after_reopening_store(tmp_path):
    db_path = str(tmp_path / "memory.db")
    store1 = VectorMemoryStore(db_path, embedding_backend=DifflibFallbackBackend())
    store1.write_validated_summary(
        MemoryEntry(person_id="p1", source="s", timestamp_iso="t", topics=["a"],
                    text_summary="x", valid_until_iso=_future_iso()),
        _granted_identity(),
    )
    store1.close()

    store2 = VectorMemoryStore(db_path, embedding_backend=DifflibFallbackBackend())
    hits = store2.query_by_topic("p1", "a")
    assert len(hits) == 1
    store2.close()
