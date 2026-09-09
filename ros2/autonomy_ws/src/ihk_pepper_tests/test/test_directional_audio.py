"""
Tests fuer directional_audio.py (Entwicklungsauftrag 04-B, AP6).
"""
import struct

import pytest

from ihk_pepper_audio.directional_audio import (
    DirectionalAudioResult,
    MockDirectionalBackend,
    PassthroughTestBackend,
    ReSpeakerVendorBackend,
)
from ihk_pepper_audio.respeaker_transport import RawAudioBlock


def _make_block(channel_samples: list, channel_count: int) -> RawAudioBlock:
    """channel_samples: Liste von Frames, jedes Frame eine Liste mit
    channel_count int16-Werten."""
    flat = [s for frame in channel_samples for s in frame]
    pcm = struct.pack(f"<{len(flat)}h", *flat)
    return RawAudioBlock(
        pcm_bytes=pcm, channel_count=channel_count, sample_rate_hz=16000,
        sample_format="S16_LE", monotonic_timestamp=0.0, sequence=0,
    )


def test_passthrough_extracts_first_channel_only():
    # 2 Kanaele, 3 Frames: Kanal 0 = [100, 200, 300], Kanal 1 = [999, 999, 999]
    block = _make_block([[100, 999], [200, 999], [300, 999]], channel_count=2)
    backend = PassthroughTestBackend()
    result = backend.process(block)
    mono_samples = struct.unpack("<3h", result.mono_pcm)
    assert mono_samples == (100, 200, 300)


def test_passthrough_always_reports_invalid_direction():
    block = _make_block([[0, 0]], channel_count=2)
    result = PassthroughTestBackend().process(block)
    assert result.valid is False
    assert result.reason == "passthrough_backend_no_direction_estimate"
    assert result.azimuth_rad == 0.0
    assert result.doa_confidence == 0.0


def test_passthrough_vad_active_above_threshold():
    loud_frame = [30000, 0]
    block = _make_block([loud_frame] * 10, channel_count=2)
    backend = PassthroughTestBackend(vad_threshold_dbfs=-45.0)
    result = backend.process(block)
    assert result.vad_active is True


def test_passthrough_vad_inactive_on_silence():
    block = _make_block([[0, 0]] * 10, channel_count=2)
    backend = PassthroughTestBackend()
    result = backend.process(block)
    assert result.vad_active is False


def test_passthrough_handles_empty_block_without_crashing():
    block = RawAudioBlock(pcm_bytes=b"", channel_count=2, sample_rate_hz=16000,
                           sample_format="S16_LE", monotonic_timestamp=0.0, sequence=0)
    result = PassthroughTestBackend().process(block)
    assert result.valid is False
    assert result.mono_pcm == b""


def test_mock_directional_backend_with_fixed_result():
    fixed = DirectionalAudioResult(
        mono_pcm=b"", azimuth_rad=0.5, doa_confidence=0.9, vad_active=True,
        input_rms_dbfs=-10.0, output_rms_dbfs=-8.0, valid=True, reason="",
    )
    backend = MockDirectionalBackend(fixed_result=fixed)
    block = _make_block([[0, 0]], channel_count=2)
    assert backend.process(block) is fixed


def test_mock_directional_backend_with_result_fn():
    def result_fn(block):
        return DirectionalAudioResult(
            mono_pcm=block.pcm_bytes, azimuth_rad=1.0, doa_confidence=0.5,
            vad_active=False, input_rms_dbfs=-30.0, output_rms_dbfs=-30.0,
            valid=True,
        )

    backend = MockDirectionalBackend(result_fn=result_fn)
    block = _make_block([[1, 2]], channel_count=2)
    result = backend.process(block)
    assert result.azimuth_rad == 1.0


def test_mock_directional_backend_requires_one_of_result_fn_or_fixed_result():
    with pytest.raises(ValueError):
        MockDirectionalBackend()


def test_respeaker_vendor_backend_raises_not_implemented():
    block = _make_block([[0, 0]], channel_count=2)
    with pytest.raises(NotImplementedError):
        ReSpeakerVendorBackend().process(block)
