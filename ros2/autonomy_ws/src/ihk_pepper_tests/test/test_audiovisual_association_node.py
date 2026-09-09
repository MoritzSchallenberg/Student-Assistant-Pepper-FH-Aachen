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

    def to_msg(self):
        from builtin_interfaces.msg import Time as TimeMsg
        stamp = TimeMsg()
        stamp.sec = int(self.nanoseconds // 1_000_000_000)
        stamp.nanosec = int(self.nanoseconds % 1_000_000_000)
        return stamp


class _FakeClock:
    def __init__(self, now_s):
        self._now_s = now_s

    def now(self):
        return _FakeNowResult(int(self._now_s * 1e9))


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeNode:
    _on_tracks = AudiovisualAssociationNode._on_tracks
    _build_candidates = AudiovisualAssociationNode._build_candidates
    _publish_visual_target = AudiovisualAssociationNode._publish_visual_target
    _handle_associate = AudiovisualAssociationNode._handle_associate

    def __init__(self, now_s=1000.0, params=None):
        self._latest_tracks = None
        self._latest_tracks_received_at = None
        self._now_s = now_s
        self.visual_target_pub = _FakePublisher()
        self._params = params or {
            "maximum_track_age_s": 0.5,
            "minimum_track_confidence": 0.70,
            "maximum_angular_error_deg": 20.0,
            "minimum_ambiguity_margin_deg": 10.0,
            "base_frame": "base_link",
            "required_source_camera": "realsense",
        }

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock(self._now_s)


def _make_track(track_id=1, confidence=0.9, has_3d=True, x=1.0, y=0.0, stable=True,
                 last_seen_s=1000.0, frame_id="base_link", source_camera="realsense",
                 distance_m=0.0):
    t = PersonTrack()
    t.track_id = track_id
    t.confidence = confidence
    t.has_3d_position = has_3d
    t.position_3d.x = x
    t.position_3d.y = y
    t.stable = stable
    t.last_seen.sec = int(last_seen_s)
    t.last_seen.nanosec = int((last_seen_s % 1) * 1e9)
    t.frame_id = frame_id
    t.source_camera = source_camera
    t.distance_m = distance_m
    return t


def _associate_request(azimuth_rad=0.0, measured_at_s=1000.0, max_measurement_age_s=3.0,
                        event_id=""):
    req = AssociatePersonWithSound.Request()
    req.sound_azimuth_rad = azimuth_rad
    req.measured_at.sec = int(measured_at_s)
    req.measured_at.nanosec = int((measured_at_s % 1) * 1e9)
    req.max_measurement_age_s = max_measurement_age_s
    req.event_id = event_id
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


def test_track_from_wrong_frame_is_excluded_via_node_params():
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 11.
    node = _FakeNode(now_s=1000.0)
    array = PersonTrackArray()
    array.tracks = [_make_track(track_id=1, x=1.0, y=0.0, last_seen_s=1000.0,
                                 frame_id="camera_color_optical_frame")]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1000.0
    response = node._handle_associate(
        _associate_request(azimuth_rad=0.0), AssociatePersonWithSound.Response())
    assert response.valid is False


# ---- /audio/visual_target (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4) ----

def test_visual_target_is_published_on_no_tracks_received():
    node = _FakeNode()
    node._handle_associate(_associate_request(event_id="evt-1"), AssociatePersonWithSound.Response())
    assert len(node.visual_target_pub.messages) == 1
    out = node.visual_target_pub.messages[0]
    assert out.valid is False
    assert out.track_id == -1
    assert out.event_id == "evt-1"
    assert out.reason == "keine_personentracks_empfangen"


def test_visual_target_is_published_on_stale_measurement():
    node = _FakeNode(now_s=1010.0)
    array = PersonTrackArray()
    array.tracks = [_make_track(last_seen_s=1010.0)]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1010.0
    node._handle_associate(
        _associate_request(measured_at_s=1000.0, max_measurement_age_s=3.0, event_id="evt-2"),
        AssociatePersonWithSound.Response(),
    )
    out = node.visual_target_pub.messages[0]
    assert out.valid is False
    assert out.track_id == -1
    assert out.event_id == "evt-2"


def test_visual_target_carries_selected_track_azimuth_distance_and_confidence():
    node = _FakeNode(now_s=1000.0)
    array = PersonTrackArray()
    array.tracks = [_make_track(track_id=5, x=1.0, y=0.0, last_seen_s=1000.0,
                                 confidence=0.85, distance_m=2.5)]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1000.0
    node._handle_associate(
        _associate_request(azimuth_rad=0.0, event_id="evt-3"), AssociatePersonWithSound.Response())
    out = node.visual_target_pub.messages[0]
    assert out.valid is True
    assert out.track_id == 5
    assert out.event_id == "evt-3"
    assert out.distance_m == 2.5
    assert out.confidence == 0.85


def test_visual_target_is_published_even_for_an_ambiguous_rejection():
    node = _FakeNode(now_s=1000.0)
    array = PersonTrackArray()
    array.tracks = [
        _make_track(track_id=1, x=1.0, y=0.0, last_seen_s=1000.0),
        _make_track(track_id=2, x=1.0, y=0.02, last_seen_s=1000.0),
    ]
    node._on_tracks(array)
    node._latest_tracks_received_at = 1000.0
    node._handle_associate(
        _associate_request(azimuth_rad=0.0, event_id="evt-4"), AssociatePersonWithSound.Response())
    assert len(node.visual_target_pub.messages) == 1
    out = node.visual_target_pub.messages[0]
    assert out.valid is False
    assert out.track_id == -1
    assert out.event_id == "evt-4"
