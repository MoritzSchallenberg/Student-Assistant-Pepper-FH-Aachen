"""
Tests fuer group_tracking_node.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 14/15). Gleiches Duck-Typing-Muster wie
test_audiovisual_association_node.py.
"""
from ihk_pepper_perception.group_tracking import GroupTracker, GroupTrackingConfig
from ihk_pepper_perception.group_tracking_node import GroupTrackingNode
from ihk_pepper_interfaces.msg import AudioFocusState, PersonTrack, PersonTrackArray


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
        return "stamp"


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
    _on_tracks = GroupTrackingNode._on_tracks
    _on_focus_state = GroupTrackingNode._on_focus_state
    _build_candidates = GroupTrackingNode._build_candidates
    _tick = GroupTrackingNode._tick
    _publish = GroupTrackingNode._publish

    def __init__(self, now_s=1000.0, tracker=None, base_frame="base_link"):
        self._latest_tracks = None
        self._anchor_track_id = -1
        self.group_pub = _FakePublisher()
        self.tracker = tracker or GroupTracker(GroupTrackingConfig(
            join_hysteresis_s=0.0, minimum_stable_duration_s=0.0))
        self._now_s = now_s
        self._params = {
            "base_frame": base_frame,
            "camera_horizontal_fov_deg": 87.0,
        }

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_clock(self):
        return _FakeClock(self._now_s)

    def get_logger(self):
        return _FakeLogger()


def _person_track(track_id, x=0.0, y=0.0, stable=True, frame_id="base_link", last_seen_s=1000.0):
    t = PersonTrack()
    t.track_id = track_id
    t.has_3d_position = True
    t.position_3d.x = x
    t.position_3d.y = y
    t.stable = stable
    t.frame_id = frame_id
    t.last_seen.sec = int(last_seen_s)
    t.last_seen.nanosec = int((last_seen_s % 1) * 1e9)
    return t


def test_no_anchor_publishes_an_empty_group_array():
    node = _FakeNode()
    node._tick()
    assert node.group_pub.messages[-1].groups == []


def test_anchor_with_a_nearby_stable_partner_forms_a_group():
    node = _FakeNode(now_s=1000.0)
    node._on_tracks(PersonTrackArray(tracks=[
        _person_track(1, x=1.0, y=0.0), _person_track(2, x=1.0, y=0.5),
    ]))
    node._on_focus_state(AudioFocusState(valid=True, selected_track_id=1))
    node._tick()
    groups = node.group_pub.messages[-1].groups
    assert len(groups) == 1
    assert set(groups[0].member_track_ids) == {1, 2}
    assert groups[0].active_speaker_track_id == 1


def test_track_in_wrong_frame_is_excluded_from_candidates():
    node = _FakeNode(now_s=1000.0)
    node._on_tracks(PersonTrackArray(tracks=[
        _person_track(1, x=1.0, y=0.0),
        _person_track(2, x=1.0, y=0.5, frame_id="camera_color_optical_frame"),
    ]))
    node._on_focus_state(AudioFocusState(valid=True, selected_track_id=1))
    node._tick()
    # Nur EIN gueltiger Kandidat (Track 2 verworfen) -- keine Gruppe moeglich.
    assert node.group_pub.messages[-1].groups == []


def test_lone_anchor_without_a_nearby_partner_forms_no_group():
    node = _FakeNode(now_s=1000.0)
    node._on_tracks(PersonTrackArray(tracks=[_person_track(1, x=1.0, y=0.0)]))
    node._on_focus_state(AudioFocusState(valid=True, selected_track_id=1))
    node._tick()
    assert node.group_pub.messages[-1].groups == []


def test_focus_becoming_invalid_clears_the_anchor_and_publishes_no_group():
    node = _FakeNode(now_s=1000.0)
    node._on_tracks(PersonTrackArray(tracks=[
        _person_track(1, x=1.0, y=0.0), _person_track(2, x=1.0, y=0.5),
    ]))
    node._on_focus_state(AudioFocusState(valid=True, selected_track_id=1))
    node._tick()
    assert len(node.group_pub.messages[-1].groups) == 1

    node._on_focus_state(AudioFocusState(valid=False, selected_track_id=1))
    node._tick()
    assert node.group_pub.messages[-1].groups == []


def test_group_geometry_fields_are_populated():
    node = _FakeNode(now_s=1000.0)
    node._on_tracks(PersonTrackArray(tracks=[
        _person_track(1, x=2.0, y=0.5), _person_track(2, x=2.0, y=-0.5),
    ]))
    node._on_focus_state(AudioFocusState(valid=True, selected_track_id=1))
    node._tick()
    group = node.group_pub.messages[-1].groups[0]
    assert group.center_position.x > 0.0
    assert group.minimum_member_distance_m > 0.0
    assert group.maximum_member_distance_m >= group.minimum_member_distance_m
