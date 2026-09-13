import threading
import time
from dataclasses import dataclass, field

from ihk_pepper_dialog.response_plan_executor import ResponsePlanExecutor


@dataclass
class _Segment:
    segment_id: str
    text: str
    gesture_name: str = None
    gesture_relation: str = None


@dataclass
class _Plan:
    segments: list = field(default_factory=list)


class _Recorder:
    def __init__(self):
        self.events = []
        self.speaking_history = []
        self.segment_statuses = []

    def say(self, text):
        self.events.append(("say_start", text))
        self.events.append(("say_done", text))
        return True

    def say_fail(self, text):
        self.events.append(("say_start", text))
        return False

    def gesture(self, name, speed):
        self.events.append(("gesture_start", name))
        self.events.append(("gesture_done", name))
        return True

    def gesture_fail(self, name, speed):
        self.events.append(("gesture_start", name))
        return False

    def set_speaking(self, flag):
        self.speaking_history.append(flag)

    def segment_status(self, segment_id, status):
        self.segment_statuses.append((segment_id, status))


def test_speech_only_segment_calls_only_say():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.")])
    result = executor.execute(plan)
    assert result.success is True
    assert rec.events == [("say_start", "Hallo."), ("say_done", "Hallo.")]


def test_before_segment_plays_gesture_fully_then_speaks():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.", gesture_name="wave",
                                     gesture_relation="before_segment")])
    executor.execute(plan)
    assert rec.events == [
        ("gesture_start", "wave"), ("gesture_done", "wave"),
        ("say_start", "Hallo."), ("say_done", "Hallo."),
    ]


def test_after_segment_speaks_then_plays_gesture():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.", gesture_name="wave",
                                     gesture_relation="after_segment")])
    executor.execute(plan)
    assert rec.events == [
        ("say_start", "Hallo."), ("say_done", "Hallo."),
        ("gesture_start", "wave"), ("gesture_done", "wave"),
    ]


def test_with_segment_start_runs_both_concurrently():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.", gesture_name="wave",
                                     gesture_relation="with_segment_start")])
    result = executor.execute(plan)
    assert result.success is True
    starts = [e for e in rec.events if e[0].endswith("_start")]
    assert ("say_start", "Hallo.") in starts
    assert ("gesture_start", "wave") in starts


def test_gesture_failure_marks_segment_failed_but_plan_still_completes_if_say_ok():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture_fail, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.", gesture_name="wave",
                                     gesture_relation="before_segment")])
    result = executor.execute(plan)
    assert result.segment_results[0].gesture_success is False
    assert rec.segment_statuses == [("a", "failed")]


def test_say_failure_aborts_whole_plan():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say_fail, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[
        _Segment(segment_id="a", text="Erstens."),
        _Segment(segment_id="b", text="Zweitens."),
    ])
    result = executor.execute(plan)
    assert result.success is False
    assert len(result.segment_results) == 1  # zweites Segment wurde nie gestartet


def test_cancel_before_next_segment_stops_execution():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)

    original_say = rec.say

    def say_then_cancel(text):
        result = original_say(text)
        executor.cancel()
        return result

    executor._say_fn = say_then_cancel
    plan = _Plan(segments=[
        _Segment(segment_id="a", text="Erstens."),
        _Segment(segment_id="b", text="Zweitens."),
    ])
    result = executor.execute(plan)
    assert result.cancelled is True
    assert len(result.segment_results) == 1


def test_half_duplex_lock_held_until_actual_end():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.05)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.")])
    executor.execute(plan)
    assert rec.speaking_history == [True, False]  # gesetzt VOR Ausfuehrung, aufgehoben NACH Nachlaufzeit


def test_no_double_start_rejects_second_execute_while_busy():
    rec = _Recorder()
    started_second = {"tried": False}

    def blocking_say(text):
        # simuliert eine laufende Ausfuehrung, waehrend derer ein zweiter
        # execute()-Aufruf ankommt
        if not started_second["tried"]:
            started_second["tried"] = True
            result = executor.execute(_Plan(segments=[_Segment(segment_id="x", text="Doppelt.")]))
            assert result.success is False
            assert result.rejected_reason == "bereits_eine_ausfuehrung_aktiv"
        return True

    executor = ResponsePlanExecutor(blocking_say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Erstens.")])
    result = executor.execute(plan)
    assert result.success is True
    assert started_second["tried"] is True


def test_post_speech_pause_is_respected():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.1)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.")])
    t0 = time.time()
    executor.execute(plan)
    elapsed = time.time() - t0
    assert elapsed >= 0.1


def test_segment_status_published_for_every_segment():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[
        _Segment(segment_id="a", text="Erstens."),
        _Segment(segment_id="b", text="Zweitens."),
    ])
    executor.execute(plan)
    assert rec.segment_statuses == [("a", "done"), ("b", "done")]


def test_is_busy_reflects_state():
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    assert executor.is_busy() is False
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.")])
    executor.execute(plan)
    assert executor.is_busy() is False  # nach Abschluss wieder frei


def test_cancel_calls_cancel_active_fn_immediately():
    # Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: cancel() muss NICHT
    # nur ein Flag setzen, sondern sofort den injizierten Hook aufrufen,
    # der eine GERADE LAUFENDE Action aktiv abbricht.
    calls = []
    executor = ResponsePlanExecutor(
        say_fn=lambda text: True, gesture_fn=lambda name, speed: True,
        cancel_active_fn=lambda: calls.append("cancelled"),
    )
    executor.cancel()
    assert calls == ["cancelled"]


def test_cancel_active_fn_is_optional_backward_compatible():
    executor = ResponsePlanExecutor(say_fn=lambda text: True, gesture_fn=lambda name, speed: True)
    executor.cancel()  # darf nicht crashen ohne cancel_active_fn


# ---- Entwicklungsauftrag 04-B, AP8.8 (Commit 13/14, bestaetigte Funde 3.1) ----

def test_cancel_called_before_execute_is_not_wiped_by_execute_start():
    # Bestaetigter Fund: execute() loeschte den Cancel-Flag bisher am
    # ANFANG -- ein cancel() VOR execute() wurde dadurch wirkungslos.
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    executor.cancel()
    plan = _Plan(segments=[_Segment(segment_id="a", text="Sollte nie gesprochen werden.")])
    result = executor.execute(plan)
    assert result.cancelled is True
    assert result.success is False
    assert rec.events == []  # keine Nebenwirkung ausgeloest


def test_cancel_flag_resets_for_the_next_genuine_execution():
    # Nach einem VOLLSTAENDIG abgeschlossenen (nicht abgebrochenen)
    # Durchlauf darf KEIN Cancel-Rest aus einer vorherigen Ausfuehrung
    # den naechsten, neuen Durchlauf blockieren.
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    executor.cancel()
    executor.execute(_Plan(segments=[_Segment(segment_id="a", text="Erster Versuch.")]))
    rec.events.clear()

    result = executor.execute(_Plan(segments=[_Segment(segment_id="b", text="Zweiter Versuch.")]))
    assert result.cancelled is False
    assert result.success is True
    assert ("say_start", "Zweiter Versuch.") in rec.events


def test_cancel_during_before_segment_gesture_prevents_the_following_tts():
    # Bestaetigter Fund: 'before_segment' rief TTS bisher UNBEDINGT nach
    # der Geste auf, auch wenn ein Cancel waehrend der Geste ankam.
    rec = _Recorder()

    def gesture_then_cancel(name, speed):
        rec.events.append(("gesture_start", name))
        executor.cancel()
        rec.events.append(("gesture_done", name))
        return True

    executor = ResponsePlanExecutor(rec.say, gesture_then_cancel, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Sollte nicht gesprochen werden.",
                                     gesture_name="wave", gesture_relation="before_segment")])
    result = executor.execute(plan)
    assert result.cancelled is True
    assert all(e[0] != "say_start" for e in rec.events)


def test_after_segment_does_not_start_gesture_when_tts_failed():
    # Bestaetigter Fund: 'after_segment' startete die Geste bisher auch
    # dann, wenn TTS zuvor fehlgeschlagen war.
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say_fail, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Scheitert.",
                                     gesture_name="wave", gesture_relation="after_segment")])
    result = executor.execute(plan)
    assert result.success is False
    assert all(e[0] != "gesture_start" for e in rec.events)
    assert result.segment_results[0].gesture_attempted is False


def test_after_segment_does_not_start_gesture_when_cancelled_right_after_tts():
    rec = _Recorder()

    def say_then_cancel(text):
        rec.events.append(("say_start", text))
        executor.cancel()
        rec.events.append(("say_done", text))
        return True

    executor = ResponsePlanExecutor(say_then_cancel, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Gesprochen.",
                                     gesture_name="wave", gesture_relation="after_segment")])
    result = executor.execute(plan)
    assert result.cancelled is True
    assert all(e[0] != "gesture_start" for e in rec.events)


def test_post_speech_pause_is_interrupted_by_a_cancel():
    # Bestaetigter Fund: die Nachlaufpause war bisher time.sleep() --
    # reagierte NICHT auf ein waehrend der Pause ankommendes Cancel.
    rec = _Recorder()
    executor = ResponsePlanExecutor(rec.say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=5.0)

    def cancel_soon():
        time.sleep(0.05)
        executor.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.")])
    started = time.time()
    result = executor.execute(plan)
    elapsed = time.time() - started
    assert result.cancelled is True
    assert elapsed < 1.0  # deutlich kuerzer als die volle 5.0s-Pause


def test_double_start_check_is_atomic_under_concurrent_calls():
    # Entwicklungsauftrag 04-B, AP8.8: die Busy-Pruefung/-Setzung muss
    # atomar sein -- mehrere gleichzeitige execute()-Aufrufe duerfen
    # NIEMALS beide erfolgreich starten.
    rec = _Recorder()
    barrier = threading.Barrier(5)
    started_count = {"n": 0}
    lock = threading.Lock()

    def slow_say(text):
        with lock:
            started_count["n"] += 1
        time.sleep(0.05)
        return True

    executor = ResponsePlanExecutor(slow_say, rec.gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.")])
    results = []
    results_lock = threading.Lock()

    def _worker():
        barrier.wait()
        r = executor.execute(plan)
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert started_count["n"] == 1  # genau EIN Durchlauf hat tatsaechlich gesprochen
    accepted = [r for r in results if r.rejected_reason == ""]
    assert len(accepted) == 1


def test_with_segment_start_gesture_exception_is_captured_not_raised():
    # Bestaetigter Fund: eine Ausnahme im Gestenthread wurde bisher
    # stillschweigend verschluckt (threading.Thread), ohne im Ergebnis
    # sichtbar zu sein.
    rec = _Recorder()

    def raising_gesture(name, speed):
        raise RuntimeError("simulierter Gestenfehler")

    executor = ResponsePlanExecutor(rec.say, raising_gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.", gesture_name="wave",
                                     gesture_relation="with_segment_start")])
    result = executor.execute(plan)  # darf NICHT selbst eine Ausnahme werfen
    assert result.segment_results[0].gesture_success is False
    assert "simulierter Gestenfehler" in result.segment_results[0].gesture_error


def test_before_segment_gesture_exception_is_captured_not_raised():
    rec = _Recorder()

    def raising_gesture(name, speed):
        raise RuntimeError("simulierter Gestenfehler")

    executor = ResponsePlanExecutor(rec.say, raising_gesture, rec.set_speaking, rec.segment_status,
                                     post_speech_pause_s=0.0)
    plan = _Plan(segments=[_Segment(segment_id="a", text="Hallo.", gesture_name="wave",
                                     gesture_relation="before_segment")])
    result = executor.execute(plan)
    assert result.segment_results[0].gesture_success is False
    assert "simulierter Gestenfehler" in result.segment_results[0].gesture_error
    # TTS lief trotzdem (Geste ist optional, kein Cancel ausgeloest):
    assert ("say_start", "Hallo.") in rec.events
