"""
Tests fuer liveness.py (Entwicklungsauftrag 04-B, AP7, Abschnitt 7/8).
"""
import math

from ihk_pepper_identity.liveness import check_liveness


def _flat_depths(n=50, value=0.5):
    return [value] * n


def _varied_depths(n=50, base=0.5, spread=0.03):
    import random
    rng = random.Random(0)
    return [base + rng.uniform(-spread, spread) for _ in range(n)]


def test_perfectly_flat_depth_fails_liveness():
    result = check_liveness(_flat_depths(), minimum_depth_std_m=0.008)
    assert result.passed is False
    assert result.reason == "zu_flach_moeglicherweise_foto"
    assert result.depth_std_m == 0.0


def test_varied_depth_passes_liveness():
    result = check_liveness(_varied_depths(spread=0.03), minimum_depth_std_m=0.008)
    assert result.passed is True
    assert result.depth_std_m > 0.008


def test_too_few_valid_samples_fails_closed():
    result = check_liveness([0.5, 0.5, 0.5], minimum_valid_samples=20)
    assert result.passed is False
    assert result.reason == "zu_wenig_gueltige_tiefenwerte"


def test_invalid_depth_values_are_filtered_not_treated_as_zero():
    values = [0.5 + 0.01 * i for i in range(30)] + [float("nan"), -1.0, 0.0, None]
    result = check_liveness(values, minimum_valid_samples=20)
    # Die 30 gueltigen Werte reichen weiterhin -- die ungueltigen wurden
    # ausgefiltert, nicht als 0.0 in die Varianz eingerechnet.
    assert result.depth_std_m > 0.0
    assert math.isfinite(result.depth_std_m)


def test_empty_input_fails_closed():
    result = check_liveness([], minimum_valid_samples=20)
    assert result.passed is False
