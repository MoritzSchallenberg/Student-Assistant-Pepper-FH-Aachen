"""
Tests fuer GccPhatDelayAndSumBackend (Entwicklungsauftrag 04-B, AP6,
Abschnitt 6/19). Synthetische, kuenstlich verzoegerte Signale --
KEIN echtes ReSpeaker-Geraet noetig (hwverificationrequired bleibt
bestehen, siehe docs/RESPEAKER_CALIBRATION.md).
"""
import math

import numpy as np
import pytest

from ihk_pepper_audio.directional_audio import GccPhatDelayAndSumBackend, MicrophoneGeometry
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


def test_provides_unambiguous_direction_is_false():
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13: Zwei-Mikrofon-
    # GCC-PHAT ist front/back-mehrdeutig, darf NIE als sichere 360-Grad-
    # Quelle fuer eine Kopfbewegung gelten.
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    assert backend.provides_unambiguous_direction is False


# ---- SteerableDirectionalAudioBackend (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5) ----

_STEER_SAMPLE_RATE_HZ = 16000
_STEER_GEOMETRY = [
    MicrophoneGeometry(channel=0, x_m=0.0, y_m=0.0),
    MicrophoneGeometry(channel=1, x_m=0.0, y_m=0.05),
    MicrophoneGeometry(channel=2, x_m=0.0, y_m=-0.05),
]
_STEER_TEST_AZIMUTH_RAD = math.radians(30.0)


def _multi_channel_block(channel_signals, sample_rate_hz=_STEER_SAMPLE_RATE_HZ):
    frame_count = len(channel_signals[0])
    channel_count = len(channel_signals)
    interleaved = np.empty(frame_count * channel_count, dtype=np.int16)
    for c, sig in enumerate(channel_signals):
        interleaved[c::channel_count] = sig
    return RawAudioBlock(
        pcm_bytes=interleaved.tobytes(), channel_count=channel_count, sample_rate_hz=sample_rate_hz,
        sample_format="S16_LE", monotonic_timestamp=0.0, sequence=0,
    )


def _synthetic_plane_wave_block(origin_signal, geometry, azimuth_rad, sample_rate_hz=_STEER_SAMPLE_RATE_HZ):
    """Baut einen Mehrkanalblock, dessen Kanaele exakt so verzoegert sind,
    wie eine ebene Welle aus azimuth_rad es fuer die gegebene Geometrie
    erwarten liesse -- dieselbe Formel wie
    GccPhatDelayAndSumBackend._expected_delay_s(), unabhaengig
    nachvollzogen, um die Implementierung selbst zu pruefen (nicht
    zirkulaer gegen sich selbst getestet)."""
    channels = []
    for geom in geometry:
        delay_s = -(geom.x_m * math.cos(azimuth_rad) + geom.y_m * math.sin(azimuth_rad)) / \
            GccPhatDelayAndSumBackend.SPEED_OF_SOUND_M_S
        shift_samples = int(round(delay_s * sample_rate_hz))
        channels.append(np.roll(origin_signal, shift_samples))
    return _multi_channel_block(channels, sample_rate_hz)


def test_steered_output_recovers_original_signal_for_matching_focus_azimuth():
    origin = _white_noise_int16(1600, seed=1)
    block = _synthetic_plane_wave_block(origin, _STEER_GEOMETRY, _STEER_TEST_AZIMUTH_RAD)
    backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1, 2], mic_spacing_m=0.05,
        microphone_geometry=_STEER_GEOMETRY, min_confidence=0.0,
    )
    backend.set_focus_target(_STEER_TEST_AZIMUTH_RAD, valid_until_monotonic_s=float("inf"))
    result = backend.process(block)
    steered = np.frombuffer(result.mono_pcm, dtype=np.int16).astype(np.float64)

    wrong_backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1, 2], mic_spacing_m=0.05,
        microphone_geometry=_STEER_GEOMETRY, min_confidence=0.0,
    )
    wrong_backend.set_focus_target(-_STEER_TEST_AZIMUTH_RAD, valid_until_monotonic_s=float("inf"))
    wrong_result = wrong_backend.process(block)
    wrong_steered = np.frombuffer(wrong_result.mono_pcm, dtype=np.int16).astype(np.float64)

    # Randbereich (Rollover durch np.roll) ausklammern -- nur der stabile
    # Mittelbereich wird auf Ausrichtungsguete verglichen.
    margin = 50
    origin_f = origin.astype(np.float64)[margin:-margin]
    correct_error = np.mean((steered[margin:-margin] - origin_f) ** 2)
    wrong_error = np.mean((wrong_steered[margin:-margin] - origin_f) ** 2)
    assert correct_error < wrong_error * 0.1


def test_measured_azimuth_is_unaffected_by_focus_target():
    # Die DoA-Messung selbst darf sich NIE nach dem Fokus-Ziel richten --
    # nur das Ausgangssignal wird gezielt ausgerichtet.
    ref = _white_noise_int16(320, seed=2)
    delayed = np.roll(ref, 4)
    block = _two_channel_block(ref, delayed)
    backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M,
        microphone_geometry=[MicrophoneGeometry(0, 0.0, -0.15), MicrophoneGeometry(1, 0.0, 0.15)],
    )
    unsteered_azimuth = backend.process(block).azimuth_rad
    backend.set_focus_target(math.radians(80.0), valid_until_monotonic_s=float("inf"))
    steered_azimuth = backend.process(block).azimuth_rad
    assert steered_azimuth == pytest.approx(unsteered_azimuth, abs=1e-9)


def test_focus_target_is_ignored_without_microphone_geometry():
    # Ohne konfigurierte Kanalgeometrie ist echtes Steering nicht
    # moeglich -- fail-closed auf das alte Verhalten, statt eine
    # Geometrie zu erfinden.
    ref = _white_noise_int16(320, seed=3)
    block = _two_channel_block(ref, ref)
    backend = GccPhatDelayAndSumBackend(microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M)
    backend.set_focus_target(0.5, valid_until_monotonic_s=float("inf"))
    assert backend._active_focus_azimuth() is None


def test_focus_target_expires_after_valid_until():
    fake_now = [1000.0]
    backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M,
        microphone_geometry=_STEER_GEOMETRY[:2], now_fn=lambda: fake_now[0],
    )
    backend.set_focus_target(0.3, valid_until_monotonic_s=1005.0)
    assert backend._active_focus_azimuth() == pytest.approx(0.3)
    fake_now[0] = 1006.0
    assert backend._active_focus_azimuth() is None


def test_clear_focus_target_disables_steering():
    backend = GccPhatDelayAndSumBackend(
        microphone_channels=[0, 1], mic_spacing_m=TEST_MIC_SPACING_M,
        microphone_geometry=_STEER_GEOMETRY[:2],
    )
    backend.set_focus_target(0.3, valid_until_monotonic_s=float("inf"))
    assert backend._active_focus_azimuth() is not None
    backend.clear_focus_target()
    assert backend._active_focus_azimuth() is None
