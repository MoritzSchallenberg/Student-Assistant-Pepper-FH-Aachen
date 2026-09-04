from ihk_pepper_navigation.odometry_health import (
    check_odometry_health,
    max_translation_variance_from_covariance,
)


def _ok(**overrides):
    defaults = dict(
        lost=False,
        translation_variance=0.001,
        max_translation_variance=0.05,
        data_age_s=0.1,
        max_data_age_s=1.0,
        inliers=30,
        min_inliers=10,
    )
    defaults.update(overrides)
    return check_odometry_health(**defaults)


def test_healthy_odometry_is_valid():
    result = _ok()
    assert result.valid is True
    assert result.reason == "ok"


def test_no_odometry_ever_received_is_invalid():
    result = _ok(data_age_s=None)
    assert result.valid is False
    assert result.reason == "keine_odometrie_empfangen"


def test_stale_odometry_is_invalid():
    result = _ok(data_age_s=5.0, max_data_age_s=1.0)
    assert result.valid is False
    assert result.reason == "odometrie_veraltet"


def test_lost_tracking_is_invalid():
    result = _ok(lost=True)
    assert result.valid is False
    assert result.reason == "odometrie_tracking_verloren"


def test_lost_flag_takes_priority_over_covariance():
    # Auftrag Abschnitt 7: Tracking-Verlust muss IMMER erkannt werden,
    # unabhaengig davon, was die Kovarianz gerade sagt.
    result = _ok(lost=True, translation_variance=0.0001)
    assert result.valid is False
    assert result.reason == "odometrie_tracking_verloren"


def test_high_covariance_is_invalid():
    result = _ok(translation_variance=1.0, max_translation_variance=0.05)
    assert result.valid is False
    assert "odometrie_kovarianz_zu_hoch" in result.reason


def test_too_few_inliers_is_invalid():
    result = _ok(inliers=2, min_inliers=10)
    assert result.valid is False
    assert "odometrie_zu_wenig_inliers" in result.reason


def test_inlier_check_is_optional():
    result = _ok(inliers=None, min_inliers=None)
    assert result.valid is True


def test_max_translation_variance_picks_the_largest_diagonal_axis():
    covariance = [0.0] * 36
    covariance[0] = 0.01   # x
    covariance[7] = 0.5    # y -- der groesste Ausreisser
    covariance[14] = 0.02  # z
    assert max_translation_variance_from_covariance(covariance) == 0.5


def test_max_translation_variance_all_zero():
    covariance = [0.0] * 36
    assert max_translation_variance_from_covariance(covariance) == 0.0
