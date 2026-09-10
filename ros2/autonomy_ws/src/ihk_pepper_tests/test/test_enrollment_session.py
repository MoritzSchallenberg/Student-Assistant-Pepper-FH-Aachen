"""
Tests fuer enrollment_session.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 7).
"""
import numpy as np

from ihk_pepper_identity.enrollment_session import EnrollmentState, observe_enrollment_frame


def _embedding(value: float, dims: int = 4) -> bytes:
    return np.array([value] * dims, dtype=np.float32).tobytes()


def _state(required=3, similarity=0.9):
    return EnrollmentState(
        person_id="p1", required_observations=required, minimum_consistency_similarity=similarity)


def test_frame_with_no_visible_person_is_skipped_not_failed():
    state = _state()
    observe_enrollment_frame(state, num_visible_tracks=0, liveness_passed=True, embedding=_embedding(1.0))
    assert state.completed is False
    assert state.failed is False
    assert state.embeddings == []


def test_frame_with_multiple_visible_people_is_skipped_not_failed():
    state = _state()
    observe_enrollment_frame(state, num_visible_tracks=2, liveness_passed=True, embedding=_embedding(1.0))
    assert state.completed is False
    assert state.failed is False


def test_frame_failing_liveness_does_not_count():
    state = _state()
    observe_enrollment_frame(state, num_visible_tracks=1, liveness_passed=False, embedding=_embedding(1.0))
    assert state.embeddings == []
    assert state.failed is False


def test_frame_without_an_embedding_does_not_count():
    state = _state()
    observe_enrollment_frame(state, num_visible_tracks=1, liveness_passed=True, embedding=None)
    assert state.embeddings == []


def test_completes_after_required_consistent_observations():
    state = _state(required=3)
    for _ in range(3):
        observe_enrollment_frame(state, 1, True, _embedding(1.0))
    assert state.completed is True
    assert state.failed is False
    assert len(state.embeddings) == 3


def test_inconsistent_embedding_fails_the_whole_session():
    state = _state(required=3, similarity=0.99)
    observe_enrollment_frame(state, 1, True, _embedding(1.0))
    observe_enrollment_frame(state, 1, True, _embedding(-1.0))  # entgegengesetzter Vektor
    assert state.failed is True
    assert state.fail_reason == "unterschiedliche_personen_erkannt"
    assert state.completed is False


def test_a_completed_session_ignores_further_frames():
    state = _state(required=1)
    observe_enrollment_frame(state, 1, True, _embedding(1.0))
    assert state.completed is True
    observe_enrollment_frame(state, 1, True, _embedding(-1.0))
    assert len(state.embeddings) == 1  # unveraendert -- kein weiterer Frame gezaehlt


def test_a_failed_session_ignores_further_frames():
    state = _state(required=3, similarity=0.99)
    observe_enrollment_frame(state, 1, True, _embedding(1.0))
    observe_enrollment_frame(state, 1, True, _embedding(-1.0))
    assert state.failed is True
    observe_enrollment_frame(state, 1, True, _embedding(1.0))
    assert len(state.embeddings) == 1


def test_final_embedding_is_none_before_completion():
    state = _state(required=3)
    observe_enrollment_frame(state, 1, True, _embedding(1.0))
    assert state.final_embedding() is None


def test_final_embedding_is_the_mean_of_collected_embeddings():
    state = _state(required=2, similarity=0.5)
    observe_enrollment_frame(state, 1, True, _embedding(1.0))
    observe_enrollment_frame(state, 1, True, _embedding(3.0))
    assert state.completed is True
    final = np.frombuffer(state.final_embedding(), dtype=np.float32)
    assert np.allclose(final, [2.0, 2.0, 2.0, 2.0])
