"""
Tests fuer die Cancel-Weiterleitung in run_dialogue_action_server.py
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 13). Gleiches Duck-Typing-
Muster wie test_dialogue_thinking_loop.py -- die ECHTEN, ungebundenen
Methoden von RunDialogueActionServer laufen gegen ein leichtgewichtiges
Fake, kein rclpy.init() noetig.
"""
from ihk_pepper_dialog.run_dialogue_action_server import RunDialogueActionServer


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def info(self, *a, **kw):
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

    def __init__(self):
        self._active_say_goal_handle = None
        self._active_gesture_goal_handle = None
        # Entwicklungsauftrag 04-B, AP8.8: Call-Token-Registrierung, die
        # _send_goal_and_wait() jetzt nutzt, um active_goal_attr nur vom
        # tatsaechlichen Eigentuemer-Aufruf schreiben/loeschen zu lassen.
        self._active_goal_tokens = {}

    def get_logger(self):
        return _FakeLogger()


def test_send_goal_and_wait_returns_success_on_normal_completion():
    node = _FakeNode()
    client = _FakeActionClient(_FakeGoalHandle(success=True))
    result = node._send_goal_and_wait(client, object(), timeout_s=1.0)
    assert result is True


def test_send_goal_and_wait_returns_false_on_rejected_goal():
    node = _FakeNode()
    client = _FakeActionClient(_FakeGoalHandle(accepted=False))
    result = node._send_goal_and_wait(client, object(), timeout_s=1.0)
    assert result is False


def test_send_goal_and_wait_tracks_active_goal_handle_while_running():
    node = _FakeNode()
    gh = _FakeGoalHandle(never_finishes=True)
    client = _FakeActionClient(gh)
    # timeout_s klein halten -- der Test wartet real auf den Ablauf.
    node._send_goal_and_wait(client, object(), timeout_s=0.05, active_goal_attr="_active_say_goal_handle")
    # Nach Rueckkehr (Timeout+Cancel-Kulanzzeit) wieder zurueckgesetzt.
    assert node._active_say_goal_handle is None


def test_send_goal_and_wait_calls_cancel_goal_async_on_its_own_timeout():
    node = _FakeNode()
    gh = _FakeGoalHandle(never_finishes=True)
    client = _FakeActionClient(gh)
    result = node._send_goal_and_wait(client, object(), timeout_s=0.05)
    assert result is False
    assert gh.cancel_calls == 1


def test_cancel_active_actions_cancels_both_say_and_gesture_handles():
    node = _FakeNode()
    say_gh = _FakeGoalHandle()
    gesture_gh = _FakeGoalHandle()
    node._active_say_goal_handle = say_gh
    node._active_gesture_goal_handle = gesture_gh
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
    node._active_say_goal_handle = _RaisingGoalHandle()
    node._cancel_active_actions()  # darf nicht crashen, obwohl cancel_goal_async() wirft


# ---- Entwicklungsauftrag 04-B, AP8.8 (Commit 13/14, bestaetigter Fund 3.3/7) ----

class _DeferredFuture:
    """Ruft add_done_callback() NICHT sofort auf -- der Test loest sie
    manuell per fire() aus, um eine VERSPAETETE Goal-Acceptance zu
    simulieren (nach dem eigenen Timeout von _send_goal_and_wait())."""

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


def test_late_goal_acceptance_after_own_timeout_is_cancelled_and_never_sets_the_handle():
    node = _FakeNode()
    client = _DeferredActionClient()
    result = node._send_goal_and_wait(
        client, object(), timeout_s=0.05, active_goal_attr="_active_say_goal_handle")
    assert result is False
    assert node._active_say_goal_handle is None

    # Die Annahme trifft ERST JETZT ein -- nachdem _send_goal_and_wait()
    # bereits (mit False) zurueckgekehrt ist.
    late_gh = _FakeGoalHandle(accepted=True, success=True)
    client.future.fire(late_gh)

    assert late_gh.cancel_calls == 1  # sofort storniert, keine normale Fortsetzung
    assert node._active_say_goal_handle is None  # NIE gesetzt worden
    assert "_active_say_goal_handle" not in node._active_goal_tokens


def test_an_unrelated_calls_finally_never_clears_a_different_owners_handle():
    # Bestaetigter Fund: der finally-Block von _send_goal_and_wait()
    # loeschte active_goal_attr bisher UNBEDINGT -- ein fremder, noch
    # aktiver Aufruf (Token-Eigentuemer) haette dadurch seinen Handle
    # verlieren koennen.
    node = _FakeNode()
    sentinel_token = object()
    node._active_goal_tokens["_active_say_goal_handle"] = sentinel_token
    node._active_say_goal_handle = "sentinel_handle"

    gh_rejected = _FakeGoalHandle(accepted=False)
    client = _FakeActionClient(gh_rejected)
    node._send_goal_and_wait(client, object(), timeout_s=1.0, active_goal_attr="_active_say_goal_handle")

    assert node._active_say_goal_handle == "sentinel_handle"
    assert node._active_goal_tokens["_active_say_goal_handle"] is sentinel_token


def test_send_goal_and_wait_clears_its_own_handle_on_normal_completion():
    node = _FakeNode()
    gh = _FakeGoalHandle(accepted=True, success=True)
    client = _FakeActionClient(gh)
    result = node._send_goal_and_wait(
        client, object(), timeout_s=1.0, active_goal_attr="_active_say_goal_handle")
    assert result is True
    assert node._active_say_goal_handle is None
    assert "_active_say_goal_handle" not in node._active_goal_tokens


# ---- Entwicklungsauftrag 04-B, AP8.8, Abschnitt 4: Einzelaktivitaet fuer RunDialogue ----

class _FakeGoalRequest:
    def __init__(self, session_id):
        self.session_id = session_id


class _SingleActivityFakeNode:
    _goal_callback = RunDialogueActionServer._goal_callback

    def __init__(self):
        import threading
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
