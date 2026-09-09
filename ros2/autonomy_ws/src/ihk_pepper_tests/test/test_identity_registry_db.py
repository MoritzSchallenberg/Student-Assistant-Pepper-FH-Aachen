import glob
import os

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


# ---- Rollen (Entwicklungsauftrag 04-B, AP7, Abschnitt 6) ----

def test_new_identity_defaults_to_student_role(store):
    record = store.create_or_touch("p1", reason="seen")
    assert record.role == "student"
    assert record.role_assigned_at_iso is None
    assert record.role_assigned_by is None


def test_set_role_updates_record_and_audit_metadata(store):
    store.create_or_touch("p1", reason="seen")
    record = store.set_role("p1", "employee", assigned_by="admin_console", reason="hired")
    assert record.role == "employee"
    assert record.role_assigned_by == "admin_console"
    assert record.role_assigned_at_iso is not None


def test_set_role_unknown_person_rejected(store):
    with pytest.raises(KeyError):
        store.set_role("p_ghost", "employee", assigned_by="admin", reason="test")


def test_set_role_invalid_role_rejected(store):
    store.create_or_touch("p1", reason="seen")
    with pytest.raises(ValueError):
        store.set_role("p1", "superadmin", assigned_by="admin", reason="test")


def test_revoke_role_resets_to_student(store):
    store.create_or_touch("p1", reason="seen")
    store.set_role("p1", "admin", assigned_by="admin_console", reason="promoted")
    record = store.revoke_role("p1", assigned_by="admin_console", reason="left_company")
    assert record.role == "student"


def test_get_effective_role_returns_student_for_unknown_person(store):
    assert store.get_effective_role("p_ghost") == "student"


def test_get_effective_role_returns_current_role_when_valid(store):
    store.create_or_touch("p1", reason="seen")
    store.set_role("p1", "employee", assigned_by="admin", reason="hired")
    assert store.get_effective_role("p1", now=1000.0) == "employee"


def test_get_effective_role_falls_back_to_student_when_expired(store):
    store.create_or_touch("p1", reason="seen")
    store.set_role("p1", "employee", assigned_by="admin", reason="temp", valid_until_ts=500.0)
    assert store.get_effective_role("p1", now=1000.0) == "student"


def test_role_changes_are_audited(store):
    store.create_or_touch("p1", reason="seen")
    store.set_role("p1", "admin", assigned_by="admin_console", reason="promoted")
    rows = store.conn.execute(
        "SELECT action, reason FROM identity_audit_log WHERE person_id='p1'").fetchall()
    actions = [r[0] for r in rows]
    assert "set_role:admin" in actions


def test_no_ros2_service_style_method_exists_for_setting_roles(store):
    # Auftrag Abschnitt 6: "Rollenaenderungen duerfen nicht ueber ein
    # frei erreichbares ROS2-Service moeglich sein" -- diese Klasse hat
    # bewusst NUR set_role/revoke_role (aufgerufen von peoplectl), keine
    # ROS2-Service-Registrierung. Dieser Test dokumentiert die Absicht:
    # person_memory_node.py (der ROS-Wrapper) darf set_role/revoke_role
    # NIE als Service exponieren (separat gegengeprueft in
    # test_person_memory_node.py).
    assert hasattr(store, "set_role")
    assert hasattr(store, "revoke_role")


# ---- Migration (Entwicklungsauftrag 04-B, AP7, Abschnitt 6) ----

def test_fresh_database_has_role_columns_without_creating_a_backup(tmp_path):
    db_path = str(tmp_path / "identity.db")
    store = IdentityRegistryStore(db_path)
    store.create_or_touch("p1", reason="seen")
    store.close()
    backups = glob.glob(db_path + ".pre-role-migration-*.bak")
    assert backups == []  # nichts zu schuetzen bei einer frischen, leeren Datenbank


def test_migrating_an_existing_populated_database_creates_a_backup_first(tmp_path):
    db_path = str(tmp_path / "identity.db")

    # Schritt 1: eine Datenbank OHNE die neuen Rollen-Spalten simulieren
    # (alter Schemastand vor AP7) -- direkt per sqlite3, nicht ueber
    # IdentityRegistryStore (das wuerde die Migration sofort ausfuehren).
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE identities (
            person_id TEXT PRIMARY KEY,
            display_name TEXT,
            consent_status TEXT NOT NULL DEFAULT 'not_asked',
            created_at REAL NOT NULL,
            last_seen_at REAL,
            last_recognition_confidence REAL NOT NULL DEFAULT 0.0,
            retention_deadline REAL
        );
        CREATE TABLE identity_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT NOT NULL, action TEXT NOT NULL,
            reason TEXT NOT NULL, timestamp REAL NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO identities (person_id, created_at, last_recognition_confidence) "
        "VALUES ('p1', 0.0, 0.0)")
    conn.commit()
    conn.close()

    # Schritt 2: oeffnen ueber IdentityRegistryStore loest die Migration aus.
    store = IdentityRegistryStore(db_path)
    record = store.lookup("p1")
    assert record.role == "student"  # Migrations-Default fuer bestehende Zeilen
    store.close()

    backups = glob.glob(db_path + ".pre-role-migration-*.bak")
    assert len(backups) == 1
    # Das Backup enthaelt noch den ALTEN Schemastand (keine role-Spalte).
    backup_conn = sqlite3.connect(backups[0])
    cols = {row[1] for row in backup_conn.execute("PRAGMA table_info(identities)").fetchall()}
    backup_conn.close()
    assert "role" not in cols


def test_reopening_an_already_migrated_database_creates_no_further_backup(tmp_path):
    db_path = str(tmp_path / "identity.db")
    store1 = IdentityRegistryStore(db_path)
    store1.create_or_touch("p1", reason="seen")
    store1.close()

    store2 = IdentityRegistryStore(db_path)  # bereits migriert -- kein erneutes Backup
    store2.close()

    backups = glob.glob(db_path + ".pre-role-migration-*.bak")
    assert backups == []
