import pytest

from ihk_pepper_bridge.joint_limits import validate_angle, get_limits, JointLimitError


def test_valid_angle_passes_through():
    assert validate_angle("HeadYaw", 0.0) == 0.0


def test_out_of_range_strict_raises():
    with pytest.raises(JointLimitError):
        validate_angle("HeadYaw", 5.0, strict=True)


def test_out_of_range_non_strict_clamps():
    clamped = validate_angle("HeadYaw", 5.0, strict=False)
    lo, hi, _ = get_limits("HeadYaw")
    assert clamped == hi


def test_unknown_joint_passes_through():
    # Kein Limit hinterlegt -- wird durchgereicht (Aufrufer muss selbst
    # pruefen, siehe Moduldoku).
    assert validate_angle("NichtExistierendesGelenk", 99.0) == 99.0


def test_t_pose_elbow_roll_zero_is_valid():
    # Regressionstest fuer den in dieser Session gefundenen Bug: 0.0 wurde
    # faelschlich als ausserhalb der Grenzen abgelehnt, obwohl live am
    # echten Roboter mehrfach erfolgreich getestet (siehe joint_limits.py
    # Kommentar + IMPLEMENTATION_REPORT.md).
    assert validate_angle("LElbowRoll", 0.0, strict=True) == 0.0
    assert validate_angle("RElbowRoll", 0.0, strict=True) == 0.0
