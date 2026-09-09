"""
Tests fuer die Wakeword-/Gespraechszustands-Verdrahtung in audio_node.py
(Entwicklungsauftrag 04-B, AP6/AP6.1, Abschnitt 8/13). Gleiches
Duck-Typing-Muster wie test_motion_guard_freshness.py/
test_run_dialogue_cancellation.py -- die ECHTEN, ungebundenen Methoden
von AudioNode laufen gegen ein leichtgewichtiges Fake, kein rclpy.init()
noetig.
"""
import threading
import time

from ihk_pepper_audio.audio_node import (
    ACTIVATION_MODE_CONTINUOUS_DEVELOPMENT,
    ACTIVATION_MODE_PUSH_TO_TALK,
    ACTIVATION_MODE_WAKEWORD_REQUIRED,
    AudioNode,
)
from ihk_pepper_audio.direction_sample_buffer import DirectionSampleBuffer, TimedDirectionSample
from ihk_pepper_audio.wakeword_gate import WakewordGate
from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import AudioFocusState
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
    nanoseconds = 1_700_000_000_000_000_000

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


class _FakeSteerableBackend:
    def __init__(self):
        self.focus_calls = []
        self.clear_calls = 0

    def set_focus_target(self, azimuth_rad, valid_until_monotonic_s):
        self.focus_calls.append((azimuth_rad, valid_until_monotonic_s))

    def clear_focus_target(self):
        self.clear_calls += 1


class _FakeNode:
    _on_interaction_state = AudioNode._on_interaction_state
    _conversation_active_for_gate = AudioNode._conversation_active_for_gate
    _conversation_confirmed_active = AudioNode._conversation_confirmed_active
    _session_active = AudioNode._session_active
    _should_process_utterance = AudioNode._should_process_utterance
    _try_wakeword_activation = AudioNode._try_wakeword_activation
    _publish_codeword_command_if_matched = AudioNode._publish_codeword_command_if_matched
    _handle_utterance = AudioNode._handle_utterance
    _get_whisper = AudioNode._get_whisper
    _on_focus_state = AudioNode._on_focus_state

    def __init__(self, params=None, wakeword_enabled=True, wakeword_detect_result=False,
                 interaction_state_known=True, push_to_talk_active=False,
                 direction_source_unambiguous=True, codeword_rules=None):
        self._params = params or {}
        self._interaction_state_value = InteractionState.IDLE
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13: Default True
        # in diesem Test-Fake, damit die BESTEHENDEN Tests (die die neue
        # Ambiguitaets-Gate-Funktion nicht pruefen wollen) unveraendert
        # weiter direction_valid=True erwarten koennen -- der echte
        # Produktions-Default in AudioNode.__init__ bleibt hingegen
        # bewusst False (siehe dort), bis ein Backend mit
        # provides_unambiguous_direction=True tatsaechlich eingetroffen ist.
        self._direction_source_unambiguous = direction_source_unambiguous
        self._current_backend = None
        # Realistischer Ausgangszustand fuer die meisten Tests: ein
        # frisches IDLE wurde bereits empfangen. Das reine "nie empfangen
        # -> faellt fail-closed auf 'koennte aktiv sein' zurueck"-
        # Verhalten wird gesondert mit interaction_state_known=False
        # geprueft (siehe test_conversation_active_fails_closed_when_never_received).
        self._interaction_state_received_at = time.monotonic() if interaction_state_known else None
        self._session_active_until = None
        self._push_to_talk_active = push_to_talk_active
        self.wakeword = _FakeWakeword(enabled=wakeword_enabled, detect_result=wakeword_detect_result)
        self.wakeword_gate = WakewordGate(
            cooldown_s=self._params.get("wakeword_cooldown_s", 3.0), now_fn=time.monotonic)
        self._direction_lock = threading.Lock()
        self._direction_buffer = DirectionSampleBuffer(max_duration_s=3.0)
        self.segment_duration_pub = _FakePublisher()
        self.wakeword_event_pub = _FakePublisher()
        self._codeword_rules = codeword_rules or {}
        self.interaction_command_raw_pub = _FakePublisher()
        self.transcript_pub = _FakePublisher()
        self._whisper_model = None

    def get_parameter(self, name):
        defaults = {
            "activation_mode": ACTIVATION_MODE_WAKEWORD_REQUIRED,
            "wakeword_min_confidence": 0.5,
            "session_active_timeout_s": 20.0,
            "interaction_state_max_age_s": 3.0,
            "direction_window_margin_s": 0.5,
            "direction_min_confidence_for_wakeword": 0.0,
            "respeaker_frame_id": "respeaker_link",
            "whisper_language": "de",
            "allow_ambiguous_direction_for_head_orientation": False,
            "focus_target_freshness_margin_s": 1.0,
        }
        return _FakeParam(self._params.get(name, defaults.get(name)))

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock()

    def _push_direction_sample(self, azimuth_rad=0.42, confidence=0.9, valid=True, age_s=0.0):
        now = time.monotonic()
        self._direction_buffer.push(TimedDirectionSample(
            ros_stamp_ns=1_700_000_000_000_000_000, monotonic_stamp_s=now - age_s,
            frame_id="respeaker_link", azimuth_rad=azimuth_rad, confidence=confidence, valid=valid,
        ))


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


# ---- _conversation_confirmed_active (Entwicklungsauftrag 04-B, AP7,
#      Abschnitt 12: haelt die Sitzung waehrend eines ECHT bestaetigten
#      Gespraechs offen, im Unterschied zu _conversation_active_for_gate()
#      NICHT fail-closed auf "aktiv" bei fehlendem/veraltetem Zustand) ----

def test_conversation_confirmed_active_false_when_never_received():
    node = _FakeNode(interaction_state_known=False)
    assert node._conversation_confirmed_active() is False


def test_conversation_confirmed_active_false_when_fresh_idle():
    node = _FakeNode()
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.IDLE)))
    assert node._conversation_confirmed_active() is False


def test_conversation_confirmed_active_true_when_fresh_non_idle():
    node = _FakeNode()
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    assert node._conversation_confirmed_active() is True


def test_conversation_confirmed_active_false_when_stale(monkeypatch):
    node = _FakeNode(params={"interaction_state_max_age_s": 1.0})
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    fake_time[0] += 5.0  # weit ueber max_age
    assert node._conversation_confirmed_active() is False


def test_should_process_utterance_stays_true_during_confirmed_conversation_past_the_wakeword_timeout():
    # Bestaetigter Fund (AP7, Abschnitt 12): vorher haette das abgelaufene
    # Wakeword-Zeitfenster ALLEIN die Sitzung beendet, obwohl der
    # Supervisor gerade FRISCH ein aktives Gespraech meldet.
    node = _FakeNode(wakeword_enabled=True)
    node._session_active_until = time.monotonic() - 1.0  # Wakeword-Fenster abgelaufen
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    assert node._session_active() is False
    assert node._should_process_utterance() is True


def test_should_process_utterance_false_when_neither_session_nor_conversation_active():
    node = _FakeNode(wakeword_enabled=True, interaction_state_known=False)
    node._session_active_until = None
    assert node._should_process_utterance() is False


# ---- _session_active (reiner Timeout-Check) ----

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
    """Regressionstest fuer den in AP6 behobenen Fund: _session_active
    war vorher ein ewiger Ratchet (einmal gesetzt, NIE zurueckgesetzt) --
    jetzt begrenzt durch session_active_timeout_s."""
    node = _FakeNode(wakeword_enabled=True)
    node._session_active_until = time.monotonic() - 1.0  # bereits abgelaufen
    assert node._session_active() is False


# ---- _should_process_utterance (AP6.1: activation_mode ersetzt das
#      bisherige "if not self.wakeword.enabled: return True") ----

def test_wakeword_required_without_model_never_processes():
    """Regressionstest fuer den bestaetigten AP6.1-Fund: OHNE geladenes
    Modell wurde bisher IMMER transkribiert (fail-open). Jetzt: NIE."""
    node = _FakeNode(wakeword_enabled=False,
                      params={"activation_mode": ACTIVATION_MODE_WAKEWORD_REQUIRED})
    assert node._should_process_utterance() is False


def test_wakeword_required_with_model_uses_session_active():
    node = _FakeNode(wakeword_enabled=True,
                      params={"activation_mode": ACTIVATION_MODE_WAKEWORD_REQUIRED})
    assert node._should_process_utterance() is False  # keine Sitzung aktiv
    node._session_active_until = time.monotonic() + 20.0
    assert node._should_process_utterance() is True


def test_push_to_talk_follows_the_flag():
    node = _FakeNode(params={"activation_mode": ACTIVATION_MODE_PUSH_TO_TALK},
                      push_to_talk_active=False)
    assert node._should_process_utterance() is False
    node._push_to_talk_active = True
    assert node._should_process_utterance() is True


def test_continuous_development_always_processes():
    node = _FakeNode(wakeword_enabled=False,
                      params={"activation_mode": ACTIVATION_MODE_CONTINUOUS_DEVELOPMENT})
    assert node._should_process_utterance() is True


# ---- _handle_utterance: Wakeword-Gate-Verdrahtung ----

def test_handle_utterance_publishes_wakeword_event_on_detection():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    node._push_direction_sample()
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.wakeword_event_pub.messages) == 1
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.keyword == "pepper"
    assert node._session_active_until is not None


def test_handle_utterance_does_not_publish_when_no_keyword_detected():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=False)
    node._push_direction_sample()
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert node.wakeword_event_pub.messages == []
    assert node._session_active_until is None


def test_handle_utterance_blocked_by_conversation_active():
    # Entwicklungsauftrag 04-B, AP7, Abschnitt 12: seit
    # _conversation_confirmed_active() nimmt _handle_utterance() waehrend
    # eines frisch bestaetigten Gespraechs den VOLLEN Transkriptionspfad
    # (nicht mehr den Wakeword-Aktivierungsversuch) -- ein neues
    # WakewordEvent kann aus diesem Pfad strukturell gar nicht mehr
    # entstehen (_try_wakeword_activation() wird hier nie aufgerufen),
    # das urspruengliche Ziel dieses Tests ("kein doppeltes Wakeword-
    # Ereignis waehrend ENGAGED") bleibt damit weiterhin erfuellt.
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    node._push_direction_sample()
    node._whisper_model = _FakeWhisperModel("ganz normaler Satz")
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert node.wakeword_event_pub.messages == []


def test_handle_utterance_respects_cooldown_between_events():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True,
                      params={"wakeword_cooldown_s": 3.0})
    node._push_direction_sample()
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.wakeword_event_pub.messages) == 1
    # Innerhalb des Cooldowns: keine zweite Aktivierung, obwohl das
    # Keyword erneut "erkannt" wird.
    node._session_active_until = None  # Sitzung zwischenzeitlich erneut abgelaufen
    node._push_direction_sample()
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.wakeword_event_pub.messages) == 1


def test_handle_utterance_carries_direction_sample_into_event():
    import pytest
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    node._push_direction_sample(azimuth_rad=0.42, confidence=0.9, valid=True)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    event_msg = node.wakeword_event_pub.messages[0]
    # atan2(sin(x),cos(x)) plus float32-Nachrichtenfelder runden minimal --
    # kein Genauigkeitsanspruch ueber ein paar ULP hinaus.
    assert event_msg.azimuth_rad == pytest.approx(0.42, abs=1e-5)
    assert event_msg.direction_confidence == pytest.approx(0.9, abs=1e-5)
    assert event_msg.direction_valid is True


def test_handle_utterance_without_any_direction_sample_reports_invalid_direction():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True)
    # kein _push_direction_sample() -- Puffer bleibt leer.
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    # WakewordGate verlangt KEINE gueltige Richtung, um ueberhaupt ein
    # Ereignis zu erzeugen (die Richtung ist informativ, nicht
    # Voraussetzung) -- aber direction_valid muss ehrlich False bleiben,
    # keine erfundene Richtung.
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.direction_valid is False


def test_handle_utterance_ignores_direction_sample_outside_utterance_window():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True,
                      params={"direction_window_margin_s": 0.05})
    node._push_direction_sample(azimuth_rad=0.9, age_s=10.0)  # weit ausserhalb des Fensters
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.direction_valid is False


# ---- Ambiguitaets-Gate (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13) ----

def test_ambiguous_direction_source_forces_direction_invalid_by_default():
    # Ein Backend ohne provides_unambiguous_direction=True (z.B. die
    # Zwei-Mikrofon-GCC-PHAT-Halbebenenschaetzung) darf NIE ohne
    # explizite Freigabe eine Kopfbewegung ausloesen -- direction_valid
    # wird ehrlich zurueckgesetzt, auch wenn ein frischer, an sich
    # gueltiger Richtungssample vorliegt.
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True,
                      direction_source_unambiguous=False)
    node._push_direction_sample(azimuth_rad=0.42, confidence=0.9, valid=True)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.direction_valid is False


def test_allow_ambiguous_direction_override_permits_valid_direction():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True,
                      direction_source_unambiguous=False,
                      params={"allow_ambiguous_direction_for_head_orientation": True})
    node._push_direction_sample(azimuth_rad=0.42, confidence=0.9, valid=True)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.direction_valid is True


# ---- _on_focus_state -> aktives Backend (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5) ----

def _focus_state(mode="CONVERSATION_FOCUS", valid=True, azimuth_rad=0.3):
    msg = AudioFocusState()
    msg.mode = mode
    msg.valid = valid
    msg.target_azimuth_rad = azimuth_rad
    return msg


def test_focus_state_conversation_focus_sets_backend_target():
    node = _FakeNode()
    backend = _FakeSteerableBackend()
    node._current_backend = backend
    node._on_focus_state(_focus_state(mode="CONVERSATION_FOCUS", valid=True, azimuth_rad=0.7))
    assert len(backend.focus_calls) == 1
    assert backend.focus_calls[0][0] == 0.7


def test_focus_state_pepper_speaking_also_sets_backend_target():
    node = _FakeNode()
    backend = _FakeSteerableBackend()
    node._current_backend = backend
    node._on_focus_state(_focus_state(mode="PEPPER_SPEAKING", valid=True))
    assert len(backend.focus_calls) == 1


def test_focus_state_invalid_clears_backend_target():
    node = _FakeNode()
    backend = _FakeSteerableBackend()
    node._current_backend = backend
    node._on_focus_state(_focus_state(mode="AUDIO_DEGRADED", valid=False))
    assert backend.clear_calls == 1
    assert backend.focus_calls == []


def test_focus_state_idle_wide_clears_backend_target():
    node = _FakeNode()
    backend = _FakeSteerableBackend()
    node._current_backend = backend
    node._on_focus_state(_focus_state(mode="IDLE_WIDE", valid=False))
    assert backend.clear_calls == 1


def test_focus_state_ignored_without_any_backend():
    node = _FakeNode()
    node._current_backend = None
    node._on_focus_state(_focus_state())  # darf nicht crashen


def test_focus_state_ignored_for_non_steerable_backend():
    class _NonSteerableBackend:
        pass

    node = _FakeNode()
    node._current_backend = _NonSteerableBackend()
    node._on_focus_state(_focus_state())  # darf nicht crashen, kein set_focus_target vorhanden


def test_unambiguous_direction_source_is_unaffected_by_the_gate():
    node = _FakeNode(wakeword_enabled=True, wakeword_detect_result=True,
                      direction_source_unambiguous=True)
    node._push_direction_sample(azimuth_rad=0.42, confidence=0.9, valid=True)
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    event_msg = node.wakeword_event_pub.messages[0]
    assert event_msg.direction_valid is True


# ---- Codewoerter (Entwicklungsauftrag 04-B, AP7, Abschnitt 12/13) ----

def _codeword_rules():
    from ihk_pepper_interaction.codeword_config import parse_codewords
    rules, errors = parse_codewords({"codewords": [
        {"phrase": "eisenbahn", "command": "interrupt_and_look", "required_role": "student"},
    ]})
    assert errors == []
    return rules


def test_matching_codeword_publishes_an_interaction_command():
    node = _FakeNode(codeword_rules=_codeword_rules())
    node._publish_codeword_command_if_matched("also Eisenbahn bitte", time.monotonic(), 1.0)
    assert len(node.interaction_command_raw_pub.messages) == 1
    msg = node.interaction_command_raw_pub.messages[0]
    assert msg.command == "interrupt_and_look"
    assert msg.raw_transcript == "also Eisenbahn bitte"
    assert msg.event_id  # nicht leer


def test_unrelated_text_publishes_nothing():
    node = _FakeNode(codeword_rules=_codeword_rules())
    node._publish_codeword_command_if_matched("wie ist das Wetter heute", time.monotonic(), 1.0)
    assert node.interaction_command_raw_pub.messages == []


def test_codeword_carries_the_real_direction_sample_into_the_command():
    node = _FakeNode(codeword_rules=_codeword_rules())
    now = time.monotonic()
    node._push_direction_sample(azimuth_rad=0.7, confidence=0.9, valid=True, age_s=0.0)
    node._publish_codeword_command_if_matched("Eisenbahn", now, 0.1)
    msg = node.interaction_command_raw_pub.messages[0]
    assert msg.direction_valid is True
    import pytest
    assert msg.direction_azimuth_rad_base == pytest.approx(0.7, abs=1e-5)


def test_codeword_without_any_direction_sample_reports_invalid_direction():
    node = _FakeNode(codeword_rules=_codeword_rules())
    node._publish_codeword_command_if_matched("Eisenbahn", time.monotonic(), 1.0)
    msg = node.interaction_command_raw_pub.messages[0]
    assert msg.direction_valid is False
    assert msg.direction_azimuth_rad_base == 0.0


def test_codeword_is_detected_during_a_confirmed_conversation_past_the_wakeword_window():
    # Ende-zu-Ende durch _handle_utterance(): das Wakeword-Fenster ist
    # abgelaufen, aber ein bestaetigtes, aktives Gespraech haelt die
    # Transkription trotzdem am Laufen (siehe _conversation_confirmed_active()).
    node = _FakeNode(wakeword_enabled=True, codeword_rules=_codeword_rules())
    node._session_active_until = time.monotonic() - 1.0
    AudioNode._on_interaction_state(node, UInt8(data=int(InteractionState.ENGAGED)))
    node._whisper_model = _FakeWhisperModel("Eisenbahn")
    AudioNode._handle_utterance(node, b"\x00\x00" * 1600)
    assert len(node.interaction_command_raw_pub.messages) == 1
    assert node.interaction_command_raw_pub.messages[0].command == "interrupt_and_look"


class _FakeWhisperModel:
    def __init__(self, text):
        self._text = text

    def transcribe(self, audio, language, beam_size, vad_filter):
        class _Segment:
            def __init__(self, text):
                self.text = text
        return [_Segment(self._text)], None
