from ihk_pepper_navigation.head_pose_gate import check_head_pose


def _ok(**overrides):
    defaults = dict(
        head_yaw_rad=0.0, head_pitch_rad=0.0,
        target_yaw_rad=0.0, target_pitch_rad=0.0,
        tolerance_rad=0.05, joint_state_age_s=0.1, max_age_s=1.0,
    )
    defaults.update(overrides)
    return check_head_pose(**defaults)


def test_head_in_pose_is_valid():
    result = _ok()
    assert result.valid is True
    assert result.reason == "ok"


def test_missing_joint_states_is_invalid():
    result = _ok(head_yaw_rad=None, head_pitch_rad=None)
    assert result.valid is False
    assert result.reason == "keine_joint_states_empfangen"


def test_stale_joint_states_is_invalid():
    result = _ok(joint_state_age_s=5.0, max_age_s=1.0)
    assert result.valid is False
    assert result.reason == "joint_states_veraltet"


def test_yaw_outside_tolerance_is_invalid():
    result = _ok(head_yaw_rad=0.5, target_yaw_rad=0.0, tolerance_rad=0.05)
    assert result.valid is False
    assert "yaw_abweichung" in result.reason


def test_pitch_outside_tolerance_is_invalid():
    result = _ok(head_pitch_rad=0.3, target_pitch_rad=0.0, tolerance_rad=0.05)
    assert result.valid is False
    assert "pitch_abweichung" in result.reason


def test_within_tolerance_boundary_is_valid():
    result = _ok(head_yaw_rad=0.04, target_yaw_rad=0.0, tolerance_rad=0.05)
    assert result.valid is True
