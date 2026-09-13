"""
Entwicklungsauftrag 04-B, AP8.8, Commit 13/14, Abschnitt 9: vollstaendig
offline arbeitende End-to-End-Szenarien fuer den Dialog-Gesten-Lifecycle.
Verbindet ECHTE Projektlogik (die tatsaechlichen, ungebundenen Methoden
von RunDialogueActionServer/ResponsePlanExecutor, gegen ein
leichtgewichtiges Fake-Node -- gleiches Muster wie
test_dialogue_thinking_loop.py/test_run_dialogue_cancellation.py) statt
nur das Verhalten eigener Fakes zu pruefen. Kein rclpy.init() hier --
ein separater, echter ROS2-Integrationstest existiert in
test_run_dialogue_real_ros2_integration.py (Abschnitt 10).

Nicht alle im Auftrag genannten Szenarien A-N sind hier einzeln
repliziert: A/E/K sind bereits ueber echte ROS2-Action-Kommunikation in
test_run_dialogue_real_ros2_integration.py abgedeckt, G/H/L/M ueber die
bereits bestehenden AP8-R1/R2-Szenarien (test_ap8r1_offline_e2e.py,
Restore-/Breathing-Matrix unveraendert) und die neuen Executor-/
Goal-Handle-Tests in test_response_plan_executor.py/
test_run_dialogue_cancellation.py. Dieses Modul deckt gezielt die
Szenarien ab, die sonst NICHT durch ein anderes Testmodul bewiesen
werden: B (Denkschleife), C (Schleifendeckel), D (optionale Geste
gesperrt, TTS trotzdem), I (Personenverlust waehrend der Antwort-
ausfuehrung).
"""
import threading
import time
from dataclasses import dataclass, field

import pytest

from ihk_pepper_dialog.response_plan_executor import ResponsePlanExecutor
from ihk_pepper_dialog.run_dialogue_action_server import RunDialogueActionServer


# ---- gemeinsame Test-Doubles (gleiches Muster wie test_dialogue_thinking_loop.py) ----

class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass


class _FakeGoalHandle:
    def __init__(self):
        self.is_cancel_requested = False
        self.outcome = None
        self.feedbacks = []

    def publish_feedback(self, fb):
        self.feedbacks.append(fb.state_name)

    def succeed(self):
        self.outcome = "succeeded"

    def abort(self):
        self.outcome = "aborted"

    def canceled(self):
        self.outcome = "canceled"


@dataclass
class _Segment:
    segment_id: str
    text: str
    gesture_name: str = None
    gesture_relation: str = None


@dataclass
class _Plan:
    segments: list = field(default_factory=list)
    source_ids: list = field(default_factory=list)
    memory_summary_candidate: str = None


class _DialogueFakeNode:
    """Bindet die ECHTEN, ungebundenen Methoden von
    RunDialogueActionServer an ein leichtgewichtiges Fake -- kein
    rclpy.init() noetig (gleiches Muster wie test_dialogue_thinking_loop.py/
    test_run_dialogue_cancellation.py)."""

    _run_acknowledge_gesture = RunDialogueActionServer._run_acknowledge_gesture
    _run_thinking_loop = RunDialogueActionServer._run_thinking_loop
    _acknowledge_and_run_pipeline = RunDialogueActionServer._acknowledge_and_run_pipeline
    _recheck_before_gesture = RunDialogueActionServer._recheck_before_gesture
    _runtime_gesture_context = RunDialogueActionServer._runtime_gesture_context
    _safety_ok = RunDialogueActionServer._safety_ok
    _track_alive = RunDialogueActionServer._track_alive

    def __init__(self, params=None, pipeline_fn=None, gesture_fn=None, safety_ok=True):
        self._params = {
            "thinking_loop_delay_s": 0.05,
            "thinking_loop_max_repetitions": 3,
            "thinking_loop_max_duration_s": 2.0,
        }
        self._params.update(params or {})
        self.gesture_calls = []
        self.cancel_active_actions_calls = 0
        # Entwicklungsauftrag 04-B, AP8.8, Abschnitt 3.3: neue
        # Unbestaetigt-Nachverfolgung fuer Systemgesten-Threads --
        # _acknowledge_and_run_pipeline() liest/schreibt dieses Attribut.
        self._unconfirmed_system_gesture_thread = None
        self._pipeline_fn = pipeline_fn or (lambda *a: (
            "plan", None,
            {"final_allowlist": set(), "head_gesture_names": set(),
             "allowed_interaction_states_for_gestures": {}, "current_interaction_state": "CONVERSATION_READY"},
        ))
        self._gesture_fn_override = gesture_fn
        self._current_gesture_recheck_context = None
        self._safety_ok_value = safety_ok
        self._safety_state = object() if safety_ok else None
        self._safety_state_received_at = time.time() if safety_ok else None
        # _runtime_gesture_context() braucht diese FreshBool-artigen
        # Attribute -- fuer die B/C/D-Szenarien reichen einfache
        # Objekte mit einer effective()-Methode, die feste, freigebende
        # Werte liefert (kein Mapping/Nav2/Verbindungsproblem in diesen
        # Tests).
        self._nav2_moving = _FixedEffective(False)
        self._mapping_active = _FixedEffective(False)
        self._gesture_in_progress_fresh = _FixedEffective(False)
        self._pepper_reachable_fresh = _FixedEffective(True)
        self._tracks = {}

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def _gesture_and_wait(self, name, speed_scale):
        self.gesture_calls.append(name)
        if self._gesture_fn_override:
            return self._gesture_fn_override(name, speed_scale)
        return True

    def _run_pipeline(self, question, session_id, person_context, recent_gestures):
        return self._pipeline_fn(question, session_id, person_context, recent_gestures)

    def _cancel_active_actions(self):
        self.cancel_active_actions_calls += 1


class _FixedEffective:
    def __init__(self, value):
        self._value = value

    def effective(self, now, max_age_s, fail_closed_value):
        return self._value


def _make_feedback():
    calls = []

    def feedback(state_value, state_name, partial_transcript=""):
        calls.append(state_name)

    return feedback, calls


# ---- Szenario B: langsame Antwort -- Denkschleife startet nach Verzoegerung ----

def test_scenario_b_thinking_loop_starts_after_delay_and_stops_when_pipeline_finishes():
    pipeline_done = threading.Event()

    def slow_pipeline(question, session_id, person_context, recent_gestures):
        pipeline_done.wait(timeout=3.0)
        return ("plan", None, {
            "final_allowlist": set(), "head_gesture_names": set(),
            "allowed_interaction_states_for_gestures": {}, "current_interaction_state": "CONVERSATION_READY",
        })

    node = _DialogueFakeNode(
        params={"thinking_loop_delay_s": 0.1, "thinking_loop_max_repetitions": 100,
                "thinking_loop_max_duration_s": 10.0},
        pipeline_fn=slow_pipeline,
    )
    goal_handle = _FakeGoalHandle()
    feedback, feedback_calls = _make_feedback()

    def _finish_after_a_bit():
        time.sleep(0.4)  # laenger als thinking_loop_delay_s -- Schleife MUSS gestartet sein
        pipeline_done.set()

    threading.Thread(target=_finish_after_a_bit, daemon=True).start()
    result = RunDialogueActionServer._acknowledge_and_run_pipeline(
        node, goal_handle, feedback, "Wie lange dauert das?", "session-b", {"known": False}, [])

    assert result is not None
    assert "WAITING_FOR_RESPONSE" in feedback_calls  # Denkschleife wurde sichtbar angekuendigt
    assert "thinking_loop_subtle" in node.gesture_calls
    # Nach Pipeline-Ende laeuft KEIN weiterer Zyklus mehr (die Schleife
    # wurde kontrolliert beendet, nicht nur der naechste Zyklus verhindert).
    calls_at_finish = node.gesture_calls.count("thinking_loop_subtle")
    time.sleep(0.2)
    assert node.gesture_calls.count("thinking_loop_subtle") == calls_at_finish


def test_scenario_b_no_thinking_loop_for_a_fast_pipeline():
    # Schnelle Antwort -- die Pipeline ist VOR thinking_loop_delay_s
    # fertig, es darf ueberhaupt keine sichtbare Denkschleife entstehen.
    node = _DialogueFakeNode(
        params={"thinking_loop_delay_s": 5.0, "thinking_loop_max_repetitions": 3,
                "thinking_loop_max_duration_s": 6.0},
        pipeline_fn=lambda *a: ("plan", None, {
            "final_allowlist": set(), "head_gesture_names": set(),
            "allowed_interaction_states_for_gestures": {}, "current_interaction_state": "CONVERSATION_READY",
        }),
    )
    goal_handle = _FakeGoalHandle()
    feedback, feedback_calls = _make_feedback()

    result = RunDialogueActionServer._acknowledge_and_run_pipeline(
        node, goal_handle, feedback, "Kurze Frage?", "session-b2", {"known": False}, [])

    assert result is not None
    assert "WAITING_FOR_RESPONSE" not in feedback_calls
    assert "thinking_loop_subtle" not in node.gesture_calls
    assert "ACKNOWLEDGING" in feedback_calls
    assert "acknowledge_nod_small" in node.gesture_calls


# ---- Szenario C: Schleifendeckel wirken unabhaengig ----

def test_scenario_c_repetition_cap_stops_the_loop_independently_of_duration_cap():
    node = _DialogueFakeNode()
    stop_event = threading.Event()
    RunDialogueActionServer._run_thinking_loop(
        node, stop_event, max_repetitions=2, max_total_duration_s=100.0)  # Dauer-Deckel praktisch nie erreicht
    assert node.gesture_calls.count("thinking_loop_subtle") == 2


def test_scenario_c_duration_cap_stops_the_loop_independently_of_repetition_cap():
    node = _DialogueFakeNode(gesture_fn=lambda name, speed: (time.sleep(0.05) or True))
    stop_event = threading.Event()
    started = time.time()
    RunDialogueActionServer._run_thinking_loop(
        node, stop_event, max_repetitions=100000, max_total_duration_s=0.2)
    elapsed = time.time() - started
    assert elapsed < 1.0  # deutlich weniger, als 100000 Wiederholungen bräuchten
    assert node.gesture_calls.count("thinking_loop_subtle") < 100000


def test_scenario_c_stop_event_prevents_any_further_cycle():
    node = _DialogueFakeNode()
    stop_event = threading.Event()
    stop_event.set()  # bereits VOR dem ersten Zyklus gesetzt
    RunDialogueActionServer._run_thinking_loop(
        node, stop_event, max_repetitions=5, max_total_duration_s=5.0)
    assert node.gesture_calls == []


# ---- Szenario D: optionale Geste durch Recheck gesperrt, TTS trotzdem ----

def test_scenario_d_gesture_rejected_by_recheck_but_say_still_happens():
    # _recheck_before_gesture() blockiert (z.B. Mapping aktiv fuer eine
    # Kopfgeste) -- ResponsePlanExecutor behandelt das wie einen
    # regulaeren Gestenfehlschlag: der (sichere) Text wird TROTZDEM
    # gesprochen, kein Bewegungstransport fand statt.
    node = _DialogueFakeNode()
    node._mapping_active = _FixedEffective(True)  # Mapping aktiv -- sperrt Kopfgesten
    from ihk_pepper_dialog.run_dialogue_action_server import SYSTEM_GESTURES_AFFECTING_HEAD
    assert "acknowledge_nod_small" in SYSTEM_GESTURES_AFFECTING_HEAD

    say_calls = []

    def say_fn(text):
        say_calls.append(text)
        return True

    def gesture_fn(name, speed_scale):
        return RunDialogueActionServer._gesture_and_wait(node, name, speed_scale)

    # _gesture_and_wait() ruft intern _recheck_before_gesture() auf, DAS
    # wiederum node._runtime_gesture_context()/node._safety_ok() nutzt --
    # hier direkt durchgereicht, kein ROS-Client noetig (kein
    # gesture_client-Attribut vorhanden faellt NIE auf, weil
    # _recheck_before_gesture() bereits VOR jedem Client-Zugriff
    # ablehnt).
    executor = ResponsePlanExecutor(
        say_fn=say_fn, gesture_fn=gesture_fn, post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(
        segment_id="a", text="Sicherer Text ohne Bewegung.",
        gesture_name="acknowledge_nod_small", gesture_relation="before_segment")])
    result = executor.execute(plan)

    assert result.segment_results[0].gesture_success is False
    assert say_calls == ["Sicherer Text ohne Bewegung."]


# ---- Szenario I: Personenverlust waehrend der Antwortausfuehrung ----

def test_scenario_i_person_lost_is_detected_via_track_alive():
    node = _DialogueFakeNode()
    # Kein Track fuer track_id 55 jemals empfangen -- _track_alive() muss
    # fail-closed False liefern (kein stillschweigendes "lebt noch").
    assert RunDialogueActionServer._track_alive(node, 55) is False


def test_scenario_i_track_alive_becomes_false_after_max_track_age():
    from ihk_pepper_dialog.run_dialogue_action_server import MAX_TRACK_AGE_S

    class _Track:
        track_id = 7

    node = _DialogueFakeNode()
    node._tracks[7] = (_Track(), time.time() - (MAX_TRACK_AGE_S + 1.0))  # veraltet
    assert RunDialogueActionServer._track_alive(node, 7) is False


def test_scenario_i_track_alive_true_for_a_fresh_track():
    class _Track:
        track_id = 8

    node = _DialogueFakeNode()
    node._tracks[8] = (_Track(), time.time())
    assert RunDialogueActionServer._track_alive(node, 8) is True
