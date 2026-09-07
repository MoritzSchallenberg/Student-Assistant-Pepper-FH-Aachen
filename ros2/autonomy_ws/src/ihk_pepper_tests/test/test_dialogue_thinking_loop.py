"""
Tests fuer die "Mhm"-/Denksequenz-Orchestrierung in
run_dialogue_action_server.py (Ergaenzungsauftrag 04-A) --
_run_acknowledge_gesture()/_run_thinking_loop()/
_acknowledge_and_run_pipeline().

Diese drei Methoden sind reine Ablauflogik ueber bereits injizierbare
Schnittstellen (get_parameter()/_gesture_and_wait()/_run_pipeline()) --
kein rclpy.init()/kein echter Node noetig. Die Tests rufen die
UNGEBUNDENEN Methoden direkt von der Klasse gegen ein leichtgewichtiges
Fake-Objekt auf (Python erzwingt fuer `self` keine echte Instanz) --
vermeidet einen echten ROS2-Node-Start nur um Timing-/Thread-Logik zu
pruefen, waehrend trotzdem exakt derselbe Code laeuft wie im echten
Node.
"""
import threading
import time

from ihk_pepper_dialog.run_dialogue_action_server import RunDialogueActionServer


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeGoalHandle:
    def __init__(self):
        self.is_cancel_requested = False


class _FakeLogger:
    def warn(self, *_a, **_kw):
        pass

    def info(self, *_a, **_kw):
        pass


class _FakeNode:
    """Duck-typed Ersatz fuer RunDialogueActionServer -- nur die
    Attribute/Methoden, die _run_thinking_loop()/_run_acknowledge_gesture()/
    _acknowledge_and_run_pipeline() tatsaechlich anfassen."""

    def __init__(self, params=None, pipeline_fn=None, gesture_fn=None):
        self._params = params or {}
        self.gesture_calls = []
        self._pipeline_fn = pipeline_fn or (lambda *a: ("plan", None))
        self._gesture_fn_override = gesture_fn

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def _gesture_and_wait(self, name, speed_scale):
        self.gesture_calls.append(name)
        if self._gesture_fn_override:
            return self._gesture_fn_override(name, speed_scale)
        time.sleep(0.05)  # simuliert eine kurze, aber echte Ausfuehrungsdauer
        return True

    def _run_pipeline(self, question, session_id, person_context):
        return self._pipeline_fn(question, session_id, person_context)


# _acknowledge_and_run_pipeline() ruft self._run_acknowledge_gesture()/
# self._run_thinking_loop() auf -- dieselben (echten, ungebundenen)
# Implementierungen hier an das Fake-Objekt haengen, statt sie nachzu-
# bauen, damit die Orchestrierungstests exakt denselben Code fuer alle
# drei Methoden durchlaufen wie der echte Node.
_FakeNode._run_acknowledge_gesture = RunDialogueActionServer._run_acknowledge_gesture
_FakeNode._run_thinking_loop = RunDialogueActionServer._run_thinking_loop


def _make_feedback_recorder():
    calls = []

    def feedback(state_value, state_name, partial_transcript=""):
        calls.append((state_value, state_name))

    return feedback, calls


# ---- _run_acknowledge_gesture ----

def test_acknowledge_gesture_plays_acknowledge_nod_small():
    node = _FakeNode()
    RunDialogueActionServer._run_acknowledge_gesture(node)
    assert node.gesture_calls == ["acknowledge_nod_small"]


def test_acknowledge_gesture_swallows_exception():
    def failing_gesture(name, speed_scale):
        raise RuntimeError("simulierter Fehler")

    node = _FakeNode(gesture_fn=failing_gesture)
    # darf NICHT werfen -- ein fehlgeschlagenes Bestaetigungsnicken darf
    # den restlichen Dialog nicht abreissen lassen.
    RunDialogueActionServer._run_acknowledge_gesture(node)


# ---- _run_thinking_loop ----

def test_thinking_loop_stops_immediately_if_stop_event_already_set():
    node = _FakeNode()
    stop_event = threading.Event()
    stop_event.set()
    RunDialogueActionServer._run_thinking_loop(node, stop_event, max_repetitions=3, max_total_duration_s=10.0)
    assert node.gesture_calls == []


def test_thinking_loop_respects_max_repetitions():
    node = _FakeNode()
    stop_event = threading.Event()
    RunDialogueActionServer._run_thinking_loop(node, stop_event, max_repetitions=2, max_total_duration_s=10.0)
    assert node.gesture_calls == ["thinking_loop_subtle", "thinking_loop_subtle"]


def test_thinking_loop_respects_max_total_duration():
    def slow_gesture(name, speed_scale):
        time.sleep(0.1)
        return True

    node = _FakeNode(gesture_fn=slow_gesture)
    stop_event = threading.Event()
    RunDialogueActionServer._run_thinking_loop(node, stop_event, max_repetitions=100, max_total_duration_s=0.25)
    # bei 0.1s pro Zyklus und 0.25s Obergrenze duerfen es nicht alle 100 sein
    assert 0 < len(node.gesture_calls) < 100


def test_thinking_loop_stops_between_cycles_when_stop_event_set_concurrently():
    stop_event = threading.Event()

    def gesture_that_stops_after_first_call(name, speed_scale):
        stop_event.set()  # simuliert: Pipeline ist waehrend des ersten Zyklus fertig geworden
        return True

    node = _FakeNode(gesture_fn=gesture_that_stops_after_first_call)
    RunDialogueActionServer._run_thinking_loop(node, stop_event, max_repetitions=10, max_total_duration_s=10.0)
    assert node.gesture_calls == ["thinking_loop_subtle"]  # nicht alle 10 Zyklen


def test_thinking_loop_stops_on_gesture_exception():
    def failing_gesture(name, speed_scale):
        raise RuntimeError("simulierter Fehler")

    node = _FakeNode(gesture_fn=failing_gesture)
    stop_event = threading.Event()
    RunDialogueActionServer._run_thinking_loop(node, stop_event, max_repetitions=10, max_total_duration_s=10.0)
    assert node.gesture_calls == ["thinking_loop_subtle"]  # bricht nach dem ersten Fehler ab, kein Crash


# ---- _acknowledge_and_run_pipeline ----

def test_fast_pipeline_never_starts_thinking_loop():
    """Auftrag-Vorgabe: erst NACH thinking_loop_delay_s Wartezeit wird
    ueberhaupt eine sichtbare Denkschleife gestartet."""
    node = _FakeNode(params={
        "thinking_loop_delay_s": 1.0,
        "thinking_loop_max_repetitions": 3,
        "thinking_loop_max_duration_s": 6.0,
    })
    goal_handle = _FakeGoalHandle()
    feedback, feedback_calls = _make_feedback_recorder()

    result = RunDialogueActionServer._acknowledge_and_run_pipeline(
        node, goal_handle, feedback, "Testfrage", "session-1", {"known": False})

    assert result == ("plan", None)
    assert "thinking_loop_subtle" not in node.gesture_calls
    assert "acknowledge_nod_small" in node.gesture_calls
    states = [name for _val, name in feedback_calls]
    assert states == ["ACKNOWLEDGING", "THINKING"]  # kein WAITING_FOR_RESPONSE


def test_slow_pipeline_starts_thinking_loop_and_stops_when_pipeline_finishes():
    pipeline_done = threading.Event()

    def slow_pipeline(question, session_id, person_context):
        pipeline_done.wait(timeout=2.0)
        return ("plan", "summary")

    node = _FakeNode(params={
        "thinking_loop_delay_s": 0.1,
        "thinking_loop_max_repetitions": 10,
        "thinking_loop_max_duration_s": 6.0,
    }, pipeline_fn=slow_pipeline)
    goal_handle = _FakeGoalHandle()
    feedback, feedback_calls = _make_feedback_recorder()

    def _finish_pipeline_soon():
        time.sleep(0.4)  # nach thinking_loop_delay_s -- die Schleife sollte inzwischen laufen
        pipeline_done.set()

    threading.Thread(target=_finish_pipeline_soon, daemon=True).start()
    result = RunDialogueActionServer._acknowledge_and_run_pipeline(
        node, goal_handle, feedback, "Testfrage", "session-1", {"known": False})

    assert result == ("plan", "summary")
    assert "thinking_loop_subtle" in node.gesture_calls
    states = [name for _val, name in feedback_calls]
    assert states == ["ACKNOWLEDGING", "THINKING", "WAITING_FOR_RESPONSE"]


def test_cancel_request_stops_thinking_loop_early():
    pipeline_done = threading.Event()

    def slow_pipeline(question, session_id, person_context):
        pipeline_done.wait(timeout=3.0)
        return ("plan", None)

    node = _FakeNode(params={
        "thinking_loop_delay_s": 0.05,
        "thinking_loop_max_repetitions": 100,
        "thinking_loop_max_duration_s": 10.0,
    }, pipeline_fn=slow_pipeline)
    goal_handle = _FakeGoalHandle()
    feedback, _calls = _make_feedback_recorder()

    def _cancel_then_finish():
        time.sleep(0.2)
        goal_handle.is_cancel_requested = True
        time.sleep(0.2)
        pipeline_done.set()

    threading.Thread(target=_cancel_then_finish, daemon=True).start()
    start = time.time()
    RunDialogueActionServer._acknowledge_and_run_pipeline(
        node, goal_handle, feedback, "Testfrage", "session-1", {"known": False})
    elapsed = time.time() - start

    # Die Denkschleife wurde vorzeitig gestoppt -- deutlich weniger als
    # die 100*~0.05s (Fake-Gestendauer), die ohne Abbruch noetig waeren.
    assert len(node.gesture_calls) < 20
    assert elapsed < 2.0
