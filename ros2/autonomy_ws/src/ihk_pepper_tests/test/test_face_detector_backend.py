"""
Tests fuer face_detector_backend.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 5).
"""
import os
import tempfile

import pytest

from ihk_pepper_identity.face_detector_backend import (
    DisabledFaceDetector,
    FaceDetection,
    FaceDetectorBackendError,
    FaceDetectorModelNotFoundError,
    LocalOnnxFaceDetector,
    MockFaceDetector,
)


def test_disabled_detector_never_finds_a_face():
    detector = DisabledFaceDetector()
    assert detector.detect(image=object(), timestamp=1.0) == []


def test_mock_detector_returns_fixed_detections():
    det = FaceDetection(
        bbox_x=1, bbox_y=2, bbox_width=3, bbox_height=4, confidence=0.9,
        measured_at_s=5.0, backend_name="mock",
    )
    detector = MockFaceDetector(fixed_detections=[det])
    result = detector.detect(image=object(), timestamp=5.0)
    assert result == [det]


def test_mock_detector_uses_injected_function():
    calls = []

    def _fn(image, timestamp):
        calls.append(timestamp)
        return []

    detector = MockFaceDetector(detect_fn=_fn)
    detector.detect(image=object(), timestamp=42.0)
    assert calls == [42.0]


def test_local_onnx_detector_fails_closed_on_missing_model_file():
    with pytest.raises(FaceDetectorModelNotFoundError):
        LocalOnnxFaceDetector(model_path="/nonexistent/model.onnx")


def test_local_onnx_detector_fails_closed_on_empty_path():
    with pytest.raises(FaceDetectorModelNotFoundError):
        LocalOnnxFaceDetector(model_path="")


def test_local_onnx_detector_fails_closed_on_directory_instead_of_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(FaceDetectorModelNotFoundError):
            LocalOnnxFaceDetector(model_path=tmpdir)


def test_face_detection_has_no_gaze_field_only_centering_score():
    # Terminologie-Grenze aus Auftrag Abschnitt 5/6: kein Feld darf
    # "gaze"/"blickrichtung" im FaceDetection-Vertrag heissen.
    fields = FaceDetection.__dataclass_fields__.keys()
    assert not any("gaze" in f.lower() for f in fields)
    assert "face_centering_score" in fields
