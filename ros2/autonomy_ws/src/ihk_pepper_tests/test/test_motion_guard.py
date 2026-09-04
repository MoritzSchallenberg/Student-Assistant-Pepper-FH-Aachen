from ihk_pepper_interaction.motion_guard import MotionGuardInputs, evaluate_motion_guard


def _ok(**overrides):
    defaults = dict(
        live_motion_mode_active=True,
        safety_allow_motion=True,
        realsense_diagnostics_valid=True,
        odometry_valid=True,
        localization_valid=True,
        obstacle_data_valid=True,
        head_navigation_pose_valid=True,
        bumper_active=False,
        emergency_stop=False,
        gesture_in_progress=False,
        cmd_age_s=0.05,
        max_cmd_age_s=0.5,
    )
    defaults.update(overrides)
    return evaluate_motion_guard(MotionGuardInputs(**defaults))


def test_all_conditions_met_allows_motion():
    result = _ok()
    assert result.allow is True
    assert result.reason == "ok"


def test_bumper_blocks_motion():
    result = _ok(bumper_active=True)
    assert result.allow is False
    assert result.reason == "bumper_active"


def test_bumper_takes_priority_over_everything_else():
    result = _ok(bumper_active=True, emergency_stop=True, safety_allow_motion=False)
    assert result.reason == "bumper_active"


def test_emergency_stop_blocks_motion():
    result = _ok(emergency_stop=True)
    assert result.allow is False
    assert result.reason == "emergency_stop"


def test_live_motion_mode_inactive_blocks_motion():
    result = _ok(live_motion_mode_active=False)
    assert result.allow is False
    assert result.reason == "live_motion_mode_inactive"


def test_safety_gate_disallow_blocks_motion():
    result = _ok(safety_allow_motion=False)
    assert result.allow is False
    assert result.reason == "safety_allow_motion_false"


def test_invalid_realsense_diagnostics_blocks_motion():
    result = _ok(realsense_diagnostics_valid=False)
    assert result.allow is False
    assert result.reason == "realsense_diagnostics_invalid"


def test_invalid_odometry_blocks_motion():
    result = _ok(odometry_valid=False)
    assert result.allow is False
    assert result.reason == "odometry_invalid"


def test_invalid_localization_blocks_motion():
    result = _ok(localization_valid=False)
    assert result.allow is False
    assert result.reason == "localization_invalid"


def test_invalid_obstacle_data_blocks_motion():
    result = _ok(obstacle_data_valid=False)
    assert result.allow is False
    assert result.reason == "obstacle_data_invalid"


def test_head_not_in_navigation_pose_blocks_motion():
    result = _ok(head_navigation_pose_valid=False)
    assert result.allow is False
    assert result.reason == "head_not_in_navigation_pose"


def test_gesture_in_progress_blocks_motion():
    result = _ok(gesture_in_progress=True)
    assert result.allow is False
    assert result.reason == "gesture_in_progress"


def test_missing_cmd_age_blocks_motion():
    result = _ok(cmd_age_s=None)
    assert result.allow is False
    assert result.reason == "cmd_vel_timeout"


def test_stale_cmd_blocks_motion():
    result = _ok(cmd_age_s=5.0, max_cmd_age_s=0.5)
    assert result.allow is False
    assert result.reason == "cmd_vel_timeout"


def test_cmd_age_exactly_at_boundary_is_allowed():
    result = _ok(cmd_age_s=0.5, max_cmd_age_s=0.5)
    assert result.allow is True
