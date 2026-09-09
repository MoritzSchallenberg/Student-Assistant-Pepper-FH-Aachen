"""
Tests fuer die Wakeword-/Gespraechszustands-Verdrahtung in audio_node.py
(Entwicklungsauftrag 04-B, AP6, Abschnitt 8). Gleiches Duck-Typing-
Muster wie test_motion_guard_freshness.py/test_run_dialogue_cancellation.py
-- die ECHTEN, ungebundenen Methoden von AudioNode laufen gegen ein
leichtgewichtiges Fake, kein rclpy.init() noetig.
"""
import threading
import time

from ihk_pepper_audio.audio_node import AudioNode
from ihk_pepper_audio.wakeword_gate import WakewordGate
from ihk_pepper_interaction.interaction_state import InteractionState
from std_msgs.msg import UInt8


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def info(self, *a, **kw):
        pass

    def warn(self, *a, **kw):
        pass


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeStamp:
    def to_msg(self):
        return "stamp"


class _FakeClock:
    def now(self):
        return _FakeStamp()


class _FakeWakeword:
    def __init__(self, enabled=True, detect_result=False):
        self.enabled = enabled
        self._detect_result = detect_result

    def detect(self, pcm):
        return self._detect_result


class _FakeNode:
    _on_interaction_state = AudioNode._on_interaction_state
    _conversation_active_for_gate = AudioNode._conversation_active_for_gate
    _session_active = AudioNode._session_active
    _handle_utterance = AudioNode._handle_utterance

    def __init__(self, params=None, wakeword_enabled=True, wakeword_detect_result=False,
                 interaction_state_known=True):
        self._params = params or {}
        self._interaction_state_value = InteractionState.IDLE
        # Realistischer Ausgangszustand fuer die meisten Tests: ein
        # frisches IDLE wurde bereits empfangen. Das reine "nie empfangen
        # -> faellt fail-closed auf 'koennte aktiv sein' zurueck"-
        # Verhalten wird gesondert mit interaction_state_known=False
        # geprueft (siehe test_conversation_active_fails_closed_when_never_received).
        self._interaction_state_received_at = time.monotonic() if interaction_state_known else None
        self._session_active_until = None
        self.wakeword = _FakeWakeword(enabled=wakeword_enabled, detect_result=wakeword_detect_result)
        self.wakeword_gate = WakewordGate(
            cooldown_s=self._params.get("wakeword_cooldown_s", 3.0), now_fn=time.monotonic)
        self._direction_lock = threading.Lock()
        self._latest_direction = (0.0, 0.0, False)
        self.segment_duration_pub = _FakePublisher()
        self.wakeword_event_pub = _FakePublisher()

    def get_parameter(self, name):
        defaults = {
            "wakeword_min_confidence": 0.5,
            "session_active_timeout_s": 20.0,
            "interaction_state_max_age_s": 3.0,
        }
        return _FakeParam(self._params.get(name, defaults.get(name)))

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock()


# ---- _on_interaction_state / _conversation_active_for_gate ----

def test_conversation_active_fails_closed_when_never_received():
    node = _FakeNode(interaction_state_known=False)
    assert node._conversation_active_for_gate() is True


def test_conversation_active_false_when_fresh_idle():
    node = _FakeNode()
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.IDLE)))
    assert node._conversation_active_for_gate() is False


def test_conversation_active_true_when_fresh_non_idle():
    node = _FakeNode()
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    assert node._conversation_active_for_gate() is True


def test_conversation_active_fails_closed_when_stale(monkeypatch):
    node = _FakeNode(params={"interaction_state_max_age_s": 1.0})
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.IDLE)))
    fake_time[0] += 5.0  # weit ueber max_age
    assert node._conversation_active_for_gate() is True


def test_idle_transition_resets_session_active_until():
    node = _FakeNode()
    node._session_active_until = time.monotonic() + 100.0
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.IDLE)))
    assert node._session_active_until is None


def test_non_idle_transition_does_not_touch_session_active_until():
    node = _FakeNode()
    node._session_active_until = time.monotonic() + 100.0
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    assert node._session_active_until is not None


# ---- _session_active ----

def test_session_active_always_true_when_wakeword_disabled():
    node = _FakeNode(wakeword_enabled=False)
    assert node._session_active() is True


def test_session_active_false_when_no_session_set():
    node = _FakeNode(wakeword_enabled=True)
    assert node._session_active() is False


def test_session_active_true_within_timeout(monkeypatch):
    node = _FakeNode(wakeword_enabled=True)
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])
    node._session_active_until = fake_time[0] + 20.0
    assert node._session_active() is True


def test_session_active_false_after_timeout_expires_without_reset():
    """Regressionstest fuer den behobenen Fund: _session_active war
    vorher ein ewiger Ratchet (einmal gesetzt, NIE zurueckgesetzt) --
    jetzt begrenzt durch session_active_timeout_s."""
    node = _FakeNode(wakeword_enabled=True)
    node._session_active_until = time.monotonic() - 1.0  # bereits abgelaufen
    assert node._session_active() is False


# ---- _handle_utterance: Wakeword-Gate-Verdrahtung ----

def test_handle_utterance_publishes_wakeword_event_on_detection():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.wakeword_event_pub.messages) == 1
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.keyword == "pepper"
    assert node._session_active_until is not None


def test_handle_utterance_does_not_publish_when_no_keyword_detected():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=False)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert node.wakeword_event_pub.messages == []
    assert node._session_active_until is None


def test_handle_utterance_blocked_by_conversation_active():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert node.wakeword_event_pub.messages == []


def test_handle_utterance_respects_cooldown_between_events():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True,
                      params={"wakeword_cooldown_s": 3.0})
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.wakeword_event_pub.messages) == 1
    # Innerhalb des Cooldowns: keine zweite Aktivierung, obwohl das
    # Keyword erneut "erkannt" wird.
    node._session_active_until = None  # Sitzung zwischenzeitlich erneut abgelaufen
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.wakeword_event_pub.messages) == 1


def test_handle_utterance_carries_latest_direction_into_event():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    node._latest_direction = (0.42, 0.9, True)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.azimuth_rad == 0.42
    assert event_msg.direction_confidence == 0.9
    assert event_msg.direction_valid is True
