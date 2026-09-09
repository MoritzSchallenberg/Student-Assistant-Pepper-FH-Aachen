"""
Tests fuer audio_focus_node.py (Entwicklungsauftrag 04-B, AP6, Abschnitt
10). Gleiches Duck-Typing-Muster wie test_audio_node_wakeword.py.
"""
from ihk_pepper_audio.audio_focus import AudioFocusMode, AudioFocusStateMachine
from ihk_pepper_audio.audio_focus_node import AudioFocusNode
from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import WakewordEvent
from std_msgs.msg import Bool, UInt8


class _FakeStamp:
    def to_msg(self):
        return "stamp"


class _FakeClock:
    def now(self):
        return _FakeStamp()


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeNode:
    _on_wakeword_event = AudioFocusNode._on_wakeword_event
    _on_speaking = AudioFocusNode._on_speaking
    _on_interaction_state = AudioFocusNode._on_interaction_state
    _tick_and_publish = AudioFocusNode._tick_and_publish

    def __init__(self):
        self._machine = AudioFocusStateMachine(target_loss_timeout_s=2.0)
        self.focus_pub = _FakePublisher()

    def get_clock(self):
        return _FakeClock()


def _wakeword_event(azimuth_rad=0.5, direction_valid=True):
    msg = WakewordEvent()
    msg.event_id = "event-1"
    msg.azimuth_rad = azimuth_rad
    msg.direction_valid = direction_valid
    return msg


def test_wakeword_event_with_invalid_direction_is_ignored():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(direction_valid=False))
    assert node._machine.mode == AudioFocusMode.IDLE_WIDE


def test_wakeword_event_with_valid_direction_starts_orienting():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    assert node._machine.mode == AudioFocusMode.ORIENTING_TO_SOUND


def test_conversation_ready_confirms_person():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_interaction_state(UInt8(data=int(InteractionState.CONVERSATION_READY)))
    assert node._machine.mode == AudioFocusMode.CONVERSATION_FOCUS


def test_idle_interaction_state_ends_conversation():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_interaction_state(UInt8(data=int(InteractionState.CONVERSATION_READY)))
    assert node._machine.mode == AudioFocusMode.CONVERSATION_FOCUS
    node._on_interaction_state(UInt8(data=int(InteractionState.IDLE)))
    assert node._machine.mode == AudioFocusMode.RETURNING_TO_IDLE


def test_speaking_changes_switch_mode():
    node = _FakeNode()
    node._on_wakeword_event(_wakeword_event(azimuth_rad=0.5, direction_valid=True))
    node._on_interaction_state(UInt8(data=int(InteractionState.CONVERSATION_READY)))
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
