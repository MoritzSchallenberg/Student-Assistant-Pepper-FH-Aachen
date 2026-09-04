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
