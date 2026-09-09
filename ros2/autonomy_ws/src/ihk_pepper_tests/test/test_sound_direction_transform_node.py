"""
Tests fuer sound_direction_transform_node.py (Entwicklungsauftrag 04-B,
AP6.1, Abschnitt 3.1/4/12): duenne ROS-Anbindung von sound_ray_transform.py
(dort bereits die eigentliche TF-Mathematik separat getestet) --
gleiches Duck-Typing-Muster wie test_bridge_node_set_head_pose.py: die
ECHTEN, ungebundenen Methoden von SoundDirectionTransformNode laufen
gegen ein leichtgewichtiges Fake, kein rclpy.init()/echter TF-Baum
noetig. Die tf_lookup_fn selbst wird hier direkt injiziert (nicht ueber
einen echten tf2_ros.Buffer), analog zu test_sound_ray_transform.py.
"""
import math

import pytest
from geometry_msgs.msg import TransformStamped

from ihk_pepper_audio.sound_direction_transform_node import SoundDirectionTransformNode
from ihk_pepper_interfaces.msg import SoundDirection, WakewordEvent


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _FakeTime:
    def __init__(self, nanoseconds):
        self.nanoseconds = nanoseconds


class _FakeClock:
    def __init__(self, now_ns):
        self._now_ns = now_ns

    def now(self):
        return _FakeTime(self._now_ns)


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


def _identity_transform():
    t = TransformStamped()
    t.transform.rotation.w = 1.0
    return t


def _yaw_transform(yaw_rad):
    t = TransformStamped()
    t.transform.rotation.z = math.sin(yaw_rad / 2.0)
    t.transform.rotation.w = math.cos(yaw_rad / 2.0)
    return t


class _FakeNode:
    _on_sound_direction_raw = SoundDirectionTransformNode._on_sound_direction_raw
    _on_wakeword_event_raw = SoundDirectionTransformNode._on_wakeword_event_raw
    _too_old = SoundDirectionTransformNode._too_old

    def __init__(self, base_frame="base_link", max_measurement_age_s=2.0,
                 now_ns=1000 * 10**9, tf_lookup_fn=None):
        self._params = {
            "base_frame": base_frame,
            "max_measurement_age_s": max_measurement_age_s,
            "tf_timeout_s": 0.2,
        }
        self.sound_direction_pub = _FakePublisher()
        self.wakeword_event_pub = _FakePublisher()
        self._now_ns = now_ns
        self._tf_lookup_fn = tf_lookup_fn or (lambda target, source, stamp: _identity_transform())

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_clock(self):
        return _FakeClock(self._now_ns)

    def get_logger(self):
        return _FakeLogger()


def _sound_direction(azimuth_rad=0.3, confidence=0.8, valid=True, frame_id="respeaker_link",
                      stamp_ns=1000 * 10**9, vad_active=True, backend="GccPhat", reason=""):
    msg = SoundDirection()
    msg.header.frame_id = frame_id
    msg.header.stamp.sec = int(stamp_ns // 10**9)
    msg.header.stamp.nanosec = int(stamp_ns % 10**9)
    msg.azimuth_rad = azimuth_rad
    msg.confidence = confidence
    msg.vad_active = vad_active
    msg.valid = valid
    msg.backend = backend
    msg.reason = reason
    return msg


def _wakeword_event(azimuth_rad=0.3, direction_confidence=0.8, direction_valid=True,
                     frame_id="respeaker_link", stamp_ns=1000 * 10**9, event_id="evt-1",
                     keyword="Pepper", keyword_confidence=1.0):
    msg = WakewordEvent()
    msg.header.frame_id = frame_id
    msg.header.stamp.sec = int(stamp_ns // 10**9)
    msg.header.stamp.nanosec = int(stamp_ns % 10**9)
    msg.event_id = event_id
    msg.keyword = keyword
    msg.keyword_confidence = keyword_confidence
    msg.azimuth_rad = azimuth_rad
    msg.direction_confidence = direction_confidence
    msg.direction_valid = direction_valid
    return msg


# ---- SoundDirection ----

def test_valid_sample_is_transformed_and_republished_as_canonical():
    node = _FakeNode(tf_lookup_fn=lambda t, s, st: _yaw_transform(math.pi / 2))
    node._on_sound_direction_raw(_sound_direction(azimuth_rad=0.0))
    assert len(node.sound_direction_pub.messages) == 1
    out = node.sound_direction_pub.messages[0]
    assert out.valid is True
    assert out.header.frame_id == "base_link"
    assert out.azimuth_rad == pytest.approx(math.pi / 2, abs=1e-5)


def test_already_invalid_raw_sample_stays_invalid_and_is_not_transformed():
    calls = []

    def _tf(t, s, st):
        calls.append(1)
        return _identity_transform()

    node = _FakeNode(tf_lookup_fn=_tf)
    node._on_sound_direction_raw(_sound_direction(valid=False, reason="kein_vad"))
    out = node.sound_direction_pub.messages[0]
    assert out.valid is False
    assert out.reason == "kein_vad"
    assert calls == []  # TF-Lookup wird fuer eine bereits ungueltige Probe gar nicht erst versucht


def test_stale_measurement_is_rejected_without_transform_attempt():
    calls = []

    def _tf(t, s, st):
        calls.append(1)
        return _identity_transform()

    now_ns = 1000 * 10**9
    old_stamp_ns = now_ns - int(5.0 * 1e9)
    node = _FakeNode(now_ns=now_ns, max_measurement_age_s=2.0, tf_lookup_fn=_tf)
    node._on_sound_direction_raw(_sound_direction(stamp_ns=old_stamp_ns))
    out = node.sound_direction_pub.messages[0]
    assert out.valid is False
    assert out.reason == "messung_zu_alt"
    assert calls == []


def test_tf_error_produces_fail_closed_canonical_message():
    def _raising(t, s, st):
        raise LookupError("keine TF respeaker_link->base_link")

    node = _FakeNode(tf_lookup_fn=_raising)
    node._on_sound_direction_raw(_sound_direction())
    out = node.sound_direction_pub.messages[0]
    assert out.valid is False
    assert out.reason.startswith("tf_fehler_")


def test_canonical_output_preserves_original_timestamp():
    original_stamp_ns = 12345 * 10**9 + 6789
    node = _FakeNode(now_ns=original_stamp_ns)
    node._on_sound_direction_raw(_sound_direction(stamp_ns=original_stamp_ns))
    out = node.sound_direction_pub.messages[0]
    assert out.header.stamp.sec == 12345
    assert out.header.stamp.nanosec == 6789


# ---- WakewordEvent ----

def test_wakeword_event_with_valid_direction_is_transformed():
    node = _FakeNode(tf_lookup_fn=lambda t, s, st: _yaw_transform(math.pi))
    node._on_wakeword_event_raw(_wakeword_event(azimuth_rad=0.0, direction_valid=True))
    out = node.wakeword_event_pub.messages[0]
    assert out.direction_valid is True
    assert out.header.frame_id == "base_link"
    assert out.event_id == "evt-1"
    assert abs(abs(out.azimuth_rad) - math.pi) < 1e-4


def test_wakeword_event_with_invalid_direction_stays_invalid_without_transform_attempt():
    calls = []

    def _tf(t, s, st):
        calls.append(1)
        return _identity_transform()

    node = _FakeNode(tf_lookup_fn=_tf)
    node._on_wakeword_event_raw(_wakeword_event(direction_valid=False))
    out = node.wakeword_event_pub.messages[0]
    assert out.direction_valid is False
    assert calls == []


def test_wakeword_event_preserves_event_id_and_keyword_through_transform_failure():
    def _raising(t, s, st):
        raise LookupError("keine TF")

    node = _FakeNode(tf_lookup_fn=_raising)
    node._on_wakeword_event_raw(_wakeword_event(event_id="evt-42", keyword="Pepper"))
    out = node.wakeword_event_pub.messages[0]
    assert out.direction_valid is False
    assert out.event_id == "evt-42"
    assert out.keyword == "Pepper"


def test_wakeword_event_stale_measurement_rejected():
    now_ns = 5000 * 10**9
    old_stamp_ns = now_ns - int(10.0 * 1e9)
    node = _FakeNode(now_ns=now_ns, max_measurement_age_s=2.0)
    node._on_wakeword_event_raw(_wakeword_event(stamp_ns=old_stamp_ns))
    out = node.wakeword_event_pub.messages[0]
    assert out.direction_valid is False
