"""
Tests fuer group_tracking.py (Entwicklungsauftrag 04-B, AP7, Abschnitt
14/16).
"""
import math

import pytest

from ihk_pepper_perception.group_tracking import (
    GroupTracker,
    GroupTrackingConfig,
    TrackCandidate,
    cluster_tracks,
    compute_group_geometry,
)


def _track(track_id, x=0.0, y=0.0, stable=True, age_s=0.1, has_3d=True):
    return TrackCandidate(track_id=track_id, x_m=x, y_m=y, stable=stable, age_s=age_s,
                           has_3d_position=has_3d)


# ---- cluster_tracks ----

def test_two_close_stable_tracks_form_a_cluster():
    config = GroupTrackingConfig(maximum_member_spacing_m=1.8, minimum_members=2)
    tracks = [_track(1, x=1.0, y=0.0), _track(2, x=1.0, y=1.0)]
    clusters = cluster_tracks(tracks, config)
    assert len(clusters) == 1
    assert set(clusters[0]) == {1, 2}


def test_a_lone_stable_track_forms_no_cluster():
    config = GroupTrackingConfig(minimum_members=2)
    clusters = cluster_tracks([_track(1, x=1.0, y=0.0)], config)
    assert clusters == []


def test_far_apart_tracks_do_not_cluster():
    config = GroupTrackingConfig(maximum_member_spacing_m=1.0, minimum_members=2)
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=5.0, y=0.0)]
    assert cluster_tracks(tracks, config) == []


def test_chained_tracks_form_one_cluster_via_transitivity():
    config = GroupTrackingConfig(maximum_member_spacing_m=1.0, minimum_members=2)
    # 1<->2 nah, 2<->3 nah, aber 1<->3 selbst zu weit -- trotzdem EIN Cluster.
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.9, y=0.0), _track(3, x=1.8, y=0.0)]
    clusters = cluster_tracks(tracks, config)
    assert len(clusters) == 1
    assert set(clusters[0]) == {1, 2, 3}


def test_unstable_track_is_excluded_from_clustering():
    config = GroupTrackingConfig(minimum_members=2)
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0, stable=False)]
    assert cluster_tracks(tracks, config) == []


def test_track_without_3d_position_is_excluded():
    config = GroupTrackingConfig(minimum_members=2)
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0, has_3d=False)]
    assert cluster_tracks(tracks, config) == []


def test_stale_track_is_excluded():
    config = GroupTrackingConfig(minimum_members=2, maximum_track_age_s=0.5)
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0, age_s=5.0)]
    assert cluster_tracks(tracks, config) == []


def test_cluster_is_capped_at_maximum_members():
    config = GroupTrackingConfig(maximum_member_spacing_m=10.0, minimum_members=2, maximum_members=3)
    tracks = [_track(i, x=float(i), y=0.0) for i in range(5)]
    clusters = cluster_tracks(tracks, config)
    assert len(clusters[0]) == 3


def test_two_separate_clusters_stay_separate():
    config = GroupTrackingConfig(maximum_member_spacing_m=1.0, minimum_members=2)
    tracks = [
        _track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0),
        _track(3, x=10.0, y=0.0), _track(4, x=10.5, y=0.0),
    ]
    clusters = cluster_tracks(tracks, config)
    assert len(clusters) == 2


# ---- GroupTracker: Beitritts-/Verlassens-Hysterese ----

def test_group_does_not_form_before_join_hysteresis_elapses():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=1.0, minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    snapshot = tracker.update(tracks, anchor_track_id=1)
    assert snapshot.formed is False


def test_group_forms_after_join_hysteresis_elapses():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=1.0, minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    tracker.update(tracks, anchor_track_id=1)
    fake_time[0] = 1.5
    snapshot = tracker.update(tracks, anchor_track_id=1)
    assert snapshot.formed is True
    assert set(snapshot.member_track_ids) == {1, 2}


def test_group_is_not_stable_before_minimum_stable_duration():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, minimum_stable_duration_s=5.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    snapshot = tracker.update(tracks, anchor_track_id=1)
    assert snapshot.formed is True
    assert snapshot.stable is False


def test_group_becomes_stable_after_minimum_stable_duration():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, minimum_stable_duration_s=2.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    tracker.update(tracks, anchor_track_id=1)
    fake_time[0] = 3.0
    snapshot = tracker.update(tracks, anchor_track_id=1)
    assert snapshot.stable is True


def test_random_passerby_is_not_added_without_completing_join_hysteresis():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=1.0, minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    tracker.update(tracks, anchor_track_id=1)
    fake_time[0] = 1.5
    tracker.update(tracks, anchor_track_id=1)  # Gruppe {1,2} jetzt bestaetigt

    # Ein DRITTER Track taucht ganz kurz auf und verschwindet gleich
    # wieder -- er darf NIE Mitglied werden.
    fake_time[0] = 1.6
    tracks_with_passerby = tracks + [_track(3, x=0.6, y=0.0)]
    tracker.update(tracks_with_passerby, anchor_track_id=1)
    fake_time[0] = 1.7
    snapshot = tracker.update(tracks, anchor_track_id=1)  # Passant schon wieder weg
    assert 3 not in snapshot.member_track_ids


def test_member_stays_through_a_brief_occlusion_within_leave_hysteresis():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, leave_hysteresis_s=2.0,
                             minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    tracker.update(tracks, anchor_track_id=1)

    fake_time[0] = 1.0
    # Track 2 kurz verdeckt (kein Cluster mehr mit ihm).
    snapshot = tracker.update([_track(1, x=0.0, y=0.0)], anchor_track_id=1)
    # Weiterhin als Mitglied gefuehrt (innerhalb der Verlassens-Hysterese) --
    # unterhalb von minimum_members zaehlt es aber (noch) nicht als formed,
    # da Track 2 kein Cluster-Mitglied mehr ist. Die Gruppe selbst bleibt
    # aber bestehen, sobald Track 2 zurueckkehrt.
    fake_time[0] = 1.5
    snapshot = tracker.update(tracks, anchor_track_id=1)
    assert 2 in snapshot.member_track_ids


def test_member_leaves_after_leave_hysteresis_elapses():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, leave_hysteresis_s=1.0,
                             minimum_members=2, minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks3 = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0), _track(3, x=1.0, y=0.0)]
    tracker.update(tracks3, anchor_track_id=1)

    # Track 3 verschwindet dauerhaft.
    fake_time[0] = 0.5
    tracker.update([_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)], anchor_track_id=1)
    fake_time[0] = 2.0
    snapshot = tracker.update([_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)], anchor_track_id=1)
    assert 3 not in snapshot.member_track_ids


def test_group_dissolves_when_anchor_has_no_cluster():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, leave_hysteresis_s=0.5,
                             minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    tracker.update(tracks, anchor_track_id=1)

    fake_time[0] = 2.0
    snapshot = tracker.update([_track(1, x=0.0, y=0.0)], anchor_track_id=1)  # Track 2 komplett weg
    assert snapshot.formed is False


def test_group_id_is_stable_across_updates_of_the_same_group():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0])
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    snap1 = tracker.update(tracks, anchor_track_id=1)
    fake_time[0] = 1.0
    snap2 = tracker.update(tracks, anchor_track_id=1)
    assert snap1.group_id == snap2.group_id


def test_group_id_changes_after_the_group_fully_dissolves_and_reforms():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, leave_hysteresis_s=0.0,
                             minimum_stable_duration_s=0.0),
        now_fn=lambda: fake_time[0], id_fn=iter(["group-a", "group-b"]).__next__)
    tracks = [_track(1, x=0.0, y=0.0), _track(2, x=0.5, y=0.0)]
    snap1 = tracker.update(tracks, anchor_track_id=1)
    assert snap1.group_id == "group-a"

    fake_time[0] = 1.0
    tracker.update([_track(1, x=0.0, y=0.0)], anchor_track_id=1)  # Gruppe zerfaellt

    fake_time[0] = 2.0
    snap2 = tracker.update(tracks, anchor_track_id=1)
    assert snap2.group_id == "group-b"


# ---- compute_group_geometry ----

def test_geometry_none_for_empty_members():
    assert compute_group_geometry([]) is None


def test_geometry_center_is_the_mean_position():
    members = [_track(1, x=0.0, y=0.0), _track(2, x=2.0, y=0.0)]
    geometry = compute_group_geometry(members)
    assert geometry.center_x_m == pytest.approx(1.0)
    assert geometry.center_y_m == pytest.approx(0.0)


def test_geometry_angular_span_for_two_symmetric_members():
    members = [_track(1, x=1.0, y=1.0), _track(2, x=1.0, y=-1.0)]
    geometry = compute_group_geometry(members)
    assert geometry.angular_span_rad == pytest.approx(math.pi / 2, abs=1e-6)


def test_geometry_distances_are_min_and_max():
    members = [_track(1, x=1.0, y=0.0), _track(2, x=3.0, y=0.0)]
    geometry = compute_group_geometry(members)
    assert geometry.minimum_member_distance_m == pytest.approx(1.0)
    assert geometry.maximum_member_distance_m == pytest.approx(3.0)


def test_geometry_all_within_fov_for_a_narrow_group_straight_ahead():
    members = [_track(1, x=2.0, y=0.1), _track(2, x=2.0, y=-0.1)]
    geometry = compute_group_geometry(members, camera_horizontal_fov_deg=87.0)
    assert geometry.all_members_within_fov is True


def test_geometry_not_all_within_fov_for_a_wide_group():
    members = [_track(1, x=1.0, y=5.0), _track(2, x=1.0, y=-5.0)]
    geometry = compute_group_geometry(members, camera_horizontal_fov_deg=60.0)
    assert geometry.all_members_within_fov is False
