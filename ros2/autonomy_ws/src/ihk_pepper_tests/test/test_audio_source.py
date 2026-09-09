"""
Tests fuer audio_source.py (Entwicklungsauftrag 04-B, AP6):
ReSpeakerCoreV2Source, build_respeaker_transport_from_config() und die
gehaertete PepperPulseAudioSource.connect() (vorher AutoAddPolicy --
bestaetigter Fund, siehe docs/RESPEAKER_TRANSPORT.md).
"""
from unittest.mock import MagicMock

import paramiko
import pytest

from ihk_pepper_audio.audio_source import (
    CHUNK_BYTES,
    AudioSourceError,
    PepperPulseAudioSource,
    ReSpeakerCoreV2Source,
    build_respeaker_transport_from_config,
)
from ihk_pepper_audio.directional_audio import DirectionalAudioResult, PassthroughTestBackend
from ihk_pepper_audio.respeaker_transport import (
    LocalAlsaTransport,
    MockPcmTransport,
    NetworkPcmTransport,
    RawAudioBlock,
    SshPcmTransport,
)


def _silence_block(channel_count=8, sample_rate_hz=16000, block_duration_ms=20,
                    sequence=0, monotonic_timestamp=0.0):
    frames = int(sample_rate_hz * (block_duration_ms / 1000.0))
    return RawAudioBlock(
        pcm_bytes=b"\x00\x00" * (frames * channel_count), channel_count=channel_count,
        sample_rate_hz=sample_rate_hz, sample_format="S16_LE",
        monotonic_timestamp=monotonic_timestamp, sequence=sequence,
    )


class _FakeTransport:
    """Liefert eine vorgegebene Liste von RawAudioBlock/Exceptions,
    fuer Tests, die exakte Sequenzluecken/Fehler brauchen (MockPcmTransport
    selbst erzeugt immer eine lueckenlose Sequenz)."""

    def __init__(self, items):
        self._items = list(items)
        self.connected = False
        self.closed = False

    def connect(self):
        self.connected = True

    def read_block(self):
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True

    def is_connected(self):
        return self.connected and not self.closed


# ---- ReSpeakerCoreV2Source ----

def test_read_chunk_returns_exactly_chunk_bytes():
    transport = MockPcmTransport(channel_count=8, sample_rate_hz=16000, block_duration_ms=20)
    source = ReSpeakerCoreV2Source(transport, directional_backend=PassthroughTestBackend())
    source.connect()
    chunk = source.read_chunk()
    assert len(chunk) == CHUNK_BYTES


def test_stale_frames_are_dropped_and_counted():
    # Der Transport stempelt jeden Block mit now=10.0, die Quelle prueft
    # das Alter aber gegen now=11.0 (1000ms "spaeter") -- weit ueber
    # maximum_frame_age_ms=50.0, jeder Block ist also sofort veraltet.
    transport = MockPcmTransport(channel_count=8, now_fn=lambda: 10.0)
    source = ReSpeakerCoreV2Source(
        transport, directional_backend=PassthroughTestBackend(),
        maximum_frame_age_ms=50.0, now_fn=lambda: 11.0,
    )
    source.connect()
    for _ in range(3):
        source._ingest_one_block()
    assert source.dropped_stale_frames == 3
    assert len(source._mono_buffer) == 0  # kein veralteter Frame kam in den Puffer


def test_expected_channel_count_mismatch_raises():
    transport = _FakeTransport([_silence_block(channel_count=6)])
    source = ReSpeakerCoreV2Source(transport, expected_channel_count=8)
    source.connect()
    with pytest.raises(AudioSourceError):
        source.read_chunk()


def test_packet_loss_detected_via_sequence_gap():
    transport = _FakeTransport([
        _silence_block(sequence=0),
        _silence_block(sequence=1),
        _silence_block(sequence=5),  # Luecke: 2,3,4 fehlen
    ])
    source = ReSpeakerCoreV2Source(transport)
    source.connect()
    for _ in range(3):
        source._ingest_one_block()
    assert source.packet_loss_count == 1


def test_buffer_overflow_drops_oldest_and_counts():
    # Sehr kleiner Maximalpuffer -- jeder Block ist bereits groesser.
    transport = MockPcmTransport(channel_count=1, sample_rate_hz=16000, block_duration_ms=100)
    source = ReSpeakerCoreV2Source(
        transport, directional_backend=PassthroughTestBackend(), maximum_buffer_ms=10.0)
    source.connect()
    source._ingest_one_block()
    source._ingest_one_block()
    assert source.buffer_overflow_count >= 1
    assert len(source._mono_buffer) <= source._max_buffer_bytes()


def test_transport_error_propagates_as_audio_source_error():
    transport = MockPcmTransport(fail_after=0)
    source = ReSpeakerCoreV2Source(transport)
    source.connect()
    with pytest.raises(AudioSourceError):
        source.read_chunk()


def test_close_delegates_to_transport():
    transport = _FakeTransport([])
    source = ReSpeakerCoreV2Source(transport)
    source.connect()
    source.close()
    assert transport.closed is True


def test_diagnostics_reflect_last_backend_result():
    fixed = DirectionalAudioResult(
        mono_pcm=b"\x00\x00" * 320, azimuth_rad=0.3, doa_confidence=0.8,
        vad_active=True, input_rms_dbfs=-20.0, output_rms_dbfs=-15.0,
        valid=True, reason="ok",
    )

    class _FixedBackend:
        def process(self, block):
            return fixed

    transport = MockPcmTransport(channel_count=8)
    source = ReSpeakerCoreV2Source(transport, directional_backend=_FixedBackend())
    source.connect()
    source._ingest_one_block()
    assert source.last_azimuth_rad == 0.3
    assert source.last_doa_confidence == 0.8
    assert source.last_vad_active is True
    assert source.last_direction_valid is True
    assert source.last_backend_reason == "ok"


def test_no_unbounded_growth_across_many_blocks():
    transport = MockPcmTransport(channel_count=1, sample_rate_hz=16000, block_duration_ms=20)
    source = ReSpeakerCoreV2Source(transport, maximum_buffer_ms=200.0)
    source.connect()
    for _ in range(200):
        source._ingest_one_block()
    assert len(source._mono_buffer) <= source._max_buffer_bytes()


# ---- build_respeaker_transport_from_config ----

def test_build_transport_from_config_mock():
    transport = build_respeaker_transport_from_config({"transport": "mock", "input_channels": 6})
    assert isinstance(transport, MockPcmTransport)
    assert transport.channel_count == 6


def test_build_transport_from_config_local_alsa():
    transport = build_respeaker_transport_from_config({
        "transport": "local_alsa", "device_name": "my-card", "input_channels": 8,
    })
    assert isinstance(transport, LocalAlsaTransport)
    assert transport.device_name == "my-card"


def test_build_transport_from_config_ssh_pcm():
    transport = build_respeaker_transport_from_config({
        "transport": "ssh_pcm", "respeaker_host": "10.0.0.5", "respeaker_user": "pi",
        "respeaker_password": "secret", "input_channels": 8,
    })
    assert isinstance(transport, SshPcmTransport)
    assert transport.host == "10.0.0.5"
    assert transport.username == "pi"


def test_build_transport_from_config_network_pcm():
    transport = build_respeaker_transport_from_config({
        "transport": "network_pcm", "respeaker_host": "10.0.0.5", "respeaker_port": 9000,
    })
    assert isinstance(transport, NetworkPcmTransport)
    assert transport.port == 9000


def test_build_transport_from_config_defaults_to_mock():
    transport = build_respeaker_transport_from_config({})
    assert isinstance(transport, MockPcmTransport)


# ---- PepperPulseAudioSource: gehaertete SSH-Verbindung ----

def test_pepper_pulseaudio_connect_uses_reject_policy(monkeypatch):
    mock_client = MagicMock()
    mock_client.exec_command.return_value = (MagicMock(), MagicMock(), MagicMock())
    # PepperPulseAudioSource.connect() macht ein lokales "import paramiko"
    # (dieselbe Modulinstanz wie ueberall) -- das Patchen des globalen
    # paramiko.SSHClient wirkt daher genauso, wie ein modulqualifiziertes
    # Patchen es wuerde, ohne dass audio_source.py einen eigenen
    # Top-Level-paramiko-Import braeuchte.
    monkeypatch.setattr(paramiko, "SSHClient", lambda: mock_client)
    source = PepperPulseAudioSource("host", "user", "pw")
    source.connect()
    policy_arg = mock_client.set_missing_host_key_policy.call_args[0][0]
    assert isinstance(policy_arg, paramiko.RejectPolicy)


def test_pepper_pulseaudio_connect_raises_audio_source_error_on_host_key_change(monkeypatch):
    mock_client = MagicMock()
    mock_client.connect.side_effect = paramiko.BadHostKeyException(
        "host", MagicMock(), MagicMock())
    monkeypatch.setattr(paramiko, "SSHClient", lambda: mock_client)
    source = PepperPulseAudioSource("host", "user", "pw")
    with pytest.raises(AudioSourceError):
        source.connect()
