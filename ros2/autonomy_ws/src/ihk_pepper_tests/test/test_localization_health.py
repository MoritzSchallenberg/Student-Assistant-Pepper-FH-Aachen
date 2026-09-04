from ihk_pepper_navigation.localization_health import check_localization_health


def _ok(**overrides):
    defaults = dict(
        map_to_odom_tf_available=True,
        map_to_odom_tf_age_s=0.2,
        max_tf_age_s=2.0,
    )
    defaults.update(overrides)
    return check_localization_health(**defaults)


def test_fresh_map_odom_tf_is_valid():
    result = _ok()
    assert result.valid is True
    assert result.reason == "ok"


def test_missing_tf_is_invalid():
    result = _ok(map_to_odom_tf_available=False)
    assert result.valid is False
    assert result.reason == "keine_map_odom_tf"


def test_unknown_age_is_invalid():
    result = _ok(map_to_odom_tf_age_s=None)
    assert result.valid is False
    assert result.reason == "map_odom_tf_alter_unbekannt"


def test_stale_tf_is_invalid():
    result = _ok(map_to_odom_tf_age_s=10.0, max_tf_age_s=2.0)
    assert result.valid is False
    assert result.reason == "map_odom_tf_veraltet"


def test_age_at_exact_boundary_is_valid():
    result = _ok(map_to_odom_tf_age_s=2.0, max_tf_age_s=2.0)
    assert result.valid is True
