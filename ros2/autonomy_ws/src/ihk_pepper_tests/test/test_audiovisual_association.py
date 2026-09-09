"""
Tests fuer audiovisual_association.py (Entwicklungsauftrag 04-B, AP6,
Abschnitt 13).
"""
import math

import pytest

from ihk_pepper_perception.audiovisual_association import (
    TrackCandidate,
    associate_person_to_sound,
    bearing_deg,
)


def _track(track_id=1, confidence=0.9, has_3d=True, x=1.0, y=0.0, stable=True, age_s=0.1,
           in_keepout=False, frame_id="base_link", source_camera="realsense", distance_m=0.0):
    return TrackCandidate(
        track_id=track_id, confidence=confidence, has_3d_position=has_3d,
        position_x_m=x, position_y_m=y, stable=stable, age_s=age_s,
        in_keepout_zone=in_keepout, frame_id=frame_id, source_camera=source_camera,
        distance_m=distance_m,
    )


def test_bearing_deg_straight_ahead_is_zero():
    assert abs(bearing_deg(1.0, 0.0)) < 1e-6


def test_bearing_deg_to_the_left_is_positive():
    assert bearing_deg(1.0, 1.0) > 0


def test_bearing_deg_to_the_right_is_negative():
    assert bearing_deg(1.0, -1.0) < 0


def test_single_unambiguous_person_is_selected():
    tracks = [_track(track_id=7, x=1.0, y=0.0)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is True
    assert result.selected_track_id == 7


def test_person_outside_angular_corridor_is_rejected():
    tracks = [_track(track_id=1, x=0.0, y=1.0)]  # 90 Grad links
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0, maximum_angular_error_deg=20.0)
    assert result.valid is False
    assert result.selected_track_id == -1
    assert result.reason == "keine_person_im_winkelkorridor"


def test_two_ambiguous_persons_selects_nobody():
    # Beide fast auf derselben Peilung -- Abstand unter der Marge.
    tracks = [
        _track(track_id=1, x=1.0, y=0.0),
        _track(track_id=2, x=1.0, y=0.02),
    ]
    result = associate_person_to_sound(
        tracks, sound_azimuth_rad=0.0, minimum_ambiguity_margin_deg=10.0)
    assert result.valid is False
    assert result.selected_track_id == -1
    assert result.reason == "mehrdeutig"


def test_best_candidate_with_sufficient_margin_is_selected():
    tracks = [
        _track(track_id=1, x=1.0, y=0.0),      # Peilung 0 Grad
        _track(track_id=2, x=0.0, y=1.0),      # Peilung 90 Grad -- weit weg, wird eh verworfen
    ]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is True
    assert result.selected_track_id == 1


def test_invalid_depth_is_excluded():
    tracks = [_track(track_id=1, has_3d=False, x=1.0, y=0.0)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is False


def test_stale_track_is_excluded():
    tracks = [_track(track_id=1, x=1.0, y=0.0, age_s=5.0)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0, maximum_track_age_s=0.5)
    assert result.valid is False


def test_low_confidence_track_is_excluded():
    tracks = [_track(track_id=1, x=1.0, y=0.0, confidence=0.3)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0, minimum_track_confidence=0.7)
    assert result.valid is False


def test_unstable_track_is_excluded():
    tracks = [_track(track_id=1, x=1.0, y=0.0, stable=False)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is False


def test_track_in_keepout_zone_is_excluded():
    tracks = [_track(track_id=1, x=1.0, y=0.0, in_keepout=True)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is False


def test_empty_track_list_selects_nobody():
    result = associate_person_to_sound([], sound_azimuth_rad=0.0)
    assert result.valid is False
    assert result.selected_track_id == -1


def test_track_in_wrong_frame_is_excluded():
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 11: has_3d_position=True
    # allein reicht nicht -- ein Track, der (noch) nicht im erwarteten
    # base_frame vorliegt, wird fail-closed verworfen.
    tracks = [_track(track_id=1, x=1.0, y=0.0, frame_id="camera_color_optical_frame")]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is False


def test_track_from_wrong_source_camera_is_excluded():
    tracks = [_track(track_id=1, x=1.0, y=0.0, source_camera="pepper_camera_2d_only")]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is False


def test_custom_required_frame_and_source_camera_are_honored():
    tracks = [_track(track_id=1, x=1.0, y=0.0, frame_id="map", source_camera="pepper_camera_2d_only")]
    result = associate_person_to_sound(
        tracks, sound_azimuth_rad=0.0, required_frame_id="map",
        required_source_camera="pepper_camera_2d_only",
    )
    assert result.valid is True
    assert result.selected_track_id == 1


def test_selected_track_carries_azimuth_distance_and_confidence():
    tracks = [_track(track_id=7, x=1.0, y=0.0, confidence=0.85, distance_m=2.5)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=0.0)
    assert result.valid is True
    assert result.target_azimuth_rad == pytest.approx(0.0, abs=1e-6)
    assert result.distance_m == 2.5
    assert result.confidence == 0.85


def test_rejected_result_carries_no_fabricated_azimuth_or_distance():
    tracks = [_track(track_id=1, x=1.0, y=0.0, distance_m=3.0)]
    result = associate_person_to_sound(tracks, sound_azimuth_rad=math.radians(90.0),
                                        maximum_angular_error_deg=20.0)
    assert result.valid is False
    assert result.target_azimuth_rad == 0.0
    assert result.distance_m == 0.0


def test_angle_wraparound_near_180_degrees_is_handled_correctly():
    # Schallquelle fast direkt hinten (~179 Grad), Person auch fast
    # direkt hinten (~-179 Grad) -- der WIRKLICHE Winkelunterschied ist
    # klein (~2 Grad), nicht 358 Grad.
    azimuth_rad = math.radians(179.0)
    tracks = [_track(track_id=1, x=-1.0, y=-0.02)]  # Peilung knapp unter -179 Grad
    result = associate_person_to_sound(tracks, sound_azimuth_rad=azimuth_rad, maximum_angular_error_deg=20.0)
    assert result.valid is True
    assert result.angular_error_deg < 10.0
