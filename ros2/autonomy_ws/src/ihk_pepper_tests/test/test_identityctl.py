"""
Tests fuer identityctl.py (Entwicklungsauftrag 04-B, AP7.1, Abschnitt
7). status/list/revoke/delete/validate-store laufen direkt gegen
temporaere Speicherdateien, kein ROS2 noetig (gleiches Prinzip wie
test_peoplectl.py, falls vorhanden). enroll wird hier NICHT end-to-end
getestet (braucht einen laufenden face_identity_node) -- nur die
Parser-Verdrahtung.
"""
import numpy as np
import pytest

from ihk_pepper_identity import identityctl
from ihk_pepper_identity.biometric_template_store import BiometricTemplateStore
from ihk_pepper_person_memory.identity_registry_db import ConsentStatus, IdentityRegistryStore


def _args(tmp_path, command, **overrides):
    parser = identityctl.build_parser()
    argv = [
        "--identity-db-path", str(tmp_path / "identity.db"),
        "--biometric-db-path", str(tmp_path / "biometric.db"),
        command,
    ]
    for key, value in overrides.items():
        flag = "--" + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        elif value is not False:
            argv += [flag, str(value)]
    return parser.parse_args(argv)


def _registry(tmp_path):
    return IdentityRegistryStore(str(tmp_path / "identity.db"))


def _store(tmp_path):
    # KEIN eigener key_path -- identityctl.py::_open_biometric_store()
    # oeffnet den Store ebenfalls ohne expliziten key_path (Default:
    # neben der DB-Datei abgeleitet), Tests muessen denselben Schluessel
    # treffen wie das getestete Kommando selbst.
    return BiometricTemplateStore(db_path=str(tmp_path / "biometric.db"))


def test_status_reports_zero_counts_on_fresh_stores(tmp_path, capsys):
    args = _args(tmp_path, "status")
    rc = identityctl.cmd_status(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "registrierte_personen: 0" in out
    assert "gespeicherte_templates: 0" in out


def test_list_reports_no_templates_when_empty(tmp_path, capsys):
    args = _args(tmp_path, "list")
    rc = identityctl.cmd_list(args)
    assert rc == 0
    assert "Keine biometrischen Vorlagen" in capsys.readouterr().out


def test_list_shows_consent_status_for_each_template(tmp_path, capsys):
    registry = _registry(tmp_path)
    registry.create_or_touch("p1")
    registry.set_consent("p1", ConsentStatus.GRANTED.value, reason="test")
    registry.close()

    store = _store(tmp_path)
    store.store_template("p1", np.array([1.0], dtype=np.float32).tobytes())
    store.close()

    args = _args(tmp_path, "list")
    rc = identityctl.cmd_list(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "p1" in out
    assert "granted" in out


def test_revoke_rejects_unknown_person(tmp_path, capsys):
    args = _args(tmp_path, "revoke", person_id="ghost", reason="test")
    rc = identityctl.cmd_revoke(args)
    assert rc == 1


def test_revoke_sets_consent_to_withdrawn_but_keeps_the_template(tmp_path):
    registry = _registry(tmp_path)
    registry.create_or_touch("p1")
    registry.set_consent("p1", ConsentStatus.GRANTED.value, reason="test")
    registry.close()

    store = _store(tmp_path)
    embedding = np.array([1.0], dtype=np.float32).tobytes()
    store.store_template("p1", embedding)
    store.close()

    args = _args(tmp_path, "revoke", person_id="p1", reason="widerruf")
    rc = identityctl.cmd_revoke(args)
    assert rc == 0

    registry = _registry(tmp_path)
    record = registry.lookup("p1")
    assert record.consent_status == ConsentStatus.WITHDRAWN.value
    registry.close()

    store = _store(tmp_path)
    assert store.has_template("p1") is True  # Template bleibt bestehen
    store.close()


def test_delete_without_yes_is_refused(tmp_path):
    args = _args(tmp_path, "delete", person_id="p1")
    rc = identityctl.cmd_delete(args)
    assert rc == 1


def test_delete_removes_the_template(tmp_path):
    store = _store(tmp_path)
    store.store_template("p1", np.array([1.0], dtype=np.float32).tobytes())
    store.close()

    args = _args(tmp_path, "delete", person_id="p1", yes=True)
    rc = identityctl.cmd_delete(args)
    assert rc == 0

    store = _store(tmp_path)
    assert store.has_template("p1") is False
    store.close()


def test_delete_unknown_template_is_reported(tmp_path):
    args = _args(tmp_path, "delete", person_id="ghost", yes=True)
    rc = identityctl.cmd_delete(args)
    assert rc == 1


def test_validate_store_passes_on_a_healthy_store(tmp_path, capsys):
    store = _store(tmp_path)
    store.store_template("p1", np.array([1.0], dtype=np.float32).tobytes())
    store.close()

    args = _args(tmp_path, "validate-store")
    rc = identityctl.cmd_validate_store(args)
    assert rc == 0
    assert "1/1" in capsys.readouterr().out


def test_validate_store_reports_empty_store(tmp_path, capsys):
    args = _args(tmp_path, "validate-store")
    rc = identityctl.cmd_validate_store(args)
    assert rc == 0
    assert "Keine Vorlagen" in capsys.readouterr().out


def test_enroll_requires_person_id_and_reason(tmp_path):
    parser = identityctl.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["enroll"])


def test_enroll_parses_with_required_arguments(tmp_path):
    args = _args(tmp_path, "enroll", person_id="p1", reason="test")
    assert args.person_id == "p1"
    assert args.reason == "test"
    assert args.timeout_s == 20.0
    assert args.func is identityctl.cmd_enroll
