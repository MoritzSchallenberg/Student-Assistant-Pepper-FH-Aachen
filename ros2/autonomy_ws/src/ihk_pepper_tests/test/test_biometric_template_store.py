"""
Tests fuer biometric_template_store.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 7).
"""
import os
import stat

import pytest

from ihk_pepper_identity.biometric_template_store import BiometricTemplateStore


@pytest.fixture
def store(tmp_path):
    s = BiometricTemplateStore(db_path=str(tmp_path / "biometric_templates.db"))
    yield s
    s.close()


def test_stored_template_can_be_retrieved(store):
    store.store_template("p1", b"\x01\x02\x03\x04")
    assert store.get_template("p1") == b"\x01\x02\x03\x04"


def test_unknown_person_has_no_template(store):
    assert store.get_template("p_ghost") is None
    assert store.has_template("p_ghost") is False


def test_template_is_encrypted_at_rest(tmp_path):
    db_path = str(tmp_path / "biometric_templates.db")
    store = BiometricTemplateStore(db_path=db_path)
    store.store_template("p1", b"GEHEIMES_EMBEDDING_KLARTEXT")
    store.close()

    raw_bytes = open(db_path, "rb").read()
    assert b"GEHEIMES_EMBEDDING_KLARTEXT" not in raw_bytes


def test_database_and_key_file_have_0600_permissions(tmp_path):
    db_path = str(tmp_path / "biometric_templates.db")
    store = BiometricTemplateStore(db_path=db_path)
    store.store_template("p1", b"\x00\x01")
    store.close()

    db_mode = stat.S_IMODE(os.stat(db_path).st_mode)
    key_mode = stat.S_IMODE(os.stat(db_path + ".key").st_mode)
    assert db_mode == 0o600
    assert key_mode == 0o600


def test_update_overwrites_previous_template(store):
    store.store_template("p1", b"\x01")
    store.store_template("p1", b"\x02")
    assert store.get_template("p1") == b"\x02"


def test_delete_template_removes_it(store):
    store.store_template("p1", b"\x01")
    assert store.delete_template("p1") is True
    assert store.get_template("p1") is None


def test_delete_unknown_template_returns_false(store):
    assert store.delete_template("p_ghost") is False


def test_expired_template_is_treated_as_absent(store):
    store.store_template("p1", b"\x01")
    # weit in der Zukunft "jetzt" simulieren -- Aufbewahrungsfrist laengst ueberschritten.
    far_future = __import__("time").time() + 10 * 365 * 86400.0
    assert store.get_template("p1", now=far_future) is None


def test_purge_expired_removes_only_expired_entries(store):
    store.store_template("p1", b"\x01")
    far_future = __import__("time").time() + 10 * 365 * 86400.0
    removed = store.purge_expired(now=far_future)
    assert removed == 1
    assert store.get_template("p1") is None


def test_purge_expired_does_not_remove_valid_entries(store):
    store.store_template("p1", b"\x01")
    removed = store.purge_expired()
    assert removed == 0
    assert store.get_template("p1") == b"\x01"


def test_all_person_ids_lists_stored_templates(store):
    store.store_template("p1", b"\x01")
    store.store_template("p2", b"\x02")
    assert set(store.all_person_ids()) == {"p1", "p2"}


def test_data_persists_after_reopening_store(tmp_path):
    db_path = str(tmp_path / "biometric_templates.db")
    store1 = BiometricTemplateStore(db_path=db_path)
    store1.store_template("p1", b"\x01\x02")
    store1.close()

    store2 = BiometricTemplateStore(db_path=db_path)
    assert store2.get_template("p1") == b"\x01\x02"
    store2.close()


def test_store_template_requires_a_non_empty_person_id(store):
    with pytest.raises(ValueError):
        store.store_template("", b"\x01")


def test_separate_database_from_identity_registry(store):
    # Auftrag Abschnitt 7: "Biometrische Templates gehoeren nicht in die
    # bestehende Identity-Datenbank" -- reiner Dokumentationstest, dass
    # dieses Modul ein VOELLIG eigenes Schema/eigene Datei nutzt (kein
    # Import von identity_registry_db.py).
    import ihk_pepper_identity.biometric_template_store as mod
    assert "identity_registry_db" not in mod.__dict__
