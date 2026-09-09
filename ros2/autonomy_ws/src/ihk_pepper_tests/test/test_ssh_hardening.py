"""
Tests fuer ssh_hardening.py (Entwicklungsauftrag 04-B, AP6). Kein echter
SSH-Server noetig: paramiko.SSHClient wird als MagicMock uebergeben,
dieselbe Vorgehensweise wie apps/web/pepper/test_qicli.py.
"""
from unittest.mock import MagicMock

import paramiko
import pytest

from ihk_pepper_audio.ssh_hardening import (
    HostKeyChangedError,
    UnknownHostKeyError,
    connect_hardened,
    known_hosts_paths,
)


def test_known_hosts_paths_uses_env_var_override(monkeypatch):
    monkeypatch.setenv("TEST_KNOWN_HOSTS_VAR", "/tmp/custom_known_hosts")
    system_path, project_path = known_hosts_paths("TEST_KNOWN_HOSTS_VAR", "/default/known_hosts")
    assert project_path == "/tmp/custom_known_hosts"
    assert system_path.endswith("known_hosts")


def test_known_hosts_paths_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("TEST_KNOWN_HOSTS_VAR", raising=False)
    _, project_path = known_hosts_paths("TEST_KNOWN_HOSTS_VAR", "/default/known_hosts")
    assert project_path == "/default/known_hosts"


def test_connect_hardened_sets_reject_policy_not_autoadd():
    client = MagicMock()
    connect_hardened(client, "1.2.3.4", "user", "pw")
    policy_arg = client.set_missing_host_key_policy.call_args[0][0]
    assert isinstance(policy_arg, paramiko.RejectPolicy)


def test_connect_hardened_raises_host_key_changed_on_bad_host_key():
    client = MagicMock()
    client.connect.side_effect = paramiko.BadHostKeyException(
        "1.2.3.4", MagicMock(), MagicMock())
    with pytest.raises(HostKeyChangedError):
        connect_hardened(client, "1.2.3.4", "user", "pw")


def test_connect_hardened_raises_unknown_host_key_when_not_in_known_hosts():
    client = MagicMock()
    client.connect.side_effect = paramiko.SSHException(
        "Server '1.2.3.4' not found in known_hosts")
    with pytest.raises(UnknownHostKeyError):
        connect_hardened(client, "1.2.3.4", "user", "pw")


def test_connect_hardened_falls_back_to_keyboard_interactive():
    client = MagicMock()
    client.connect.side_effect = paramiko.ssh_exception.BadAuthenticationType(
        "password not allowed", ["publickey", "keyboard-interactive"])
    connect_hardened(client, "1.2.3.4", "user", "pw")
    client.get_transport.return_value.auth_interactive.assert_called_once()


def test_connect_hardened_reraises_unrelated_ssh_exceptions():
    client = MagicMock()
    client.connect.side_effect = paramiko.SSHException("etwas ganz anderes ist kaputt")
    with pytest.raises(paramiko.SSHException):
        connect_hardened(client, "1.2.3.4", "user", "pw")
