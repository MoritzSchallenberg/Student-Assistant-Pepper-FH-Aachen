import numpy as np

from ihk_pepper_navigation.realsense_diagnostics import (
    check_realsense_diagnostics,
    compute_invalid_depth_fraction,
)


def _ok(**overrides):
    defaults = dict(
        color_topic_age_s=0.05,
        depth_topic_age_s=0.05,
        camera_info_topic_age_s=0.5,
        max_data_age_s=1.0,
        color_depth_sync_diff_s=0.01,
        max_sync_diff_s=0.05,
        measured_fps=15.0,
        min_fps=10.0,
        invalid_depth_fraction=0.1,
        max_invalid_depth_fraction=0.5,
        tf_to_base_available=True,
        usb_type="3.2",
        require_usb3=True,
    )
    defaults.update(overrides)
    return check_realsense_diagnostics(**defaults)


def test_all_nominal_is_valid():
    result = _ok()
    assert result.valid is True
    assert result.reasons == []


def test_missing_all_topics_reports_camera_not_present():
    result = _ok(color_topic_age_s=None, depth_topic_age_s=None, camera_info_topic_age_s=None)
    assert result.valid is False
    assert "kamera_nicht_vorhanden" in result.reasons
    assert "rgb_topic_fehlt" in result.reasons
    assert "depth_topic_fehlt" in result.reasons
    assert "camera_info_topic_fehlt" in result.reasons


def test_missing_only_depth_topic_does_not_claim_camera_absent():
    result = _ok(depth_topic_age_s=None)
    assert result.valid is False
    assert "depth_topic_fehlt" in result.reasons
    assert "kamera_nicht_vorhanden" not in result.reasons


def test_stale_color_data_is_rejected():
    result = _ok(color_topic_age_s=5.0, max_data_age_s=1.0)
    assert result.valid is False
    assert "rgb_daten_veraltet" in result.reasons


def test_stale_depth_data_is_rejected():
    result = _ok(depth_topic_age_s=5.0, max_data_age_s=1.0)
    assert result.valid is False
    assert "depth_daten_veraltet" in result.reasons


def test_stale_camera_info_is_rejected():
    result = _ok(camera_info_topic_age_s=5.0, max_data_age_s=1.0)
    assert result.valid is False
    assert "camera_info_veraltet" in result.reasons


def test_timestamps_out_of_sync_is_rejected():
    result = _ok(color_depth_sync_diff_s=0.3, max_sync_diff_s=0.05)
    assert result.valid is False
    assert "zeitstempel_nicht_synchron" in result.reasons


def test_framerate_too_low_is_rejected():
    result = _ok(measured_fps=2.0, min_fps=10.0)
    assert result.valid is False
    assert "bildrate_zu_niedrig" in result.reasons


def test_too_much_invalid_depth_is_rejected():
    result = _ok(invalid_depth_fraction=0.9, max_invalid_depth_fraction=0.5)
    assert result.valid is False
    assert "ungueltiger_tiefenanteil_zu_hoch" in result.reasons


def test_missing_tf_to_base_is_rejected():
    result = _ok(tf_to_base_available=False)
    assert result.valid is False
    assert "tf_zur_roboterbasis_fehlt" in result.reasons


def test_usb2_connection_is_rejected_when_usb3_required():
    result = _ok(usb_type="2.1", require_usb3=True)
    assert result.valid is False
    assert "usb_verbindung_ungeeignet" in result.reasons


def test_usb2_connection_is_accepted_when_usb3_not_required():
    result = _ok(usb_type="2.1", require_usb3=False)
    assert result.valid is True


def test_unknown_usb_type_is_not_penalised():
    result = _ok(usb_type=None)
    assert result.valid is True


def test_multiple_simultaneous_problems_are_all_reported():
    result = _ok(measured_fps=1.0, min_fps=10.0, tf_to_base_available=False)
    assert result.valid is False
    assert "bildrate_zu_niedrig" in result.reasons
    assert "tf_zur_roboterbasis_fehlt" in result.reasons
    assert len(result.reasons) == 2


def test_invalid_depth_fraction_all_valid_pixels():
    depth = np.full((10, 10), 2.0, dtype=np.float32)
    fraction = compute_invalid_depth_fraction(depth, depth_scale_to_m=1.0,
                                               min_valid_depth_m=0.2, max_valid_depth_m=8.0)
    assert fraction == 0.0


def test_invalid_depth_fraction_all_zero_pixels():
    depth = np.zeros((10, 10), dtype=np.float32)
    fraction = compute_invalid_depth_fraction(depth, depth_scale_to_m=1.0,
                                               min_valid_depth_m=0.2, max_valid_depth_m=8.0)
    assert fraction == 1.0


def test_invalid_depth_fraction_mixed_nan_and_valid():
    depth = np.full((10, 10), 2.0, dtype=np.float32)
    depth[0:5, :] = np.nan
    fraction = compute_invalid_depth_fraction(depth, depth_scale_to_m=1.0,
                                               min_valid_depth_m=0.2, max_valid_depth_m=8.0)
    assert fraction == 0.5


def test_invalid_depth_fraction_out_of_range_counts_as_invalid():
    depth = np.full((10, 10), 20.0, dtype=np.float32)  # ausserhalb max_valid_depth_m
    fraction = compute_invalid_depth_fraction(depth, depth_scale_to_m=1.0,
                                               min_valid_depth_m=0.2, max_valid_depth_m=8.0)
    assert fraction == 1.0


def test_invalid_depth_fraction_empty_image_is_fully_invalid():
    depth = np.zeros((0, 0), dtype=np.float32)
    fraction = compute_invalid_depth_fraction(depth)
    assert fraction == 1.0


def test_invalid_depth_fraction_respects_depth_scale():
    # Rohwerte in mm (uebliche RealSense-Kodierung), scale=0.001 -> Meter
    depth = np.full((10, 10), 2000.0, dtype=np.float32)
    fraction = compute_invalid_depth_fraction(depth, depth_scale_to_m=0.001,
                                               min_valid_depth_m=0.2, max_valid_depth_m=8.0)
    assert fraction == 0.0
