"""
Unit-Tests fuer pepper/qicli.py -- Entwicklungsauftrag 4, AP2.

Kein echter Pepper/SSH-Server noetig: paramiko.SSHClient wird gemockt.
Deckt genau die in AP2 geforderten Verhaltensweisen ab: kein
AutoAddPolicy mehr, verstaendliche Fehler bei unbekanntem/veraendertem
Host-Key, Zeitlimit-Durchsetzung mit Reconnect-Versuch.
"""
import socket
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from qicli import (
    HostKeyChangedError,
    UnknownHostKeyError,
    qicli,
    socket_timeout_errors,
)


def test_connect_uses_reject_policy_not_autoadd():
    """Der Kern der AP2-Vorgabe: kein AutoAddPolicy mehr."""
    client = qicli("10.0.0.1", "nao", "irrelevant")
    with patch("qicli.paramiko.SSHClient") as mock_ssh_client_cls:
        mock_instance = MagicMock()
        mock_ssh_client_cls.return_value = mock_instance
        client.connect()
        mock_instance.set_missing_host_key_policy.assert_called_once()
        policy_arg = mock_instance.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy_arg, paramiko.RejectPolicy)


def test_connect_raises_host_key_changed_error():
    """Ein tatsaechlich abweichender Host-Key (BadHostKeyException) muss
    als HostKeyChangedError mit verstaendlicher Meldung durchgereicht
    werden -- niemals automatisch akzeptiert."""
    client = qicli("10.0.0.1", "nao", "irrelevant")
    with patch("qicli.paramiko.SSHClient") as mock_ssh_client_cls:
        mock_instance = MagicMock()
        mock_ssh_client_cls.return_value = mock_instance
        mock_instance.connect.side_effect = paramiko.BadHostKeyException(
            "10.0.0.1", MagicMock(), MagicMock()
        )
        with pytest.raises(HostKeyChangedError) as excinfo:
            client.connect()
        assert "10.0.0.1" in str(excinfo.value) or "geaendert" in str(excinfo.value)


def test_connect_raises_unknown_host_key_error():
    """Ein Host, dessen Key in keiner known_hosts-Datei steht, muss als
    UnknownHostKeyError mit einer konkreten Handlungsanweisung
    durchgereicht werden -- nicht stillschweigend akzeptiert."""
    client = qicli("10.0.0.1", "nao", "irrelevant")
    with patch("qicli.paramiko.SSHClient") as mock_ssh_client_cls:
        mock_instance = MagicMock()
        mock_ssh_client_cls.return_value = mock_instance
        mock_instance.connect.side_effect = paramiko.SSHException(
            "Server '10.0.0.1' not found in known_hosts"
        )
        with pytest.raises(UnknownHostKeyError):
            client.connect()


def test_exec_command_sets_channel_timeout():
    """Jeder exec_command()-Aufruf muss ein Kanal-Lese-Timeout setzen --
    verhindert einen unbegrenzt haengenden stdout.read()."""
    client = qicli("10.0.0.1", "nao", "irrelevant", timeout=7)
    client.client = MagicMock()
    stdout_mock = MagicMock()
    stdout_mock.read.return_value = b"ok"
    stderr_mock = MagicMock()
    stderr_mock.read.return_value = b""
    client.client.exec_command.return_value = (MagicMock(), stdout_mock, stderr_mock)

    output, error = client.exec_command("echo hi")

    stdout_mock.channel.settimeout.assert_called_once_with(7)
    assert output == "ok"
    assert error == ""


def test_exec_command_timeout_triggers_reconnect_and_retry():
    """Ein Kommando, das das Zeitlimit ueberschreitet, muss NICHT
    unbegrenzt haengen bleiben -- ein Timeout loest einen Reconnect
    plus genau einen Wiederholungsversuch aus (retries=1 Default)."""
    client = qicli("10.0.0.1", "nao", "irrelevant", timeout=1)
    first_client = MagicMock()
    second_client = MagicMock()

    hanging_stdout = MagicMock()
    hanging_stdout.read.side_effect = socket.timeout("timed out")
    first_client.exec_command.return_value = (MagicMock(), hanging_stdout, MagicMock())

    ok_stdout = MagicMock()
    ok_stdout.read.return_value = b"recovered"
    ok_stderr = MagicMock()
    ok_stderr.read.return_value = b""
    second_client.exec_command.return_value = (MagicMock(), ok_stdout, ok_stderr)

    client.client = first_client
    with patch.object(client, "connect", side_effect=lambda: setattr(client, "client", second_client)):
        output, error = client.exec_command("slow_command")

    assert output == "recovered"


def test_socket_timeout_errors_includes_socket_timeout():
    assert socket.timeout in socket_timeout_errors()
