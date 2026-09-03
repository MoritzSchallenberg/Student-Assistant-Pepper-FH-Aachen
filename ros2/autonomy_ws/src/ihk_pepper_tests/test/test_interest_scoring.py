from ihk_pepper_perception.interest_scoring import TrackHistory, score


def test_interested_approaching_waving_person_scores_high():
    h = TrackHistory(
        frame_count=5, time_since_seen_s=0.1, image_center_offset=0.1,
        positions_m=[(0.0, 2.0, 0.0), (0.0, 1.9, 1.0)],
        last_wrist_above_shoulder=True, distance_m=1.9, has_valid_depth=True,
    )
    assert abs(score(h) - 0.85) < 1e-6


def test_person_crossing_fast_scores_zero():
    h = TrackHistory(
        frame_count=5, time_since_seen_s=0.1, image_center_offset=0.5,
        positions_m=[(0.0, 2.0, 0.0), (2.0, 2.0, 1.0)],
        last_wrist_above_shoulder=False, distance_m=2.83, has_valid_depth=True,
    )
    assert score(h) == 0.0


def test_single_frame_only_scores_zero():
    h = TrackHistory(frame_count=1, time_since_seen_s=0.1)
    assert score(h) == 0.0


def test_keepout_zone_is_hard_zero_regardless_of_other_signals():
    h = TrackHistory(
        frame_count=10, time_since_seen_s=0.0, image_center_offset=0.0,
        last_wrist_above_shoulder=True, distance_m=1.5, has_valid_depth=True,
        in_keepout_zone=True,
    )
    assert score(h) == 0.0


def test_score_is_clamped_to_unit_interval():
    h = TrackHistory(frame_count=1, time_since_seen_s=999.0)
    result = score(h)
    assert 0.0 <= result <= 1.0
