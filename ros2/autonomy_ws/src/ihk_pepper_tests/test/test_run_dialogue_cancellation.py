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
