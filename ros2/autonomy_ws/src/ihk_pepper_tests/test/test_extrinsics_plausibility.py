from ihk_pepper_navigation.extrinsics_plausibility import check_extrinsics_plausibility


def _ok(**overrides):
    translation = dict(x=0.0, y=0.0, z=0.1)
    rotation = dict(roll=0.0, pitch=0.0, yaw=0.0)
    translation.update(overrides.get("translation", {}))
    rotation.update(overrides.get("rotation", {}))
    return check_extrinsics_plausibility(translation, rotation)


def test_placeholder_zero_translation_is_plausible():
    result = _ok()
    assert result.plausible is True
    assert result.reason == "ok"


def test_realistic_head_mount_offset_is_plausible():
    result = _ok(translation={"x": 0.05, "y": 0.0, "z": 0.15})
    assert result.plausible is True


def test_multi_meter_translation_is_implausible():
    result = _ok(translation={"x": 3.0, "y": 0.0, "z": 0.0})
    assert result.plausible is False
    assert "translation_unplausibel" in result.reason


def test_translation_exactly_at_boundary_is_plausible():
    result = _ok(translation={"x": 2.0, "y": 0.0, "z": 0.0})
    assert result.plausible is True


def test_translation_just_above_boundary_is_implausible():
    result = _ok(translation={"x": 2.01, "y": 0.0, "z": 0.0})
    assert result.plausible is False


def test_rotation_outside_valid_range_is_implausible():
    result = _ok(rotation={"yaw": 10.0})
    assert result.plausible is False
    assert "yaw_ausserhalb" in result.reason


def test_negative_rotation_within_range_is_plausible():
    result = _ok(rotation={"roll": -3.0, "pitch": 1.5, "yaw": -3.0})
    assert result.plausible is True
