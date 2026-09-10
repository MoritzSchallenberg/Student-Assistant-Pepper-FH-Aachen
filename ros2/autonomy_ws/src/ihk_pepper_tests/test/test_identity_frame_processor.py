"""
Tests fuer identity_frame_processor.py (Entwicklungsauftrag 04-B,
AP7.1, Abschnitt 6).
"""
import numpy as np
import pytest

from ihk_pepper_identity.face_detector_backend import FaceDetection
from ihk_pepper_identity.face_identity_backend import FaceEmbeddingResult
from ihk_pepper_identity.face_track_association import TrackBoundingBox
from ihk_pepper_identity.identity_frame_processor import IdentityFrameConfig, process_frame
from ihk_pepper_identity.persistent_identity_confirmer import PersistentIdentityConfirmer


def _face(x=0, y=0, w=10, h=10):
    return FaceDetection(bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                          confidence=0.9, measured_at_s=1.0, backend_name="mock")


def _track(track_id=1, x=0, y=0, w=10, h=10, distance_m=1.0, depth_confidence=0.9, has_3d=True):
    return TrackBoundingBox(track_id=track_id, bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                             has_3d_position=has_3d, distance_m=distance_m, depth_confidence=depth_confidence)


class _FakeIdentityBackend:
    def __init__(self, embedding=b"", valid=True, reason=""):
        self._embedding = embedding
        self._valid = valid
        self._reason = reason

    def observe_transient(self, image, face_bboxes):
        raise NotImplementedError

    def identify_persistent(self, image, face_bbox):
        return FaceEmbeddingResult(
            embedding=self._embedding if self._valid else None,
            valid=self._valid, confidence=1.0, reason=self._reason)


def _embedding_for(value: float, dims: int = 4) -> bytes:
    return np.array([value] * dims, dtype=np.float32).tobytes()


def _live_depth_values():
    # Genuegend gueltige, streuende Tiefenwerte -- besteht check_liveness().
    return [1.0, 1.01, 1.02, 0.99, 0.98, 1.03, 1.0, 0.97, 1.04, 1.0,
            1.02, 0.99, 1.01, 1.0, 0.98, 1.03, 1.0, 1.02, 0.99, 1.01]


def _flat_depth_values():
    return [1.0] * 25  # keine Streuung -- besteht check_liveness() NICHT


def _default_config(**overrides):
    return IdentityFrameConfig(**overrides)


def _process(tracks, faces, identity_backend, confirmer=None, candidates=None,
             consent=True, depth_values=None, config=None):
    confirmer = confirmer or PersistentIdentityConfirmer(
        required_consecutive_matches=1, now_fn=lambda: 1000.0)
    candidates_fn = lambda: (candidates or [])
    consent_fn = lambda person_id: consent
    depth_fn = lambda face: (depth_values if depth_values is not None else _live_depth_values())
    return process_frame(
        tracks=tracks, faces=faces, depth_patch_fn=depth_fn,
        identity_backend=identity_backend, confirmer=confirmer,
        template_candidates_fn=candidates_fn, consent_lookup_fn=consent_fn,
        image=object(), now_s=1000.0, config=config or _default_config(),
    )


def test_track_without_a_matched_face_falls_back_to_unknown():
    track = _track()
    results = _process([track], faces=[], identity_backend=_FakeIdentityBackend())
    assert results[0].known is False
    assert results[0].reason == "kein_gesicht_eindeutig_zugeordnet"


def test_track_with_implausible_depth_falls_back_to_unknown():
    track = _track(has_3d=False)
    face = _face()
    results = _process([track], [face], identity_backend=_FakeIdentityBackend())
    assert results[0].known is False
    assert results[0].reason == "tiefe_nicht_plausibel"


def test_track_failing_liveness_falls_back_to_unknown():
    track = _track()
    face = _face()
    results = _process([track], [face], identity_backend=_FakeIdentityBackend(),
                        depth_values=_flat_depth_values())
    assert results[0].known is False
    assert results[0].liveness_passed is False
    assert results[0].reason.startswith("liveness:")


def test_failed_embedding_falls_back_to_unknown():
    track = _track()
    face = _face()
    backend = _FakeIdentityBackend(valid=False, reason="inferenz_fehlgeschlagen")
    results = _process([track], [face], identity_backend=backend)
    assert results[0].known is False
    assert results[0].liveness_passed is True
    assert "einbettung" in results[0].reason


def test_unconfirmed_single_frame_match_stays_unknown():
    track = _track()
    face = _face()
    embedding = _embedding_for(1.0)
    backend = _FakeIdentityBackend(embedding=embedding)
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=3, now_fn=lambda: 1000.0)
    results = _process(
        [track], [face], identity_backend=backend, confirmer=confirmer,
        candidates=[("p1", embedding)],
    )
    assert results[0].known is False
    assert results[0].reason == "noch_nicht_mehrfach_bestaetigt"


def test_confirmed_match_with_consent_is_known():
    track = _track()
    face = _face()
    embedding = _embedding_for(1.0)
    backend = _FakeIdentityBackend(embedding=embedding)
    results = _process(
        [track], [face], identity_backend=backend,
        candidates=[("p1", embedding)], consent=True,
    )
    assert results[0].known is True
    assert results[0].person_id == "p1"
    assert results[0].consent_granted is True


def test_confirmed_match_without_consent_falls_back_to_unknown():
    track = _track()
    face = _face()
    embedding = _embedding_for(1.0)
    backend = _FakeIdentityBackend(embedding=embedding)
    results = _process(
        [track], [face], identity_backend=backend,
        candidates=[("p1", embedding)], consent=False,
    )
    assert results[0].known is False
    assert results[0].reason == "einwilligung_widerrufen_oder_fehlend"


def test_consent_revocation_clears_the_confirmer_state():
    # Nachdem der Consent-Widerruf erkannt wurde, darf ein spaeterer
    # Frame NICHT sofort wieder als bestaetigt gelten, ohne die
    # Mehrframe-Bestaetigung erneut zu durchlaufen.
    track = _track()
    face = _face()
    embedding = _embedding_for(1.0)
    backend = _FakeIdentityBackend(embedding=embedding)
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=1, now_fn=lambda: 1000.0)

    consent_flags = {"granted": True}
    candidates_fn = lambda: [("p1", embedding)]
    consent_fn = lambda person_id: consent_flags["granted"]
    depth_fn = lambda face: _live_depth_values()

    r1 = process_frame(
        tracks=[track], faces=[face], depth_patch_fn=depth_fn, identity_backend=backend,
        confirmer=confirmer, template_candidates_fn=candidates_fn, consent_lookup_fn=consent_fn,
        image=object(), now_s=1000.0, config=_default_config(),
    )
    assert r1[0].known is True

    consent_flags["granted"] = False
    r2 = process_frame(
        tracks=[track], faces=[face], depth_patch_fn=depth_fn, identity_backend=backend,
        confirmer=confirmer, template_candidates_fn=candidates_fn, consent_lookup_fn=consent_fn,
        image=object(), now_s=1001.0, config=_default_config(),
    )
    assert r2[0].known is False
    assert r2[0].reason == "einwilligung_widerrufen_oder_fehlend"
    assert confirmer.is_confirmed(track.track_id) is False


def test_result_carries_a_finite_expiry():
    track = _track()
    results = _process([track], faces=[], identity_backend=_FakeIdentityBackend())
    assert results[0].valid_until_s == pytest.approx(1000.0 + IdentityFrameConfig().result_validity_s)


def test_ambiguous_face_track_association_falls_back_to_unknown():
    track = _track(x=0, y=0, w=10, h=10)
    face_a = _face(0, 0, 10, 10)
    face_b = _face(1, 0, 10, 10)
    results = _process(
        [track], [face_a, face_b], identity_backend=_FakeIdentityBackend(),
        config=_default_config(ambiguity_margin=0.5),
    )
    assert results[0].known is False
    assert results[0].reason == "kein_gesicht_eindeutig_zugeordnet"
