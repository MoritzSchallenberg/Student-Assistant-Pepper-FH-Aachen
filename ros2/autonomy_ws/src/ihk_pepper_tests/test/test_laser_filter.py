import math

from sensor_msgs.msg import LaserScan

from ihk_pepper_navigation.laser_filter_node import filter_ranges, is_stale


def _scan(ranges, range_min=0.1, range_max=3.0):
    msg = LaserScan()
    msg.range_min = range_min
    msg.range_max = range_max
    msg.ranges = ranges
    return msg


def test_above_range_max_becomes_inf():
    # Bekannte Pepper-Eigenheit (siehe docs/STATUS.md): Werte > range_max
    # kodieren "kein Echo", nicht eine echte weite Distanz.
    out = filter_ranges(_scan([7.08]))
    assert out[0] == float("inf")


def test_nan_and_inf_become_inf():
    out = filter_ranges(_scan([float("nan"), float("inf")]))
    assert out[0] == float("inf")
    assert out[1] == float("inf")


def test_below_range_min_becomes_inf():
    out = filter_ranges(_scan([0.02, -1.0]))
    assert out[0] == float("inf")
    assert out[1] == float("inf")


def test_valid_value_passes_through():
    out = filter_ranges(_scan([1.5]))
    assert abs(out[0] - 1.5) < 1e-3


def test_is_stale():
    assert is_stale(msg_stamp_s=100.0, now_s=103.0, max_age_s=2.0) is True   # 3s alt, max 2s erlaubt
    assert is_stale(msg_stamp_s=100.0, now_s=101.0, max_age_s=2.0) is False  # 1s alt, noch frisch
