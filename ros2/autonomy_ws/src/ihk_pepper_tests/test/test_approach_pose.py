import math

import pytest

from ihk_pepper_navigation.approach_pose import (
    RepeatedPlanningFailureGuard,
    compute_approach_pose,
    is_track_fresh,
    should_replan,
)


def _pose(**overrides):
    defaults = dict(
        robot_x=0.0, robot_y=0.0,
        person_x=3.0, person_y=0.0,
        target_distance_m=1.0,
        minimum_person_distance_m=0.5,
        maximum_approach_distance_m=8.0,
    )
    defaults.update(overrides)
    return compute_approach_pose(**defaults)


def test_target_is_in_front_of_person_not_on_person():
    result = _pose()
    assert result.valid is True
    assert result.reason == "ok"
    # Person bei x=3, Ziel 1m davor auf der Geraden Roboter(0,0)->Person
    # -> x=2.0, y=0.0. NIEMALS x=3 (die Personenposition selbst).
    assert result.target_x == pytest.approx(2.0)
    assert result.target_y == pytest.approx(0.0)
    assert result.target_x != pytest.approx(3.0)


def test_target_yaw_faces_the_person():
    result = _pose(robot_x=0.0, robot_y=0.0, person_x=0.0, person_y=5.0)
    assert result.valid is True
    assert result.target_yaw_rad == pytest.approx(math.pi / 2)


def test_diagonal_direction_and_distance_are_correct():
    result = _pose(robot_x=0.0, robot_y=0.0, person_x=3.0, person_y=4.0, target_distance_m=1.0)
    assert result.valid is True
    # Einheitsvektor (0.6, 0.8), Ziel 1m vor der Person: (3-0.6, 4-0.8)
    assert result.target_x == pytest.approx(2.4)
    assert result.target_y == pytest.approx(3.2)
    dist_to_target = math.hypot(result.target_x - 0.0, result.target_y - 0.0)
    assert dist_to_target == pytest.approx(4.0)  # 5m Gesamtdistanz - 1m Zielabstand


def test_person_already_within_target_distance_needs_no_drive():
    result = _pose(person_x=0.5, person_y=0.0, target_distance_m=1.0)
    assert result.valid is True
    assert result.already_within_distance is True
    assert result.reason == "bereits_im_gespraechsabstand"
    assert result.target_x == pytest.approx(0.0)
    assert result.target_y == pytest.approx(0.0)


def test_person_exactly_at_target_distance_needs_no_drive():
    result = _pose(person_x=1.0, person_y=0.0, target_distance_m=1.0)
    assert result.valid is True
    assert result.already_within_distance is True


def test_person_position_identical_to_robot_is_rejected():
    result = _pose(robot_x=1.0, robot_y=1.0, person_x=1.0, person_y=1.0)
    assert result.valid is False
    assert result.reason == "person_position_identisch_mit_roboterposition"


def test_person_beyond_maximum_approach_distance_is_rejected():
    result = _pose(person_x=20.0, person_y=0.0, maximum_approach_distance_m=8.0)
    assert result.valid is False
    assert result.reason == "person_ausserhalb_maximum_approach_distance_m"


def test_target_distance_below_minimum_is_rejected():
    result = _pose(target_distance_m=0.3, minimum_person_distance_m=0.5)
    assert result.valid is False
    assert result.reason == "target_distance_unter_minimum_person_distance"


def test_zero_or_negative_target_distance_is_rejected():
    result = _pose(target_distance_m=0.0)
    assert result.valid is False
    assert result.reason == "target_distance_muss_positiv_sein"


def test_target_in_keepout_zone_is_rejected():
    from ihk_pepper_navigation.zone_config import Zone
    zones = {
        "z1": Zone(id="z1", type="keepout",
                   polygon=[(1.5, -1.0), (2.5, -1.0), (2.5, 1.0), (1.5, 1.0)]),
    }
    result = _pose(person_x=3.0, person_y=0.0, target_distance_m=1.0, zones=zones)
    assert result.valid is False
    assert result.reason == "zielpose_in_keepout_zone"


def test_target_outside_keepout_zone_is_accepted():
    from ihk_pepper_navigation.zone_config import Zone
    zones = {
        "z1": Zone(id="z1", type="keepout",
                   polygon=[(-5.0, -5.0), (-4.0, -5.0), (-4.0, -4.0), (-5.0, -4.0)]),
    }
    result = _pose(person_x=3.0, person_y=0.0, target_distance_m=1.0, zones=zones)
    assert result.valid is True


def test_costmap_free_fn_rejects_target_in_obstacle():
    result = _pose(costmap_free_fn=lambda x, y: False)
    assert result.valid is False
    assert result.reason == "zielpose_ausserhalb_karte_oder_in_hindernis"


def test_costmap_free_fn_accepts_free_target():
    result = _pose(costmap_free_fn=lambda x, y: True)
    assert result.valid is True


def test_should_replan_triggers_above_threshold():
    assert should_replan(0.0, 0.0, 1.0, 0.0, replan_distance_threshold_m=0.5) is True


def test_should_replan_ignores_small_jitter():
    assert should_replan(0.0, 0.0, 0.05, 0.0, replan_distance_threshold_m=0.5) is False


def test_track_fresh_within_timeout():
    assert is_track_fresh(track_age_s=0.5, person_track_timeout_s=2.0) is True


def test_track_stale_beyond_timeout():
    assert is_track_fresh(track_age_s=3.0, person_track_timeout_s=2.0) is False


def test_repeated_planning_failure_guard_aborts_after_threshold():
    guard = RepeatedPlanningFailureGuard(max_consecutive_failures=3)
    assert guard.should_abort() is False
    guard.record_failure()
    guard.record_failure()
    assert guard.should_abort() is False
    guard.record_failure()
    assert guard.should_abort() is True


def test_repeated_planning_failure_guard_resets_on_success():
    guard = RepeatedPlanningFailureGuard(max_consecutive_failures=2)
    guard.record_failure()
    guard.record_success()
    guard.record_failure()
    assert guard.should_abort() is False
    assert guard.consecutive_failures == 1
