"""
Tests fuer GccPhatDelayAndSumBackend (Entwicklungsauftrag 04-B, AP6,
Abschnitt 6/19). Synthetische, kuenstlich verzoegerte Signale --
KEIN echtes ReSpeaker-Geraet noetig (hwverificationrequired bleibt
bestehen, siehe docs/RESPEAKER_CALIBRATION.md).
"""
import numpy as np
import pytest

from ihk_pepper_audio.directional_audio import GccPhatDelayAndSumBackend
from ihk_pepper_audio.respeaker_transport import RawAudioBlock

# Bewusst grosszuegiger, physikalisch nicht realistischer Mikrofonabstand
# fuer diese Tests -- pruefen nur die ALGORITHMUS-Korrektheit (Vorzeichen/
# Groessenordnung), nicht die tatsaechliche ReSpeaker-Geometrie.
TEST_MIC_SPACING_M = 0.30


def _two_channel_block(ref, delayed, sample_rate_hz=16000):
    frame_count = len(ref)
    interleaved = np.empty(frame_count * 2, dtype=np.int16)
    interleaved[0::2] = ref
    interleaved[1::2] = delayed
    return RawAudioBlock(
        pcm_bytes=interleaved.tobytes(), channel_count=2, sample_rate_hz=sample_rate_hz,
        sample_format="S16_LE", monotonic_timestamp=0.0, sequence=0,
    )


def _white_noise_int16(n, seed=0, amplitude=10000):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) * (amplitude / 4)).clip(-32768, 32767).astype(np.int16)


def test_zero_delay_gives_near_zero_azimuth():
    ref = _white_noise_int16(320)
    block = _two_channel_block(ref, ref)  # identisch = keine Verzoegerung
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    result = backend.process(block)
    assert abs(result.azimuth_rad) < 0.1
    assert result.valid is True


def test_delay_gives_nonzero_azimuth():
    ref = _white_noise_int16(320)
    delayed = np.roll(ref, 4)
    block = _two_channel_block(ref, delayed)
    # min_confidence bewusst niedrig: die Konfidenzformel ist ausdruecklich
    # NICHT kalibriert (siehe Klassendoku), dieser Test prueft nur die
    # Vorzeichen-/Groessenordnungskorrektheit der Azimut-Schaetzung selbst,
    # nicht die (spaeter am realen Geraet zu kalibrierende) Schwelle.
    backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M, min_confidence=0.05)
    result = backend.process(block)
    assert result.vad_active is True
    assert result.doa_confidence > 0.0
    assert abs(result.azimuth_rad) > 0.01
    assert result.valid is True


def test_opposite_delay_gives_opposite_sign():
    ref = _white_noise_int16(320)
    delayed_pos = np.roll(ref, 4)
    delayed_neg = np.roll(ref, -4)
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    az_pos = backend.process(_two_channel_block(ref, delayed_pos)).azimuth_rad
    az_neg = backend.process(_two_channel_block(ref, delayed_neg)).azimuth_rad
    assert (az_pos > 0) != (az_neg > 0)


def test_silence_is_not_vad_active_and_invalid():
    ref = np.zeros(320, dtype=np.int16)
    block = _two_channel_block(ref, ref)
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    result = backend.process(block)
    assert result.vad_active is False
    assert result.valid is False


def test_channel_count_mismatch_returns_invalid():
    ref = _white_noise_int16(320)
    block = _two_channel_block(ref, ref)  # nur 2 Kanaele
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 5], mic_spacing_m=TEST_MIC_SPACING_M)
    result = backend.process(block)
    assert result.valid is False
    assert result.reason == "channel_count_mismatch"


def test_requires_at_least_two_microphone_channels():
    with pytest.raises(ValueError):
        GccPhatDelayAndSumBackend(microphone_channels=[0])


def test_mono_output_length_matches_frame_count():
    ref = _white_noise_int16(320)
    block = _two_channel_block(ref, ref)
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    result = backend.process(block)
    assert len(result.mono_pcm) == 320 * 2  # int16 = 2 bytes/sample


def test_confidence_is_bounded_between_zero_and_one():
    ref = _white_noise_int16(320)
    block = _two_channel_block(ref, ref)
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    result = backend.process(block)
    assert 0.0 <= result.doa_confidence <= 1.0


def test_smoothing_window_converges_across_identical_blocks():
    ref = _white_noise_int16(320)
    delayed = np.roll(ref, 4)
    block = _two_channel_block(ref, delayed)
    backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M, smoothing_window=3)
    backend.process(block)
    second = backend.process(block).azimuth_rad
    third = backend.process(block).azimuth_rad
    assert abs(second - third) < 1e-6
