"""
Tests fuer respeaker_transport.py (Entwicklungsauftrag 04-B, AP6).
"""
import pytest

from ihk_pepper_audio.respeaker_transport import (
    LocalAlsaTransport,
    MockPcmTransport,
    NetworkPcmTransport,
    ReSpeakerTransportError,
    SshPcmTransport,
    create_transport,
    resolve_alsa_device_index,
)


def test_read_block_before_connect_raises():
    transport = MockPcmTransport()
    with pytest.raises(ReSpeakerTransportError):
        transport.read_block()


def test_connect_then_read_block_returns_expected_shape():
    transport = MockPcmTransport(channel_count=8, sample_rate_hz=16000, block_duration_ms=20)
    transport.connect()
    block = transport.read_block()
    frames = int(16000 * 0.020)
    assert block.channel_count == 8
    assert block.sample_rate_hz == 16000
    assert len(block.pcm_bytes) == frames * 8 * 2  # int16 = 2 bytes/sample
    assert block.sequence == 0


def test_sequence_increases_monotonically():
    transport = MockPcmTransport()
    transport.connect()
    seqs = [transport.read_block().sequence for _ in range(5)]
    assert seqs == [0, 1, 2, 3, 4]


def test_monotonic_timestamp_uses_injected_now_fn():
    times = iter([100.0, 100.02, 100.04])
    transport = MockPcmTransport(now_fn=lambda: next(times))
    transport.connect()
    assert transport.read_block().monotonic_timestamp == 100.0
    assert transport.read_block().monotonic_timestamp == 100.02


def test_fail_after_simulates_disconnect():
    transport = MockPcmTransport(fail_after=2)
    transport.connect()
    transport.read_block()
    transport.read_block()
    with pytest.raises(ReSpeakerTransportError):
        transport.read_block()


def test_block_fn_supplies_custom_pcm_content():
    def block_fn(sequence):
        return bytes([sequence % 256]) * 16

    transport = MockPcmTransport(channel_count=2, sample_rate_hz=16000, block_duration_ms=20,
                                  block_fn=block_fn)
    transport.connect()
    block = transport.read_block()
    assert block.pcm_bytes == bytes([0]) * 16


def test_close_then_read_block_raises():
    transport = MockPcmTransport()
    transport.connect()
    transport.close()
    assert transport.is_connected() is False
    with pytest.raises(ReSpeakerTransportError):
        transport.read_block()


def test_is_connected_reflects_state():
    transport = MockPcmTransport()
    assert transport.is_connected() is False
    transport.connect()
    assert transport.is_connected() is True


def test_create_transport_mock():
    transport = create_transport("mock", channel_count=6)
    assert isinstance(transport, MockPcmTransport)
    assert transport.channel_count == 6


def test_create_transport_unknown_kind_raises():
    # "ssh_pcm" ist seit Commit 2 implementiert (siehe
    # test_create_transport_ssh_pcm/local_alsa/network_pcm unten) --
    # hier ein wirklich unbekannter Transportname.
    with pytest.raises(ValueError):
        create_transport("totally_unknown_transport_kind")


def test_create_transport_local_alsa():
    transport = create_transport("local_alsa", device_name="my-card")
    assert isinstance(transport, LocalAlsaTransport)
    assert transport.device_name == "my-card"


def test_create_transport_ssh_pcm():
    transport = create_transport("ssh_pcm", host="10.0.0.5", username="pi", password="pw")
    assert isinstance(transport, SshPcmTransport)
    assert transport.host == "10.0.0.5"


def test_create_transport_network_pcm():
    transport = create_transport("network_pcm", host="10.0.0.5", port=9000)
    assert isinstance(transport, NetworkPcmTransport)
    assert transport.port == 9000


def test_resolve_alsa_device_index_finds_matching_device():
    devices = [
        {"name": "HDA Intel PCH", "max_input_channels": 2},
        {"name": "seeed-8mic-voicecard", "max_input_channels": 8},
    ]
    assert resolve_alsa_device_index(devices, "seeed-8mic-voicecard") == 1


def test_resolve_alsa_device_index_returns_none_when_not_found():
    devices = [{"name": "HDA Intel PCH", "max_input_channels": 2}]
    assert resolve_alsa_device_index(devices, "seeed-8mic-voicecard") is None


def test_resolve_alsa_device_index_ignores_output_only_devices():
    devices = [{"name": "seeed-8mic-voicecard", "max_input_channels": 0}]
    assert resolve_alsa_device_index(devices, "seeed-8mic-voicecard") is None


def test_local_alsa_transport_connect_raises_when_device_not_found(monkeypatch):
    import sys
    import types

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [{"name": "HDA Intel PCH", "max_input_channels": 2}]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    transport = LocalAlsaTransport(device_name="seeed-8mic-voicecard")
    with pytest.raises(ReSpeakerTransportError):
        transport.connect()


def test_ssh_pcm_transport_read_block_uses_hardened_connect(monkeypatch):
    from unittest.mock import MagicMock

    import ihk_pepper_audio.respeaker_transport as respeaker_transport_module

    frames = int(16000 * 0.020)
    pcm = b"\x00\x00" * frames * 8

    fake_stdout = MagicMock()
    fake_stdout.read.return_value = pcm
    mock_client = MagicMock()
    mock_client.exec_command.return_value = (MagicMock(), fake_stdout, MagicMock())

    monkeypatch.setattr(respeaker_transport_module, "connect_hardened", lambda *a, **kw: None)
    monkeypatch.setattr("paramiko.SSHClient", lambda: mock_client)

    transport = SshPcmTransport(host="10.0.0.5", username="pi", password="pw", channel_count=8)
    transport.connect()
    block = transport.read_block()
    assert block.channel_count == 8
    assert len(block.pcm_bytes) == len(pcm)


def test_network_pcm_transport_read_block_reads_exact_bytes(monkeypatch):
    from unittest.mock import MagicMock

    frames = int(16000 * 0.020)
    expected_bytes = frames * 8 * 2
    fake_socket = MagicMock()
    fake_socket.recv.return_value = b"\x00" * expected_bytes

    import socket as socket_module
    monkeypatch.setattr(socket_module, "create_connection", lambda *a, **kw: fake_socket)

    transport = NetworkPcmTransport(host="10.0.0.5", port=9000, channel_count=8)
    transport.connect()
    block = transport.read_block()
    assert len(block.pcm_bytes) == expected_bytes


def test_network_pcm_transport_raises_on_connection_closed(monkeypatch):
    from unittest.mock import MagicMock

    fake_socket = MagicMock()
    fake_socket.recv.return_value = b""  # Verbindung beendet

    import socket as socket_module
    monkeypatch.setattr(socket_module, "create_connection", lambda *a, **kw: fake_socket)

    transport = NetworkPcmTransport(host="10.0.0.5", port=9000, channel_count=8)
    transport.connect()
    with pytest.raises(ReSpeakerTransportError):
        transport.read_block()
