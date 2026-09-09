"""
Tests fuer audio_focus_node.py (Entwicklungsauftrag 04-B, AP6, Abschnitt
10; AP6.1, Abschnitt 5). Gleiches Duck-Typing-Muster wie
test_audio_node_wakeword.py -- die ECHTEN, ungebundenen Methoden von
AudioFocusNode laufen gegen ein leichtgewichtiges Fake, die TF-Lookup
selbst wird injiziert (self._tf_lookup_fn), kein echter TF-Baum noetig.
"""
import math

import pytest

from ihk_pepper_audio.audio_focus import AudioFocusMode, AudioFocusStateMachine
from ihk_pepper_audio.audio_focus_node import AudioFocusNode, transform_person_position_to_azimuth
from ihk_pepper_audio.group_speaker_selection import ActiveSpeakerSelector
from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import (
    AudioVisualTarget,
    ConversationGroup,
    ConversationGroupArray,
    PersonTrack,
    PersonTrackArray,
    SoundDirection,
    WakewordEvent,
)
from geometry_msgs.msg import TransformStamped
from std_msgs.msg import Bool, UInt8


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeStamp:
    def to_msg(self):
        return "stamp"


class _FakeClock:
    def now(self):
        return _FakeStamp()


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


def _identity_transform():
    t = TransformStamped()
    t.transform.rotation.w = 1.0
    return t


class _FakeNode:
    _on_wakeword_event = AudioFocusNode._on_wakeword_event
    _on_speaking = AudioFocusNode._on_speaking
    _on_interaction_state = AudioFocusNode._on_interaction_state
    _on_visual_target = AudioFocusNode._on_visual_target
    _on_person_tracks = AudioFocusNode._on_person_tracks
    _on_sound_direction = AudioFocusNode._on_sound_direction
    _on_groups = AudioFocusNode._on_groups
    _stable_group_for = AudioFocusNode._stable_group_for
    _tick_and_publish = AudioFocusNode._tick_and_publish

    def __init__(self, tf_lookup_fn=None, params=None, active_speaker_selector=None):
        self._machine = AudioFocusStateMachine(target_loss_timeout_s=2.0)
        self.focus_pub = _FakePublisher()
        self._tf_lookup_fn = tf_lookup_fn or (lambda t, s, st: _identity_transform())
        self._latest_groups = None
        self._latest_doa = None
        self._active_speaker_selector = active_speaker_selector or ActiveSpeakerSelector(
            required_confirming_frames=1)
        self._params = params or {
            "base_frame": "base_link",
            "respeaker_frame_id": "respeaker_link",
            "tf_timeout_s": 0.2,
            "group_wide_mode_max_span_rad": math.radians(40.0),
        }

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_clock(self):
        return _FakeClock()

    def get_logger(self):
        return _FakeLogger()


def _wakeword_event(azimuth_rad=0.5, direction_valid=True):
    msg = WakewordEvent()
    msg.event_id = "event-1"
    msg.azimuth_rad = azimuth_rad
    msg.direction_valid = direction_valid
    return msg


def _visual_target(valid=True, track_id=5, azimuth_rad_base=0.0, distance_m=1.5, reason=""):
    msg = AudioVisualTarget()
    msg.event_id = "event-1"
    msg.valid = valid
    msg.track_id = track_id
    msg.target_azimuth_rad_base = azimuth_rad_base
    msg.distance_m = distance_m
    msg.reason = reason
    return msg


def _person_track(track_id=5, x=1.5, y=0.0, z=0.0, has_3d=True, frame_id="base_link"):
    t = PersonTrack()
    t.track_id = track_id
    t.has_3d_position = has_3d
    t.position_3d.x = x
    t.position_3d.y = y
    t.position_3d.z = z
    t.frame_id = frame_id
    return t


def test_wakeword_event_with_invalid_direction_is_ignored():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(direction_valid=False))
    assert node._machine.mode == AudioFocusMode.IDLE_WIDE


def test_wakeword_event_with_valid_direction_starts_orienting():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    assert node._machine.mode == AudioFocusMode.ORIENTING_TO_SOUND


# ---- /audio/visual_target (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5) ----

def test_valid_visual_target_confirms_the_real_track_id():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7))
    assert node._machine.mode == AudioFocusMode.CONVERSATION_FOCUS
    assert node._machine.snapshot().selected_track_id == 7


def test_invalid_visual_target_returns_to_idle():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=False, reason="mehrdeutig"))
    assert node._machine.mode == AudioFocusMode.RETURNING_TO_IDLE


def test_visual_target_azimuth_is_transformed_to_respeaker_frame():
    # 90-Grad-Drehung base_link->respeaker_link -- die bestaetigte
    # Person liegt bei azimuth_rad_base=0.0 (geradeaus in base_link),
    # muss im respeaker_link-Frame verschoben sein.
    def _yaw_transform(t, s, st):
        tr = TransformStamped()
        tr.transform.rotation.z = math.sin(math.pi / 4)
        tr.transform.rotation.w = math.cos(math.pi / 4)
        return tr

    node = _FakeNode(tf_lookup_fn=_yaw_transform)
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7, azimuth_rad_base=0.0, distance_m=2.0))
    assert node._machine.mode == AudioFocusMode.CONVERSATION_FOCUS
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(math.pi / 2, abs=1e-4)


def test_visual_target_outside_expected_window_is_ignored():
    # Kein vorheriges Wakeword-Ereignis -- noch IDLE_WIDE. Ein
    # verspaetetes/fremdes AudioVisualTarget darf hier keine Bestaetigung
    # ausloesen.
    node = _FakeNode()
    node._on_visual_target(_visual_target(valid=True, track_id=7))
    assert node._machine.mode == AudioFocusMode.IDLE_WIDE
    assert node._machine.snapshot().selected_track_id == -1


def test_visual_target_missing_tf_does_not_confirm():
    def _raising(t, s, st):
        raise LookupError("keine TF")

    node = _FakeNode(tf_lookup_fn=_raising)
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7))
    assert node._machine.mode != AudioFocusMode.CONVERSATION_FOCUS
    assert node._machine.snapshot().selected_track_id == -1


# ---- /perception_node/person_tracks waehrend eines bestaetigten Fokus ----

def test_person_tracks_update_the_confirmed_track():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7, azimuth_rad_base=0.0, distance_m=1.0))
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(0.0, abs=1e-6)

    array = PersonTrackArray()
    array.tracks = [_person_track(track_id=7, x=1.0, y=1.0)]  # neue Position, 45 Grad
    node._on_person_tracks(array)
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(math.radians(45.0), abs=1e-3)


def test_person_tracks_ignore_a_foreign_track_id():
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: ein lauterer/anderer
    # Sprecher darf NIE selbst zum neuen Fokus werden.
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7, azimuth_rad_base=0.0, distance_m=1.0))
    before = node._machine.snapshot().target_azimuth_rad

    array = PersonTrackArray()
    array.tracks = [_person_track(track_id=99, x=1.0, y=1.0)]  # FREMDER Track
    node._on_person_tracks(array)
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(before, abs=1e-9)
    assert node._machine.snapshot().selected_track_id == 7


def test_person_tracks_without_selected_target_are_ignored():
    node = _FakeNode()  # noch IDLE_WIDE, kein bestaetigter Track
    array = PersonTrackArray()
    array.tracks = [_person_track(track_id=1, x=1.0, y=0.0)]
    node._on_person_tracks(array)  # darf nicht crashen, tut einfach nichts
    assert node._machine.snapshot().selected_track_id == -1


def test_person_tracks_in_wrong_frame_are_ignored():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7, azimuth_rad_base=0.0, distance_m=1.0))
    before = node._machine.snapshot().target_azimuth_rad

    array = PersonTrackArray()
    array.tracks = [_person_track(track_id=7, x=1.0, y=1.0, frame_id="camera_color_optical_frame")]
    node._on_person_tracks(array)
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(before, abs=1e-9)


def test_idle_interaction_state_ends_conversation():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7))
    assert node._machine.mode == AudioFocusMode.CONVERSATION_FOCUS
    node._on_interaction_state(UInt8(data=int(InteractionState.IDLE)))
    assert node._machine.mode == AudioFocusMode.RETURNING_TO_IDLE


def test_speaking_changes_switch_mode():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7))
    node._on_speaking(Bool(data=True))
    assert node._machine.mode == AudioFocusMode.PEPPER_SPEAKING
    node._on_speaking(Bool(data=False))
    assert node._machine.mode == AudioFocusMode.CONVERSATION_FOCUS


def test_tick_and_publish_publishes_current_snapshot():
    node = _FakeNode()
    node._tick_and_publish()
    assert len(node.focus_pub.messages) == 1
    msg = node.focus_pub.messages[0]
    assert msg.mode == AudioFocusMode.IDLE_WIDE.value
    assert msg.valid is False


# ---- transform_person_position_to_azimuth() (reine Funktion) ----

def test_transform_person_position_identity():
    az = transform_person_position_to_azimuth(
        1.0, 0.0, 0.0, "base_link", "respeaker_link", "stamp",
        lambda t, s, st: _identity_transform())
    assert az == pytest.approx(0.0, abs=1e-9)


def test_transform_person_position_empty_frame_returns_none():
    az = transform_person_position_to_azimuth(
        1.0, 0.0, 0.0, "", "respeaker_link", "stamp", lambda t, s, st: _identity_transform())
    assert az is None


def test_transform_person_position_tf_error_returns_none():
    def _raising(t, s, st):
        raise LookupError("keine TF")

    az = transform_person_position_to_azimuth(
        1.0, 0.0, 0.0, "base_link", "respeaker_link", "stamp", _raising)
    assert az is None


def test_transform_person_position_none_transform_returns_none():
    az = transform_person_position_to_azimuth(
        1.0, 0.0, 0.0, "base_link", "respeaker_link", "stamp", lambda t, s, st: None)
    assert az is None


# ---- Gruppen-Audiofokus (Entwicklungsauftrag 04-B, AP7, Abschnitt 17) ----

def _group(group_id="g1", member_track_ids=(7, 8), stable=True, angular_span_rad=0.1,
           center_x=1.0, center_y=0.0):
    g = ConversationGroup()
    g.group_id = group_id
    g.member_track_ids = list(member_track_ids)
    g.stable = stable
    g.angular_span_rad = angular_span_rad
    g.center_position.x = center_x
    g.center_position.y = center_y
    return g


def _sound_direction(azimuth_rad=0.0, valid=True, vad_active=True):
    msg = SoundDirection()
    msg.azimuth_rad = azimuth_rad
    msg.valid = valid
    msg.vad_active = vad_active
    return msg


def _confirm_track_7(node):
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_visual_target(_visual_target(valid=True, track_id=7, azimuth_rad_base=0.0, distance_m=1.0))


def test_no_group_uses_the_confirmed_persons_own_position_unchanged():
    node = _FakeNode()
    _confirm_track_7(node)
    array = PersonTrackArray(tracks=[_person_track(track_id=7, x=1.0, y=1.0)])
    node._on_person_tracks(array)
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(math.radians(45.0), abs=1e-3)


def test_unstable_group_is_ignored_uses_own_position():
    node = _FakeNode()
    _confirm_track_7(node)
    node._on_groups(ConversationGroupArray(groups=[_group(stable=False)]))
    array = PersonTrackArray(tracks=[
        _person_track(track_id=7, x=1.0, y=1.0), _person_track(track_id=8, x=5.0, y=0.0),
    ])
    node._on_person_tracks(array)
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(math.radians(45.0), abs=1e-3)


def test_group_wide_mode_targets_the_group_center_not_the_confirmed_person():
    node = _FakeNode()
    _confirm_track_7(node)
    node._on_groups(ConversationGroupArray(groups=[
        _group(member_track_ids=(7, 8), stable=True, angular_span_rad=0.1, center_x=2.0, center_y=2.0),
    ]))
    array = PersonTrackArray(tracks=[
        _person_track(track_id=7, x=1.0, y=0.0), _person_track(track_id=8, x=3.0, y=0.0),
    ])
    node._on_person_tracks(array)
    # Peilung zum Gruppenzentrum (2,2), NICHT zur Einzelposition von Track 7 (1,0).
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(math.radians(45.0), abs=1e-3)


def test_session_identity_stays_the_original_anchor_even_in_group_wide_mode():
    node = _FakeNode()
    _confirm_track_7(node)
    node._on_groups(ConversationGroupArray(groups=[_group(member_track_ids=(7, 8))]))
    array = PersonTrackArray(tracks=[
        _person_track(track_id=7, x=1.0, y=0.0), _person_track(track_id=8, x=3.0, y=0.0),
    ])
    node._on_person_tracks(array)
    assert node._machine.snapshot().selected_track_id == 7  # NIE auf 8 umgesprungen


def test_active_speaker_mode_targets_the_confirmed_speaker_after_enough_frames():
    node = _FakeNode()
    _confirm_track_7(node)
    # Grosse Winkelspanne -- ACTIVE_SPEAKER statt GROUP_WIDE.
    node._on_groups(ConversationGroupArray(groups=[
        _group(member_track_ids=(7, 8), angular_span_rad=math.radians(90.0)),
    ]))
    array = PersonTrackArray(tracks=[
        _person_track(track_id=7, x=1.0, y=0.0), _person_track(track_id=8, x=0.0, y=1.0),
    ])
    # DoA zeigt auf Track 8 (90 Grad) -- required_confirming_frames=1 im Fake.
    node._on_sound_direction(_sound_direction(azimuth_rad=math.radians(90.0)))
    node._on_person_tracks(array)
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(math.radians(90.0), abs=1e-3)
    assert node._machine.snapshot().selected_track_id == 7  # Sitzungsidentitaet unveraendert


def test_active_speaker_mode_falls_back_to_original_anchor_before_confirmation():
    node = _FakeNode(active_speaker_selector=ActiveSpeakerSelector(required_confirming_frames=3))
    _confirm_track_7(node)
    node._on_groups(ConversationGroupArray(groups=[
        _group(member_track_ids=(7, 8), angular_span_rad=math.radians(90.0)),
    ]))
    array = PersonTrackArray(tracks=[
        _person_track(track_id=7, x=1.0, y=0.0), _person_track(track_id=8, x=0.0, y=1.0),
    ])
    node._on_sound_direction(_sound_direction(azimuth_rad=math.radians(90.0)))
    node._on_person_tracks(array)
    # Noch nicht genug bestaetigende Frames -- bleibt sicher bei Track 7.
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(0.0, abs=1e-3)


def test_active_speaker_never_targets_a_direction_outside_the_group():
    node = _FakeNode()
    _confirm_track_7(node)
    node._on_groups(ConversationGroupArray(groups=[
        _group(member_track_ids=(7, 8), angular_span_rad=math.radians(90.0)),
    ]))
    array = PersonTrackArray(tracks=[
        _person_track(track_id=7, x=1.0, y=0.0), _person_track(track_id=8, x=0.0, y=1.0),
    ])
    # DoA zeigt WEIT ausserhalb jeder Gruppenperson.
    node._on_sound_direction(_sound_direction(azimuth_rad=math.radians(179.0)))
    node._on_person_tracks(array)
    # Kein Kandidat passt -- bleibt beim urspruenglichen Anker (Track 7, 0 Grad).
    assert node._machine.snapshot().target_azimuth_rad == pytest.approx(0.0, abs=1e-3)
