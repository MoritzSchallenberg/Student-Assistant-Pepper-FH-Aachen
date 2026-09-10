"""
Tests fuer face_track_association.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 6).
"""
from ihk_pepper_identity.face_detector_backend import FaceDetection
from ihk_pepper_identity.face_track_association import (
    TrackBoundingBox,
    bbox_center_distance,
    bbox_iou,
    is_depth_plausible,
    match_faces_to_tracks,
)


def _face(x, y, w, h, confidence=0.9):
    return FaceDetection(
        bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h, confidence=confidence,
        measured_at_s=1.0, backend_name="mock",
    )


def _track(track_id, x, y, w, h, **kwargs):
    return TrackBoundingBox(track_id=track_id, bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h, **kwargs)


# ---- bbox_iou ----

def test_identical_boxes_have_iou_one():
    assert bbox_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


def test_disjoint_boxes_have_iou_zero():
    assert bbox_iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_degenerate_box_has_iou_zero():
    assert bbox_iou((0, 0, 0, 10), (0, 0, 10, 10)) == 0.0


def test_partial_overlap_iou_between_zero_and_one():
    iou = bbox_iou((0, 0, 10, 10), (5, 0, 10, 10))
    assert 0.0 < iou < 1.0


# ---- bbox_center_distance ----

def test_identical_boxes_have_zero_center_distance():
    assert bbox_center_distance((0, 0, 10, 10), (0, 0, 10, 10)) == 0.0


def test_offset_boxes_have_positive_center_distance():
    assert bbox_center_distance((0, 0, 10, 10), (10, 0, 10, 10)) == 10.0


# ---- match_faces_to_tracks ----

def test_single_face_matches_single_overlapping_track():
    face = _face(0, 0, 10, 10)
    track = _track(1, 0, 0, 10, 10)
    result = match_faces_to_tracks([face], [track])
    assert 1 in result
    assert result[1].face is face


def test_no_face_over_the_track_yields_no_match():
    face = _face(500, 500, 10, 10)
    track = _track(1, 0, 0, 10, 10)
    result = match_faces_to_tracks([face], [track])
    assert 1 not in result


def test_two_equally_overlapping_faces_are_rejected_as_ambiguous():
    track = _track(1, 0, 0, 10, 10)
    face_a = _face(0, 0, 10, 10)
    face_b = _face(1, 0, 10, 10)  # fast identische Ueberlappung
    result = match_faces_to_tracks([face_a, face_b], [track], ambiguity_margin=0.2)
    assert 1 not in result


def test_a_face_is_never_assigned_to_two_tracks():
    face = _face(0, 0, 10, 10)
    track_a = _track(1, 0, 0, 10, 10)
    track_b = _track(2, 0, 0, 10, 10)  # identische Position -- gleiche Box
    result = match_faces_to_tracks([face], [track_a, track_b])
    matched_tracks = [tid for tid, m in result.items() if m.face is face]
    assert len(matched_tracks) <= 1


def test_global_greedy_assigns_the_clearly_better_track_first():
    # face liegt fast exakt auf track_a, nur am Rand von track_b --
    # track_a soll das Gesicht bekommen, track_b bleibt leer statt eine
    # schlechtere Zuordnung zu erzwingen.
    face = _face(0, 0, 10, 10)
    track_a = _track(1, 0, 0, 10, 10)
    track_b = _track(2, 8, 0, 10, 10)
    result = match_faces_to_tracks([face], [track_a, track_b], minimum_iou=0.05)
    assert result[1].face is face
    assert 2 not in result


def test_two_distinct_faces_match_two_distinct_tracks():
    face_a = _face(0, 0, 10, 10)
    face_b = _face(100, 100, 10, 10)
    track_a = _track(1, 0, 0, 10, 10)
    track_b = _track(2, 100, 100, 10, 10)
    result = match_faces_to_tracks([face_a, face_b], [track_a, track_b])
    assert result[1].face is face_a
    assert result[2].face is face_b


def test_empty_inputs_yield_empty_result():
    assert match_faces_to_tracks([], []) == {}
    assert match_faces_to_tracks([_face(0, 0, 10, 10)], []) == {}
    assert match_faces_to_tracks([], [_track(1, 0, 0, 10, 10)]) == {}


# ---- is_depth_plausible ----

def test_depth_implausible_without_3d_position():
    track = _track(1, 0, 0, 10, 10, has_3d_position=False, distance_m=1.0, depth_confidence=0.9)
    assert is_depth_plausible(track, 0.5, 0.3, 5.0) is False


def test_depth_implausible_below_confidence_threshold():
    track = _track(1, 0, 0, 10, 10, has_3d_position=True, distance_m=1.0, depth_confidence=0.1)
    assert is_depth_plausible(track, 0.5, 0.3, 5.0) is False


def test_depth_implausible_when_out_of_range():
    track = _track(1, 0, 0, 10, 10, has_3d_position=True, distance_m=50.0, depth_confidence=0.9)
    assert is_depth_plausible(track, 0.5, 0.3, 5.0) is False


def test_depth_implausible_on_nan_distance():
    track = _track(1, 0, 0, 10, 10, has_3d_position=True, distance_m=float("nan"), depth_confidence=0.9)
    assert is_depth_plausible(track, 0.5, 0.3, 5.0) is False


def test_depth_plausible_when_all_conditions_met():
    track = _track(1, 0, 0, 10, 10, has_3d_position=True, distance_m=1.5, depth_confidence=0.9)
    assert is_depth_plausible(track, 0.5, 0.3, 5.0) is True
