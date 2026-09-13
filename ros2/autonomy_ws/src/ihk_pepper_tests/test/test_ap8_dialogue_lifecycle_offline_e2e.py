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
    _dialogue_abort_requested = RunDialogueActionServer._dialogue_abort_requested
    _wait_for_question = RunDialogueActionServer._wait_for_question

    def __init__(self, params=None, pipeline_fn=None, gesture_fn=None, safety_ok=True):
        self._params = {
            "thinking_loop_delay_s": 0.05,
            "thinking_loop_max_repetitions": 3,
            "thinking_loop_max_duration_s": 2.0,
            "question_timeout_s": 5.0,
        }
        self._params.update(params or {})
        self.gesture_calls = []
        self.cancel_active_actions_calls = 0
        # _wait_for_question() braucht diese beiden Attribute.
        self._latest_transcript_event = threading.Event()
        self._voice_command = None
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
        self._safety_state = _FakeSafetyState() if safety_ok else None
        self._safety_state_received_at = time.monotonic() if safety_ok else None
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


class _FakeSafetyState:
    """Entwicklungsauftrag 04-B, AP8-R3: _safety_ok() liest jetzt in
    JEDER Wartephase (nicht nur am Rundenanfang) -- braucht deshalb ein
    echtes Objekt mit emergency_stop/bumper_active statt eines reinen
    object()-Platzhalters."""

    emergency_stop = False
    bumper_active = False


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
    node._tracks[7] = (_Track(), time.monotonic() - (MAX_TRACK_AGE_S + 1.0))  # veraltet
    assert RunDialogueActionServer._track_alive(node, 7) is False


def test_scenario_i_track_alive_true_for_a_fresh_track():
    class _Track:
        track_id = 8

    node = _DialogueFakeNode()
    node._tracks[8] = (_Track(), time.monotonic())
    assert RunDialogueActionServer._track_alive(node, 8) is True


def test_scenario_i_person_lost_during_pipeline_aborts_active_system_gestures_promptly():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 6/7 (Testpunkt 8):
    # "Personenverlust waehrend Pipeline storniert aktive Systemgesten."
    # Ein Track, der WAEHREND einer (absichtlich haengenden) Pipeline
    # veraltet, muss denselben sofortigen Abbruchpfad ausloesen wie ein
    # explizites ROS-Cancel -- NICHT erst nach dem natuerlichen
    # Pipeline-Ende bemerkt werden.
    from ihk_pepper_dialog.run_dialogue_action_server import MAX_TRACK_AGE_S

    class _Track:
        track_id = 42

    never_finishes = threading.Event()

    def hanging_pipeline(*a):
        never_finishes.wait(timeout=10.0)  # simuliert eine (zu) lange laufende Pipeline
        return ("plan", None, {
            "final_allowlist": set(), "head_gesture_names": set(),
            "allowed_interaction_states_for_gestures": {}, "current_interaction_state": "CONVERSATION_READY",
        })

    node = _DialogueFakeNode(
        params={"thinking_loop_delay_s": 5.0, "thinking_loop_max_repetitions": 3,
                "thinking_loop_max_duration_s": 6.0},
        pipeline_fn=hanging_pipeline,
    )
    node._tracks[42] = (_Track(), time.monotonic())  # zunaechst frisch
    goal_handle = _FakeGoalHandle()
    feedback, _feedback_calls = _make_feedback()

    def _let_the_track_expire():
        time.sleep(0.2)
        node._tracks[42] = (_Track(), time.monotonic() - (MAX_TRACK_AGE_S + 1.0))  # veraltet

    threading.Thread(target=_let_the_track_expire, daemon=True).start()

    started = time.monotonic()
    result = RunDialogueActionServer._acknowledge_and_run_pipeline(
        node, goal_handle, feedback, "Frage?", "session-i2", {"known": False}, [], 42)
    elapsed = time.monotonic() - started

    assert result is None  # Runde wird sicher uebersprungen, kein Ergebnis verwendet
    assert elapsed < 2.0  # deutlich vor Ablauf der 10s-Pipeline-Haengezeit
    assert node.cancel_active_actions_calls >= 1  # aktive Systemgeste wurde aktiv abgebrochen


def test_wait_for_question_returns_abort_not_timeout_on_safety_loss():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 6 (bestaetigter Fund):
    # ein Safety-Verlust WAEHREND der Frage-Wartephase wurde bisher wie
    # ein Frage-Timeout behandelt (return None -> QUESTION_TIMEOUT,
    # success=True, goal_handle.succeed()) -- obwohl der eigentliche
    # Grund ein Sicherheitsereignis war. '__ABORT__' signalisiert jetzt
    # dem Aufrufer, zur Schleifenspitze zurueckzukehren, die den echten
    # Grund korrekt klassifiziert.
    node = _DialogueFakeNode(
        params={"question_timeout_s": 5.0}, safety_ok=True)
    goal_handle = _FakeGoalHandle()

    def _lose_safety_shortly():
        time.sleep(0.1)
        node._safety_state = None  # Safety-Zustand verloren

    threading.Thread(target=_lose_safety_shortly, daemon=True).start()

    started = time.monotonic()
    result = RunDialogueActionServer._wait_for_question(node, goal_handle)
    elapsed = time.monotonic() - started

    assert result == "__ABORT__"
    assert elapsed < 1.0  # deutlich vor Ablauf der 5s question_timeout_s


def test_wait_for_question_returns_none_on_a_genuine_timeout_with_nothing_else_wrong():
    node = _DialogueFakeNode(params={"question_timeout_s": 0.1}, safety_ok=True)
    goal_handle = _FakeGoalHandle()
    result = RunDialogueActionServer._wait_for_question(node, goal_handle)
    assert result is None  # echter Timeout, kein Abbruchgrund -- unveraendertes Verhalten


def test_scenario_i_track_alive_uses_monotonic_time_not_wall_clock(monkeypatch):
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 4 (bestaetigter Fund):
    # _track_alive() verglich frueher gegen time.time() -- ein
    # Wanduhrsprung rueckwaerts (NTP-Korrektur/manuelle Verstellung)
    # liess einen bereits veralteten Track wieder als frisch erscheinen.
    # Reproduktion der Auftragsvorgabe: Empfang bei (simulierter)
    # Wanduhr 100 -> Pruefung bei 111 (veraltet, MAX_TRACK_AGE_S=2.0) ->
    # Wanduhr springt auf 99 zurueck -- der Track MUSS trotzdem veraltet
    # bleiben, weil _track_alive() time.monotonic() nutzt, das von einem
    # Wanduhrsprung unbeeinflusst ist.
    from ihk_pepper_dialog import run_dialogue_action_server as mod

    class _Track:
        track_id = 9

    node = _DialogueFakeNode()
    fake_wall_clock = {"value": 100.0}
    monkeypatch.setattr(mod.time, "time", lambda: fake_wall_clock["value"])
    # Empfang bei monotonic() = realer Testlaufzeit-Wert (nicht
    # manipuliert) -- nur time.time() wird hier verfaelscht, um zu
    # beweisen, dass _track_alive() davon UNBEEINFLUSST bleibt.
    node._tracks[9] = (_Track(), time.monotonic() - (mod.MAX_TRACK_AGE_S + 1.0))
    assert mod.RunDialogueActionServer._track_alive(node, 9) is False

    fake_wall_clock["value"] = 99.0  # Wanduhr springt zurueck
    assert mod.RunDialogueActionServer._track_alive(node, 9) is False, (
        "Ein veralteter Track darf durch einen Wanduhrsprung nicht wieder frisch werden."
    )
