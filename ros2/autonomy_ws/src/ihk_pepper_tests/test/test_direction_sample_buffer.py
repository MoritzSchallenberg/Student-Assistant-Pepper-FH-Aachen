"""
Tests fuer direction_sample_buffer.py (Entwicklungsauftrag 04-B, AP6.1,
Abschnitt 5).
"""
import math

import pytest

from ihk_pepper_audio.direction_sample_buffer import DirectionSampleBuffer, TimedDirectionSample


def _sample(azimuth_rad=0.0, confidence=1.0, valid=True, monotonic_stamp_s=1000.0,
            ros_stamp_ns=1_000, frame_id="respeaker_link"):
    return TimedDirectionSample(
        ros_stamp_ns=ros_stamp_ns, monotonic_stamp_s=monotonic_stamp_s,
        frame_id=frame_id, azimuth_rad=azimuth_rad, confidence=confidence, valid=valid,
    )


def _buffer_at(now_s=1000.0, max_duration_s=3.0):
    """now_fn fest auf now_s eingefroren -- die im Test verwendeten
    monotonic_stamp_s-Werte liegen bewusst nahe now_s, damit
    _evict_old() (das den ECHTEN time.monotonic() sonst als Default
    verwendet) die Testproben nicht faelschlich als laengst veraltet
    verwirft."""
    return DirectionSampleBuffer(max_duration_s=max_duration_s, now_fn=lambda: now_s)


def test_push_and_select_single_sample():
    buf = _buffer_at(1000.0)
    buf.push(_sample(azimuth_rad=0.3, monotonic_stamp_s=1000.0))
    result = buf.select_for_window(999.0, 1001.0)
    assert result is not None
    assert result.azimuth_rad == pytest.approx(0.3)


def test_select_returns_none_when_buffer_empty():
    buf = _buffer_at(1000.0)
    assert buf.select_for_window(0.0, 100.0) is None


def test_select_returns_none_outside_window():
    buf = _buffer_at(1000.0)
    buf.push(_sample(monotonic_stamp_s=1000.0))
    assert buf.select_for_window(2000.0, 2001.0) is None


def test_invalid_sample_is_excluded():
    buf = _buffer_at(1000.0)
    buf.push(_sample(valid=False, monotonic_stamp_s=1000.0))
    assert buf.select_for_window(999.0, 1001.0) is None


def test_low_confidence_sample_excluded_by_min_confidence():
    buf = _buffer_at(1000.0)
    buf.push(_sample(confidence=0.1, monotonic_stamp_s=1000.0))
    assert buf.select_for_window(999.0, 1001.0, min_confidence=0.5) is None


def test_nan_azimuth_is_rejected_on_push():
    buf = DirectionSampleBuffer()
    accepted = buf.push(_sample(azimuth_rad=float("nan")))
    assert accepted is False
    assert len(buf) == 0


def test_inf_confidence_is_rejected_on_push():
    buf = DirectionSampleBuffer()
    accepted = buf.push(_sample(confidence=float("inf")))
    assert accepted is False


def test_azimuth_outside_valid_range_is_rejected():
    buf = DirectionSampleBuffer()
    accepted = buf.push(_sample(azimuth_rad=10.0))  # weit ausserhalb [-pi, pi]
    assert accepted is False


def test_old_samples_are_evicted_beyond_max_duration():
    now = {"t": 1000.0}
    buf = DirectionSampleBuffer(max_duration_s=1.0, now_fn=lambda: now["t"])
    buf.push(_sample(monotonic_stamp_s=1000.0))
    assert len(buf) == 1
    now["t"] = 1002.0  # 2s spaeter, ueber max_duration_s=1.0
    buf.push(_sample(monotonic_stamp_s=1002.0))
    assert len(buf) == 1  # die alte Probe wurde verworfen


def test_circular_mean_averages_multiple_samples_correctly():
    buf = _buffer_at(1000.0)
    buf.push(_sample(azimuth_rad=0.1, confidence=1.0, monotonic_stamp_s=1000.0))
    buf.push(_sample(azimuth_rad=0.3, confidence=1.0, monotonic_stamp_s=1000.1))
    result = buf.select_for_window(999.0, 1001.0)
    assert result.azimuth_rad == pytest.approx(0.2, abs=1e-6)


def test_circular_mean_handles_wraparound_near_pi():
    # Zwei Proben knapp auf beiden Seiten des +-pi-Uebergangs -- der
    # "wahre" Mittelwert liegt bei +-pi, NICHT bei 0 (was ein naiver
    # arithmetischer Mittelwert faelschlich ergeben wuerde).
    buf = _buffer_at(1000.0)
    buf.push(_sample(azimuth_rad=math.pi - 0.05, confidence=1.0, monotonic_stamp_s=1000.0))
    buf.push(_sample(azimuth_rad=-math.pi + 0.05, confidence=1.0, monotonic_stamp_s=1000.1))
    result = buf.select_for_window(999.0, 1001.0)
    assert abs(result.azimuth_rad) > 3.0  # nahe +-pi, NICHT nahe 0


def test_confidence_weighting_favors_higher_confidence_sample():
    buf = _buffer_at(1000.0)
    buf.push(_sample(azimuth_rad=0.0, confidence=0.9, monotonic_stamp_s=1000.0))
    buf.push(_sample(azimuth_rad=1.0, confidence=0.1, monotonic_stamp_s=1000.1))
    result = buf.select_for_window(999.0, 1001.0)
    assert result.azimuth_rad < 0.3  # deutlich naeher an 0.0 als an 1.0


def test_old_measurement_not_reused_for_a_later_window():
    buf = _buffer_at(1000.0)
    buf.push(_sample(azimuth_rad=0.5, monotonic_stamp_s=1000.0))
    # Ein spaeteres Fenster, das die alte Probe NICHT mehr einschliesst.
    result = buf.select_for_window(1005.0, 1006.0)
    assert result is None


def test_len_reports_current_sample_count():
    buf = _buffer_at(1000.0)
    assert len(buf) == 0
    buf.push(_sample(monotonic_stamp_s=1000.0))
    assert len(buf) == 1
