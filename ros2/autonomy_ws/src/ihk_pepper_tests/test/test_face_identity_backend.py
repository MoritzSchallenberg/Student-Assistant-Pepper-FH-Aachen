"""
Tests fuer face_identity_backend.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 7).

EHRLICHER STAND: kein echtes ONNX-Gesichtserkennungsmodell in dieser
Session verfuegbar (auch das `onnx`-Paket zum SELBST-BAUEN eines
Test-Modells ist nicht installiert, nur die Laufzeitbibliothek
onnxruntime) -- LocalOnnxIdentityBackend wird deshalb NUR in seinem
fail-closed-Konstruktionspfad (fehlende Modelldatei) getestet, plus
seine beiden reinen Hilfsfunktionen (_bbox_center_gaze_score/
_resize_nearest) direkt und ohne echte Modell-Inferenz. Der eigentliche
ONNX-Inferenzpfad bleibt hwverificationrequired, siehe Klassendoku in
face_identity_backend.py und docs/FACE_IDENTITY_AND_PRIVACY.md.
"""
import numpy as np
import pytest

from ihk_pepper_identity.face_identity_backend import (
    DisabledIdentityBackend,
    FaceEmbeddingResult,
    FaceIdentityModelNotFoundError,
    LocalOnnxIdentityBackend,
    MockIdentityBackend,
    TransientFaceObservation,
    _bbox_center_gaze_score,
    _resize_nearest,
)


# ---- DisabledIdentityBackend ----

def test_disabled_backend_transient_reports_disabled_for_every_bbox():
    backend = DisabledIdentityBackend()
    observations = backend.observe_transient(None, [(0, 0, 50, 50), (10, 10, 40, 40)])
    assert len(observations) == 2
    for obs in observations:
        assert obs.face_visible is False
        assert obs.reason == "identity_backend_disabled"


def test_disabled_backend_persistent_never_returns_an_embedding():
    backend = DisabledIdentityBackend()
    result = backend.identify_persistent(None, (0, 0, 50, 50))
    assert result.embedding is None
    assert result.valid is False
    assert result.reason == "identity_backend_disabled"


# ---- MockIdentityBackend ----

def test_mock_backend_with_fixed_results():
    fixed_obs = [TransientFaceObservation(0, 0, 50, 50, True, True, 0.9)]
    fixed_persistent = FaceEmbeddingResult(embedding=b"\x00" * 8, valid=True, confidence=1.0)
    backend = MockIdentityBackend(fixed_transient=fixed_obs, fixed_persistent=fixed_persistent)
    assert backend.observe_transient(None, []) == fixed_obs
    assert backend.identify_persistent(None, (0, 0, 1, 1)) == fixed_persistent


def test_mock_backend_with_result_fn():
    backend = MockIdentityBackend(
        transient_fn=lambda image, bboxes: [
            TransientFaceObservation(x, y, w, h, True, True, 0.5) for x, y, w, h in bboxes
        ],
    )
    result = backend.observe_transient(None, [(1, 2, 3, 4)])
    assert len(result) == 1
    assert result[0].bbox_x == 1


def test_mock_backend_without_any_fixture_returns_safe_defaults():
    backend = MockIdentityBackend()
    assert backend.observe_transient(None, [(0, 0, 1, 1)]) == []
    result = backend.identify_persistent(None, (0, 0, 1, 1))
    assert result.valid is False


# ---- LocalOnnxIdentityBackend: fail-closed construction ----

def test_missing_model_file_raises_fail_closed():
    with pytest.raises(FaceIdentityModelNotFoundError):
        LocalOnnxIdentityBackend(model_path="/nonexistent/model.onnx")


def test_empty_model_path_raises_fail_closed():
    with pytest.raises(FaceIdentityModelNotFoundError):
        LocalOnnxIdentityBackend(model_path="")


def test_directory_instead_of_file_raises_fail_closed(tmp_path):
    with pytest.raises(FaceIdentityModelNotFoundError):
        LocalOnnxIdentityBackend(model_path=str(tmp_path))


# ---- Reine Hilfsfunktionen (kein Modell noetig) ----

def test_gaze_score_is_highest_at_the_image_center():
    center_score = _bbox_center_gaze_score(320 - 25, 240 - 25, 50, 50, 640, 480, 0.35)
    corner_score = _bbox_center_gaze_score(0, 0, 50, 50, 640, 480, 0.35)
    assert center_score > corner_score
    assert center_score == pytest.approx(1.0, abs=1e-6)


def test_gaze_score_is_zero_for_unknown_image_dimensions():
    assert _bbox_center_gaze_score(0, 0, 50, 50, 0, 0, 0.35) == 0.0


def test_gaze_score_is_bounded_between_zero_and_one():
    for x, y in [(0, 0), (600, 400), (300, 200)]:
        score = _bbox_center_gaze_score(x, y, 50, 50, 640, 480, 0.35)
        assert 0.0 <= score <= 1.0


def test_resize_nearest_produces_the_requested_output_shape():
    src = np.arange(20 * 30 * 3, dtype=np.uint8).reshape(20, 30, 3)
    resized = _resize_nearest(src, (112, 112))
    assert resized.shape == (112, 112, 3)


def test_resize_nearest_rejects_empty_crop():
    with pytest.raises(ValueError):
        _resize_nearest(np.zeros((0, 0, 3), dtype=np.uint8), (112, 112))


def test_resize_nearest_preserves_pixel_values_on_upscale_of_uniform_image():
    src = np.full((10, 10, 3), 42, dtype=np.uint8)
    resized = _resize_nearest(src, (112, 112))
    assert (resized == 42).all()
