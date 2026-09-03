from ihk_pepper_person_memory.identity_registry import (
    ConsentStatus,
    IdentityRecord,
    effective_session_key,
    is_storage_allowed,
)
from ihk_pepper_person_memory.mood_signal import MoodObservation
from ihk_pepper_person_memory.vector_memory import MemoryEntry, validate_memory_write


def test_storage_allowed_only_with_granted_consent():
    granted = IdentityRecord(person_id="p1", consent_status=ConsentStatus.GRANTED.value)
    denied = IdentityRecord(person_id="p2", consent_status=ConsentStatus.DENIED.value)
    not_asked = IdentityRecord(person_id="p3")
    assert is_storage_allowed(granted) is True
    assert is_storage_allowed(denied) is False
    assert is_storage_allowed(not_asked) is False


def test_effective_session_key_falls_back_without_consent():
    denied = IdentityRecord(person_id="p2", consent_status=ConsentStatus.DENIED.value)
    assert effective_session_key(denied, "session-xyz") == "session-xyz"
    assert effective_session_key(None, "session-xyz") == "session-xyz"


def test_effective_session_key_uses_person_id_with_consent():
    granted = IdentityRecord(person_id="p1", consent_status=ConsentStatus.GRANTED.value)
    assert effective_session_key(granted, "session-xyz") == "p1"


def test_memory_write_rejected_without_matching_identity():
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-03T10:00:00",
        text_summary="mag Robotik", valid_until_iso="2026-12-01T00:00:00",
    )
    errors = validate_memory_write(entry, identity=None)
    assert any("Identity-Record" in e for e in errors)


def test_memory_write_rejected_without_consent():
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-03T10:00:00",
        text_summary="mag Robotik", valid_until_iso="2026-12-01T00:00:00",
    )
    identity = IdentityRecord(person_id="p1", consent_status=ConsentStatus.NOT_ASKED.value)
    errors = validate_memory_write(entry, identity)
    assert any("Einwilligung" in e for e in errors)


def test_memory_write_rejected_without_retention_rule():
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-03T10:00:00",
        text_summary="mag Robotik", valid_until_iso=None,
    )
    identity = IdentityRecord(person_id="p1", consent_status=ConsentStatus.GRANTED.value)
    errors = validate_memory_write(entry, identity)
    assert any("Gueltigkeits" in e for e in errors)


def test_memory_write_rejected_when_embedding_ref_looks_like_raw_payload():
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-03T10:00:00",
        text_summary="mag Robotik", valid_until_iso="2026-12-01T00:00:00",
        embedding_ref="x" * 1000,
    )
    identity = IdentityRecord(person_id="p1", consent_status=ConsentStatus.GRANTED.value)
    errors = validate_memory_write(entry, identity)
    assert any("Rohdaten" in e for e in errors)


def test_memory_write_valid_with_consent_and_retention():
    entry = MemoryEntry(
        person_id="p1", source="dialog_session", timestamp_iso="2026-09-03T10:00:00",
        text_summary="mag Robotik", valid_until_iso="2026-12-01T00:00:00",
        embedding_ref="vector-store://p1/2026-09-03",
    )
    identity = IdentityRecord(person_id="p1", consent_status=ConsentStatus.GRANTED.value)
    errors = validate_memory_write(entry, identity)
    assert errors == []


def test_mood_observation_is_never_usable_as_fact():
    obs = MoodObservation(label="happy", confidence=0.9, observed_at_iso="2026-09-03T10:00:00")
    assert obs.is_usable_as_fact() is False
