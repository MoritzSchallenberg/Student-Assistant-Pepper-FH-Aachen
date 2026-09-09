"""
Tests fuer audiovisual_association_node.py (Entwicklungsauftrag 04-B,
AP6, Abschnitt 13). Gleiches Duck-Typing-Muster wie
test_orient_to_sound_node.py -- die ECHTEN, ungebundenen Methoden von
AudiovisualAssociationNode laufen gegen ein leichtgewichtiges Fake.
"""
from ihk_pepper_perception.audiovisual_association_node import AudiovisualAssociationNode
from ihk_pepper_interfaces.msg import PersonTrack, PersonTrackArray
from ihk_pepper_interfaces.srv import AssociatePersonWithSound


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def info(self, *a, **kw):
        pass


class _FakeNowResult:
    def __init__(self, nanoseconds):
        self.nanoseconds = nanoseconds


class _FakeClock:
    def __init__(self, now_s):
        self._now_s = now_s

    def now(self):
        return _FakeNowResult(int(self._now_s * 1e9))


class _FakeNode:
    _on_tracks = AudiovisualAssociationNode._on_tracks
    _build_candidates = AudiovisualAssociationNode._build_candidates
    _handle_associate = AudiovisualAssociationNode._handle_associate

    def __init__(self, now_s=1000.0, params=None):
        self._latest_tracks = None
        self._latest_tracks_received_at = None
        self._now_s = now_s
        self._params = params or {
            "maximum_track_age_s": 0.5,
            "minimum_track_confidence": 0.70,
            "maximum_angular_error_deg": 20.0,
            "minimum_ambiguity_margin_deg": 10.0,
        }

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock(self._now_s)


def _make_track(track_id=1, confidence=0.9, has_3d=True, x=1.0, y=0.0, stable=True,
                 last_seen_s=1000.0):
    t = PersonTrack()
    t.track_id = track_id
    t.confidence = confidence
    t.has_3d_position = has_3d
    t.position_3d.x = x
    t.position_3d.y = y
    t.stable = stable
    t.last_seen.sec = int(last_seen_s)
    t.last_seen.nanosec = int((last_seen_s % 1) * 1e9)
    return t


def _associate_request(azimuth_rad=0.0, measured_at_s=1000.0, max_measurement_age_s=3.0):
    req = AssociatePersonWithSound.Request()
    req.sound_azimuth_rad = azimuth_rad
    req.measured_at.sec = int(measured_at_s)
    req.measured_at.nanosec = int((measured_at_s % 1) * 1e9)
    req.max_measurement_age_s = max_measurement_age_s
    return req


def test_no_tracks_ever_received_returns_invalid():
    node = _FakeNode()
    response = node._handle_associate(_associate_request(), AssociatePersonWithSound.Response())
    assert response.valid is False
    assert response.selected_track_id == -1
    assert response.reason == "keine_personentracks_empfangen"


def test_stale_measurement_is_rejected():
    node = _FakeNode(now_s=1010.0)
    array = PersonTrackArray()
    array.tracks = [_make_track(last_seen_s=1010.0)]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1010.0
    response = node._handle_associate(
        _associate_request(measured_at_s=1000.0, max_measurement_age_s=3.0),
        AssociatePersonWithSound.Response(),
    )
    assert response.valid is False
    assert "zu_alt" in response.reason


def test_single_matching_track_is_selected():
    node = _FakeNode(now_s=1000.0)
    array = PersonTrackArray()
    array.tracks = [_make_track(track_id=5, x=1.0, y=0.0, last_seen_s=1000.0)]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1000.0
    response = node._handle_associate(
        _associate_request(azimuth_rad=0.0), AssociatePersonWithSound.Response())
    assert response.valid is True
    assert response.selected_track_id == 5


def test_two_ambiguous_tracks_selects_nobody():
    node = _FakeNode(now_s=1000.0)
    array = PersonTrackArray()
    array.tracks = [
        _make_track(track_id=1, x=1.0, y=0.0, last_seen_s=1000.0),
        _make_track(track_id=2, x=1.0, y=0.02, last_seen_s=1000.0),
    ]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1000.0
    response = node._handle_associate(
        _associate_request(azimuth_rad=0.0), AssociatePersonWithSound.Response())
    assert response.valid is False
    assert response.reason == "mehrdeutig"


def test_stale_track_last_seen_is_excluded_via_age_computation():
    node = _FakeNode(now_s=1005.0)  # 5s nach last_seen
    array = PersonTrackArray()
    array.tracks = [_make_track(track_id=1, x=1.0, y=0.0, last_seen_s=1000.0)]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1000.0
    response = node._handle_associate(
        _associate_request(azimuth_rad=0.0, measured_at_s=1005.0),
        AssociatePersonWithSound.Response(),
    )
    assert response.valid is False
