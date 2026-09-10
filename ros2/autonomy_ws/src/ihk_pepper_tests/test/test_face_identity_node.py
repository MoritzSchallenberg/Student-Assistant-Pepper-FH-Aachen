"""
Tests fuer face_identity_node.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 6). Gleiches Duck-Typing-Muster wie test_person_approach_node_follow.py
-- die ECHTEN, ungebundenen Methoden von FaceIdentityNode laufen gegen
ein leichtgewichtiges Fake, kein rclpy.init() noetig. Biometrischer
Speicher/Registry laufen echt gegen eine temporaere Datei (kein Mock
noetig, beides ist bereits reine SQLite-/Datei-Logik ohne ROS).
"""
import time
import types

import numpy as np
import pytest

from ihk_pepper_identity.biometric_template_store import BiometricTemplateStore
from ihk_pepper_identity.face_detector_backend import (
    DisabledFaceDetector,
    FaceDetectorModelNotFoundError,
    MockFaceDetector,
)
from ihk_pepper_identity.face_identity_backend import DisabledIdentityBackend, MockIdentityBackend
from ihk_pepper_identity.face_identity_node import (
    FaceIdentityNode,
    _build_face_detector,
    _build_identity_backend,
)
from ihk_pepper_person_memory.identity_registry_db import ConsentStatus, IdentityRegistryStore


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass


def _fake_node_with_params(**params):
    node = types.SimpleNamespace()
    node._params = params
    node.get_parameter = lambda name: _FakeParam(node._params[name])
    node.get_logger = lambda: _FakeLogger()
    return node


# ---- _build_face_detector / _build_identity_backend ----

def test_build_face_detector_defaults_to_disabled():
    node = _fake_node_with_params(face_detector_kind="anything_unexpected")
    assert isinstance(_build_face_detector(node), DisabledFaceDetector)


def test_build_face_detector_mock():
    node = _fake_node_with_params(face_detector_kind="mock")
    assert isinstance(_build_face_detector(node), MockFaceDetector)


def test_build_face_detector_falls_back_to_disabled_on_missing_model():
    node = _fake_node_with_params(
        face_detector_kind="local_onnx", face_detector_model_path="/no/such/model.onnx",
        face_detector_minimum_confidence=0.5,
    )
    assert isinstance(_build_face_detector(node), DisabledFaceDetector)


def test_build_identity_backend_defaults_to_disabled():
    node = _fake_node_with_params(identity_backend_kind="unknown")
    assert isinstance(_build_identity_backend(node), DisabledIdentityBackend)


def test_build_identity_backend_mock():
    node = _fake_node_with_params(identity_backend_kind="mock")
    assert isinstance(_build_identity_backend(node), MockIdentityBackend)


def test_build_identity_backend_falls_back_to_disabled_on_missing_model():
    node = _fake_node_with_params(
        identity_backend_kind="local_onnx", identity_backend_model_path="/no/such/model.onnx")
    assert isinstance(_build_identity_backend(node), DisabledIdentityBackend)


# ---- _current_tracks ----

class _FakeNode:
    _current_tracks = FaceIdentityNode._current_tracks
    _consent_lookup = FaceIdentityNode._consent_lookup
    _template_candidates = FaceIdentityNode._template_candidates
    _depth_patch = staticmethod(FaceIdentityNode._depth_patch)

    def __init__(self, params=None, tracks_msg=None, tracks_received_s=None,
                 biometric_store=None, identity_registry=None):
        self._params = params or {"person_tracks_max_age_s": 1.0}
        self._latest_tracks = tracks_msg
        self._latest_tracks_received_s = tracks_received_s or 0.0
        self._biometric_store = biometric_store
        self._identity_registry = identity_registry

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


def _track_msg(track_id=1, x=0, y=0, w=10, h=10, has_3d=True, distance_m=1.0, depth_confidence=0.9):
    return types.SimpleNamespace(
        track_id=track_id, bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
        has_3d_position=has_3d, distance_m=distance_m, depth_confidence=depth_confidence,
    )


def test_current_tracks_empty_without_any_message():
    node = _FakeNode()
    assert node._current_tracks() == []


def test_current_tracks_empty_when_stale(monkeypatch):
    msg = types.SimpleNamespace(tracks=[_track_msg()])
    node = _FakeNode(tracks_msg=msg, tracks_received_s=time.time() - 10.0)
    assert node._current_tracks() == []


def test_current_tracks_returns_fresh_tracks():
    msg = types.SimpleNamespace(tracks=[_track_msg(track_id=7)])
    node = _FakeNode(tracks_msg=msg, tracks_received_s=time.time())
    result = node._current_tracks()
    assert len(result) == 1
    assert result[0].track_id == 7


# ---- _consent_lookup / _template_candidates (echte Registry/Store) ----

@pytest.fixture()
def _registry(tmp_path):
    store = IdentityRegistryStore(str(tmp_path / "identities.db"))
    yield store
    store.close()


@pytest.fixture()
def _biometric_store(tmp_path):
    store = BiometricTemplateStore(
        db_path=str(tmp_path / "biometric.db"), key_path=str(tmp_path / "key.bin"))
    yield store
    store.close()


def test_consent_lookup_false_without_a_registry():
    node = _FakeNode(identity_registry=None)
    assert node._consent_lookup("p1") is False


def test_consent_lookup_false_for_an_empty_person_id(_registry):
    node = _FakeNode(identity_registry=_registry)
    assert node._consent_lookup("") is False


def test_consent_lookup_true_only_when_granted(_registry):
    _registry.create_or_touch("p1")
    _registry.set_consent("p1", ConsentStatus.GRANTED.value, reason="test")
    node = _FakeNode(identity_registry=_registry)
    assert node._consent_lookup("p1") is True


def test_consent_lookup_false_when_not_granted(_registry):
    _registry.create_or_touch("p1")
    node = _FakeNode(identity_registry=_registry)  # consent_status default "not_asked"
    assert node._consent_lookup("p1") is False


def test_template_candidates_empty_without_store_or_registry():
    assert _FakeNode(biometric_store=None, identity_registry=None)._template_candidates() == []


def test_template_candidates_only_include_consented_persons(_registry, _biometric_store):
    _registry.create_or_touch("consented")
    _registry.set_consent("consented", ConsentStatus.GRANTED.value, reason="test")
    _registry.create_or_touch("revoked")
    _registry.set_consent("revoked", ConsentStatus.GRANTED.value, reason="test")
    _registry.set_consent("revoked", ConsentStatus.WITHDRAWN.value, reason="widerruf")

    emb_consented = np.array([1.0, 2.0], dtype=np.float32).tobytes()
    emb_revoked = np.array([3.0, 4.0], dtype=np.float32).tobytes()
    _biometric_store.store_template("consented", emb_consented)
    _biometric_store.store_template("revoked", emb_revoked)

    node = _FakeNode(biometric_store=_biometric_store, identity_registry=_registry)
    candidates = node._template_candidates()
    person_ids = [pid for pid, _emb in candidates]
    assert "consented" in person_ids
    assert "revoked" not in person_ids


# ---- _depth_patch ----

def test_depth_patch_empty_without_a_depth_image():
    assert FaceIdentityNode._depth_patch(None, 1.0, types.SimpleNamespace(
        bbox_x=0, bbox_y=0, bbox_width=1, bbox_height=1)) == []


def test_depth_patch_extracts_scaled_values_within_bounds():
    depth_image = np.array([[1000, 2000], [3000, 4000]], dtype=np.uint16)
    face = types.SimpleNamespace(bbox_x=0, bbox_y=0, bbox_width=2, bbox_height=2)
    values = FaceIdentityNode._depth_patch(depth_image, 0.001, face)
    assert sorted(values) == [1.0, 2.0, 3.0, 4.0]


def test_depth_patch_clips_to_image_bounds():
    depth_image = np.array([[1000, 2000], [3000, 4000]], dtype=np.uint16)
    face = types.SimpleNamespace(bbox_x=1, bbox_y=1, bbox_width=10, bbox_height=10)
    values = FaceIdentityNode._depth_patch(depth_image, 0.001, face)
    assert values == [4.0]
