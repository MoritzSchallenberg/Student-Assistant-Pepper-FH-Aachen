"""
Tests fuer identity_matching.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 7).
"""
import numpy as np
import pytest

from ihk_pepper_identity.identity_matching import match_embedding


def _embedding(*values):
    return np.asarray(values, dtype=np.float32).tobytes()


def test_no_candidates_never_matches():
    result = match_embedding(_embedding(1.0, 0.0), [])
    assert result.matched is False
    assert result.person_id is None
    assert result.reason == "keine_kandidaten"


def test_identical_embedding_matches_with_high_similarity():
    query = _embedding(1.0, 0.0, 0.0)
    result = match_embedding(query, [("p1", _embedding(1.0, 0.0, 0.0))])
    assert result.matched is True
    assert result.person_id == "p1"
    assert result.similarity == pytest.approx(1.0, abs=1e-5)


def test_dissimilar_embedding_is_rejected():
    query = _embedding(1.0, 0.0, 0.0)
    result = match_embedding(query, [("p1", _embedding(0.0, 1.0, 0.0))], minimum_similarity=0.55)
    assert result.matched is False
    assert result.reason == "keine_ausreichende_aehnlichkeit"


def test_two_almost_equally_good_candidates_are_rejected_as_ambiguous():
    query = _embedding(1.0, 0.0, 0.0)
    candidates = [
        ("p1", _embedding(0.99, 0.01, 0.0)),
        ("p2", _embedding(0.98, 0.02, 0.0)),
    ]
    result = match_embedding(query, candidates, minimum_similarity=0.5, minimum_margin=0.05)
    assert result.matched is False
    assert result.person_id is None
    assert result.reason == "mehrdeutig"


def test_clear_winner_among_multiple_candidates_is_accepted():
    query = _embedding(1.0, 0.0, 0.0)
    candidates = [
        ("p1", _embedding(1.0, 0.0, 0.0)),
        ("p2", _embedding(0.0, 1.0, 0.0)),
    ]
    result = match_embedding(query, candidates, minimum_similarity=0.5, minimum_margin=0.05)
    assert result.matched is True
    assert result.person_id == "p1"


def test_mismatched_embedding_dimensions_are_never_matched():
    query = _embedding(1.0, 0.0, 0.0)
    result = match_embedding(query, [("p1", _embedding(1.0, 0.0))], minimum_similarity=0.1)
    assert result.matched is False


def test_zero_vector_never_matches():
    query = _embedding(0.0, 0.0, 0.0)
    result = match_embedding(query, [("p1", _embedding(1.0, 0.0, 0.0))], minimum_similarity=0.0)
    assert result.matched is False
