"""
Tests fuer respeaker_transport.py (Entwicklungsauftrag 04-B, AP6).
"""
import pytest

from ihk_pepper_audio.respeaker_transport import (
    MockPcmTransport,
    ReSpeakerTransportError,
    create_transport,
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
    with pytest.raises(ValueError):
        create_transport("ssh_pcm")
