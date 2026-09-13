"""
Tests fuer die Cancel-Weiterleitung/Action-Ausfuehrungsregistry in
run_dialogue_action_server.py (Entwicklungsauftrag 04-B, AP5B,
Abschnitt 13; AP8-R3, Abschnitt 3). Gleiches Duck-Typing-Muster wie
test_dialogue_thinking_loop.py -- die ECHTEN, ungebundenen Methoden von
RunDialogueActionServer laufen gegen ein leichtgewichtiges Fake, kein
rclpy.init() noetig.

Entwicklungsauftrag 04-B, AP8-R3 (bestaetigter Fund): die vorherige API
(active_goal_attr-Kwarg, _active_say_goal_handle/_active_gesture_goal_handle-
Attribute, _active_goal_tokens-Dict, _unconfirmed_action_attrs-Set)
wurde durch eine kleine, gemeinsam durch _action_registry_lock
geschuetzte Registry (_action_registry: channel -> _ActionExecutionRecord)
ersetzt -- ein Set von Attributnamen konnte mehrere Ausfuehrungen
DESSELBEN Kanals nicht anhand ihrer Identitaet unterscheiden. Diese
Datei wurde entsprechend auf die neue Registry-API umgestellt.
"""
import threading

from ihk_pepper_dialog.run_dialogue_action_server import (
    RunDialogueActionServer,
    _ActionExecutionRecord,
)


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _FakeActionResult:
    def __init__(self, success):
        class _R:
            pass
        r = _R()
        r.success = success
        self.result = r


class _ImmediateFuture:
    def __init__(self, value):
        self._value = value

    def add_done_callback(self, cb):
        cb(self)

    def result(self):
        return self._value


class _NeverDoneFuture:
    def add_done_callback(self, cb):
        pass  # ruft NIE zurueck -- simuliert eine haengende Anfrage

    def result(self):
        raise RuntimeError("nicht fertig")


class _FakeGoalHandle:
    def __init__(self, accepted=True, success=True, never_finishes=False):
        self.accepted = accepted
        self.cancel_calls = 0
        self._success = success
        self._never_finishes = never_finishes
        self.goal_id = object()

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        if self._never_finishes:
            return _NeverDoneFuture()
        return _ImmediateFuture(_FakeActionResult(self._success))


class _FakeActionClient:
    def __init__(self, goal_handle):
        self.goal_handle = goal_handle
        self.sent_goals = []

    def send_goal_async(self, goal):
        self.sent_goals.append(goal)
        return _ImmediateFuture(self.goal_handle)


class _FakeNode:
    _send_goal_and_wait = RunDialogueActionServer._send_goal_and_wait
    _cancel_active_actions = RunDialogueActionServer._cancel_active_actions
    _has_unconfirmed_action = RunDialogueActionServer._has_unconfirmed_action

    def __init__(self):
        self._action_registry_lock = threading.Lock()
        self._action_registry = {}
        self._active_session_id = "session-test"
        self._response_generation = 0

    def get_logger(self):
        return _FakeLogger()


def test_send_goal_and_wait_returns_success_on_normal_completion():
    node = _FakeNode()
    client = _FakeActionClient(_FakeGoalHandle(success=True))
    result = node._send_goal_and_wait(client, object(), timeout_s=1.0, channel="say", action_type="Say")
    assert result is True


def test_send_goal_and_wait_returns_false_on_rejected_goal():
    node = _FakeNode()
    client = _FakeActionClient(_FakeGoalHandle(accepted=False))
    result = node._send_goal_and_wait(client, object(), timeout_s=1.0, channel="say", action_type="Say")
    assert result is False


def test_send_goal_and_wait_does_not_release_the_channel_after_an_unconfirmed_timeout():
    # Entwicklungsauftrag 04-B, AP8.8/AP8-R3, Abschnitt 3.2: ein Timeout,
    # dem selbst nach der zusaetzlichen Cancel-Kulanzzeit KEIN Ergebnis
    # folgt (never_finishes), beweist kein terminales Ende der Action.
    # Der Handle/Datensatz bleibt deshalb bewusst bestehen (weiterhin per
    # _cancel_active_actions() erreichbar) und der Kanal gilt als
    # unbestaetigt belegt, statt bedingungslos freigegeben zu werden.
    node = _FakeNode()
    gh = _FakeGoalHandle(never_finishes=True)
    client = _FakeActionClient(gh)
    node._send_goal_and_wait(client, object(), timeout_s=0.05, channel="say", action_type="Say")
    record = node._action_registry["say"]
    assert record.handle is gh
    assert record.unconfirmed is True
    assert node._has_unconfirmed_action() is True


def test_send_goal_and_wait_calls_cancel_goal_async_on_its_own_timeout():
    node = _FakeNode()
    gh = _FakeGoalHandle(never_finishes=True)
    client = _FakeActionClient(gh)
    result = node._send_goal_and_wait(client, object(), timeout_s=0.05, channel="gesture", action_type="PlayGesture")
    assert result is False
    assert gh.cancel_calls == 1


def test_cancel_active_actions_cancels_both_say_and_gesture_records():
    node = _FakeNode()
    say_gh = _FakeGoalHandle(never_finishes=True)
    gesture_gh = _FakeGoalHandle(never_finishes=True)
    # Beide Kanaele "aktiv" simulieren (nicht terminal, Handle bereits
    # angenommen) -- direkt ueber die Registry, ohne auf einen echten
    # Timeout warten zu muessen.
    node._action_registry["say"] = _ActionExecutionRecord(
        channel="say", action_type="Say", session_id="s", generation=0, handle=say_gh,
        pending_acceptance=False)
    node._action_registry["gesture"] = _ActionExecutionRecord(
        channel="gesture", action_type="PlayGesture", session_id="s", generation=0, handle=gesture_gh,
        pending_acceptance=False)
    node._cancel_active_actions()
    assert say_gh.cancel_calls == 1
    assert gesture_gh.cancel_calls == 1


def test_cancel_active_actions_is_a_noop_when_nothing_is_active():
    node = _FakeNode()
    node._cancel_active_actions()  # darf nicht crashen


def test_cancel_active_actions_survives_a_failing_cancel_call():
    class _RaisingGoalHandle(_FakeGoalHandle):
        def cancel_goal_async(self):
            raise RuntimeError("Verbindung verloren")

    node = _FakeNode()
    node._action_registry["say"] = _ActionExecutionRecord(
        channel="say", action_type="Say", session_id="s", generation=0,
        handle=_RaisingGoalHandle(), pending_acceptance=False)
    node._cancel_active_actions()  # darf nicht crashen, obwohl cancel_goal_async() wirft


def test_cancel_active_actions_marks_a_still_pending_channel_for_later_cancellation():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 3: "Ausstehende
    # Goal-Acceptance bleibt nachverfolgt" -- steht die Annahme noch
    # aus (kein Handle), setzt _cancel_active_actions() cancel_requested,
    # statt nichts zu tun.
    node = _FakeNode()
    record = _ActionExecutionRecord(
        channel="gesture", action_type="PlayGesture", session_id="s", generation=0)
    node._action_registry["gesture"] = record
    node._cancel_active_actions()
    assert record.cancel_requested is True


# ---- Entwicklungsauftrag 04-B, AP8.8/AP8-R3: verspaetete Annahme/Ergebnisse ----

class _DeferredFuture:
    """Ruft add_done_callback() NICHT sofort auf -- der Test loest sie
    manuell per fire() aus, um eine VERSPAETETE Goal-Acceptance/ein
    verspaetetes Ergebnis zu simulieren."""

    def __init__(self):
        self._cb = None
        self._value = None

    def add_done_callback(self, cb):
        self._cb = cb

    def fire(self, value):
        self._value = value
        self._cb(self)

    def result(self):
        return self._value


class _DeferredActionClient:
    def __init__(self):
        self.future = _DeferredFuture()

    def send_goal_async(self, goal):
        return self.future


def test_late_goal_acceptance_after_own_timeout_is_cancelled_and_frees_the_channel():
    node = _FakeNode()
    client = _DeferredActionClient()
    result = node._send_goal_and_wait(
        client, object(), timeout_s=0.05, channel="say", action_type="Say")
    assert result is False
    record = node._action_registry["say"]
    assert record.unconfirmed is True
    assert record.handle is None

    # Die Annahme trifft ERST JETZT ein -- nachdem _send_goal_and_wait()
    # bereits (mit False) zurueckgekehrt ist. Der Datensatz ist noch
    # immer der AKTUELLE (kein neuer Aufruf konnte waehrend der
    # Unbestaetigt-Sperre starten) -- die verspaetete Annahme wird ueber
    # den bereits gesetzten cancel_requested-Zustand sofort storniert.
    late_gh = _FakeGoalHandle(accepted=True, success=True)
    client.future.fire(late_gh)

    assert late_gh.cancel_calls == 1


def test_an_old_records_late_result_never_touches_a_newer_records_state():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 3 (bestaetigter Fund,
    # exakte Auftragsreproduktion): "Ein altes Result entfernt keine
    # fremde Quarantaene." Erzwingt direkt ueber die Registry die
    # Konstellation, in der ein spaeter eintreffendes Ergebnis fuer
    # Datensatz A auf einen Kanal trifft, der inzwischen von einem
    # ANDEREN Datensatz B belegt ist -- As Callback darf B NICHT
    # veraendern (Pruefung per Objektidentitaet, nicht per Kanalname).
    node = _FakeNode()
    gh_a = _DeferredActionClient()
    node._send_goal_and_wait(gh_a, object(), timeout_s=0.05, channel="gesture", action_type="PlayGesture")
    record_a = node._action_registry["gesture"]
    assert record_a.unconfirmed is True

    # Ziel A wird jetzt (verspaetet) angenommen -- sein Ergebnis-Future
    # wird separat kontrolliert.
    accepted_gh_a = _FakeGoalHandle(accepted=True)
    result_future_a = _DeferredFuture()
    accepted_gh_a.get_result_async = lambda: result_future_a
    gh_a.future.fire(accepted_gh_a)  # storniert sofort (cancel_requested), Datensatz bleibt record_a

    # Simuliert, dass inzwischen ein neuer Datensatz B denselben Kanal
    # belegt (z.B. nachdem record_a irgendwann sauber terminal wurde).
    record_b = _ActionExecutionRecord(
        channel="gesture", action_type="PlayGesture", session_id="session-b", generation=1)
    record_b.unconfirmed = True
    node._action_registry["gesture"] = record_b

    # As spaeter eintreffendes (echtes) Ergebnis darf B NICHT beruehren.
    result_future_a.fire(_FakeActionResult(True))

    assert node._action_registry["gesture"] is record_b
    assert record_b.unconfirmed is True  # unveraendert durch As Ergebnis
    assert record_b.terminal is False


def test_an_old_records_late_acceptance_never_touches_a_newer_records_state():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 3/7 (Testpunkt 2):
    # "Alte verspaetete Goal-Acceptance veraendert keine neue
    # Ausfuehrung." Analog zum obigen Test, diesmal fuer eine verspaetete
    # ANNAHME statt eines verspaeteten Ergebnisses.
    node = _FakeNode()
    client_a = _DeferredActionClient()
    node._send_goal_and_wait(client_a, object(), timeout_s=0.05, channel="say", action_type="Say")
    assert node._action_registry["say"].unconfirmed is True

    record_b = _ActionExecutionRecord(
        channel="say", action_type="Say", session_id="session-b", generation=1)
    node._action_registry["say"] = record_b

    late_gh_a = _FakeGoalHandle(accepted=True, success=True)
    client_a.future.fire(late_gh_a)

    assert late_gh_a.cancel_calls == 1  # sofort storniert
    assert node._action_registry["say"] is record_b  # B komplett unveraendert
    assert record_b.handle is None
    assert record_b.terminal is False


def test_send_goal_and_wait_clears_the_channel_on_normal_completion():
    node = _FakeNode()
    gh = _FakeGoalHandle(accepted=True, success=True)
    client = _FakeActionClient(gh)
    result = node._send_goal_and_wait(
        client, object(), timeout_s=1.0, channel="say", action_type="Say")
    assert result is True
    assert "say" not in node._action_registry  # Kanal wieder frei


class _FakeGoalHandleWithDeferredResult(_FakeGoalHandle):
    """Wird sofort angenommen, aber das Ergebnis kommt erst, wenn der
    Test es manuell per result_future.fire() ausloest -- simuliert ein
    Ziel, dessen Ende weit nach dem eigenen Timeout eintrifft."""

    def __init__(self):
        super().__init__(accepted=True)
        self.result_future = _DeferredFuture()

    def get_result_async(self):
        return self.result_future


def test_a_new_call_is_refused_while_the_same_channel_is_still_unconfirmed():
    # Entwicklungsauftrag 04-B, AP8.8/AP8-R3, Abschnitt 3/9 (Testpunkt 8,
    # "unbestaetigte Say-/Gesture-Action bleibt nachverfolgt"): solange
    # ein Kanal unbestaetigt ist, darf KEINE neue, konkurrierende
    # Ausfuehrung fuer denselben Kanal starten.
    node = _FakeNode()
    gh = _FakeGoalHandleWithDeferredResult()
    client = _FakeActionClient(gh)
    node._send_goal_and_wait(client, object(), timeout_s=0.05, channel="gesture", action_type="PlayGesture")
    assert node._action_registry["gesture"].unconfirmed is True

    other_client = _FakeActionClient(_FakeGoalHandle())
    result = node._send_goal_and_wait(
        other_client, object(), timeout_s=1.0, channel="gesture", action_type="PlayGesture")
    assert result is False
    assert other_client.sent_goals == []  # kein neues Ziel wurde je gesendet


def test_a_late_arriving_result_clears_the_unconfirmed_marker_and_frees_the_channel():
    # Entwicklungsauftrag 04-B, AP8.8/AP8-R3, Abschnitt 3/9 (Testpunkt
    # 10, "spaetes Result raeumt ausschliesslich seinen eigenen
    # Datensatz auf"): das schliesslich doch noch eintreffende Ergebnis
    # hebt die Unbestaetigt-Markierung wieder auf und gibt den Kanal frei.
    node = _FakeNode()
    gh = _FakeGoalHandleWithDeferredResult()
    client = _FakeActionClient(gh)
    node._send_goal_and_wait(client, object(), timeout_s=0.05, channel="gesture", action_type="PlayGesture")
    assert node._action_registry["gesture"].handle is gh
    assert node._action_registry["gesture"].unconfirmed is True

    gh.result_future.fire(_FakeActionResult(True))

    assert "gesture" not in node._action_registry
    assert "say" not in node._action_registry


def test_concurrent_registration_for_the_same_channel_starts_at_most_one_goal():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 3/7/9 (Testpunkt 3):
    # "Gleichzeitige Registrierung desselben Action-Kanals startet
    # hoechstens ein Ziel." Echter Nebenlaeufigkeitstest (Barrier +
    # echte Threads), kein rein sequenzieller Ablauf.
    node = _FakeNode()
    n = 5
    barrier = threading.Barrier(n)
    lock = threading.Lock()
    started = []

    def _worker():
        gh = _FakeGoalHandle(never_finishes=True)
        client = _FakeActionClient(gh)
        barrier.wait()
        # Kurzes, aber real ablaufendes Timeout -- der Kanal bleibt fuer
        # dessen Dauer durchgehend belegt (kein Ergebnis kommt je), gibt
        # den anderen Threads ein deterministisches Zeitfenster, in dem
        # ihre eigene Registrierung abgelehnt werden MUSS.
        node._send_goal_and_wait(client, object(), timeout_s=0.2, channel="say", action_type="Say")
        with lock:
            if client.sent_goals:
                started.append(client)

    threads = [threading.Thread(target=_worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(started) == 1


# ---- Entwicklungsauftrag 04-B, AP8.8, Abschnitt 4: Einzelaktivitaet fuer RunDialogue ----

class _FakeGoalRequest:
    def __init__(self, session_id):
        self.session_id = session_id


class _SingleActivityFakeNode:
    _goal_callback = RunDialogueActionServer._goal_callback

    def __init__(self):
        self._active_execution_lock = threading.Lock()
        self._active_session_id = None

    def get_logger(self):
        return _FakeLogger()


def test_goal_callback_rejects_a_second_goal_while_one_is_active():
    from rclpy.action import GoalResponse
    node = _SingleActivityFakeNode()
    assert node._goal_callback(_FakeGoalRequest("session-1")) == GoalResponse.ACCEPT
    # Sitzung 1 ist jetzt "aktiv" (so wie _goal_callback es reserviert) --
    # ein zweites, gleichzeitiges Ziel wird abgelehnt.
    assert node._goal_callback(_FakeGoalRequest("session-2")) == GoalResponse.REJECT


def test_goal_callback_accepts_a_new_goal_after_the_previous_session_id_was_cleared():
    from rclpy.action import GoalResponse
    node = _SingleActivityFakeNode()
    assert node._goal_callback(_FakeGoalRequest("session-1")) == GoalResponse.ACCEPT
    # Simuliert das Ende der ersten Sitzung (_execute()s finally-Block).
    node._active_session_id = None
    assert node._goal_callback(_FakeGoalRequest("session-2")) == GoalResponse.ACCEPT
