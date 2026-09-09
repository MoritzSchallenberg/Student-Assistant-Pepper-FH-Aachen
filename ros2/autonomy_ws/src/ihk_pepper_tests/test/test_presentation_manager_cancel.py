"""
Tests fuer die Say-Abbruch-Weiterleitung in presentation_manager_node.py
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 13). Gleiches Duck-Typing-
Muster wie test_run_dialogue_cancellation.py -- die ECHTEN, ungebundenen
Methoden von PresentationManagerNode laufen gegen ein leichtgewichtiges
Fake, kein rclpy.init() noetig.
"""
import threading
import time

from rclpy.action import CancelResponse

from ihk_pepper_presentation.presentation_manager_node import PresentationManagerNode


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _NeverDoneFuture:
    def add_done_callback(self, cb):
        pass  # ruft NIE zurueck -- simuliert ein Ergebnis, das nie eintrifft

    def result(self):
        raise RuntimeError("nicht fertig")


class _ImmediateFuture:
    def __init__(self, value):
        self._value = value

    def add_done_callback(self, cb):
        cb(self)

    def result(self):
        return self._value


class _FakeSayResult:
    def __init__(self, success):
        class _R:
            pass
        r = _R()
        r.success = success
        self.result = r


class _FakeGoalHandle:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.cancel_calls = 0

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        return _NeverDoneFuture()


class _FinishingGoalHandle(_FakeGoalHandle):
    """Ein Say-Ziel, dessen Ergebnis SOFORT (synchron) eintrifft."""

    def __init__(self, success=True):
        super().__init__()
        self._success = success

    def get_result_async(self):
        return _ImmediateFuture(_FakeSayResult(self._success))


class _FakeSayClient:
    def __init__(self, goal_handle):
        self.goal_handle = goal_handle

    def wait_for_server(self, timeout_sec=None):
        return True

    def send_goal_async(self, goal):
        return _ImmediateFuture(self.goal_handle)


class _FakeNode:
    _say_and_wait = PresentationManagerNode._say_and_wait
    _cancel_callback = PresentationManagerNode._cancel_callback
    _cancel_active_say = PresentationManagerNode._cancel_active_say

    def __init__(self, goal_handle):
        self.say_client = _FakeSayClient(goal_handle)
        self._active_say_goal_handle = None
        self._active_say_lock = threading.Lock()

    def get_logger(self):
        return _FakeLogger()


def test_cancel_callback_actively_cancels_a_running_say_goal():
    gh = _FakeGoalHandle()
    node = _FakeNode(gh)
    result_holder = {}

    def run():
        result_holder["value"] = node._say_and_wait("Text.", timeout_s=0.3)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    # Begrenzt warten, bis das Ziel als aktiv registriert ist (send_goal_async
    # laeuft im Hintergrundthread, "sofort" ist keine Garantie).
    deadline = time.monotonic() + 1.0
    while node._active_say_goal_handle is None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert node._active_say_goal_handle is gh

    response = node._cancel_callback(goal_handle=None)
    assert response == CancelResponse.ACCEPT
    assert gh.cancel_calls == 1

    t.join(timeout=1.0)
    assert result_holder["value"] is False  # Ergebnis kam nie -- Timeout griff


def test_cancel_active_say_is_a_noop_when_nothing_is_active():
    node = _FakeNode(_FakeGoalHandle())
    node._cancel_active_say()  # darf nicht crashen


def test_cancel_active_say_survives_a_raising_cancel_call():
    class _RaisingGoalHandle(_FakeGoalHandle):
        def cancel_goal_async(self):
            raise RuntimeError("Verbindung verloren")

    node = _FakeNode(_FakeGoalHandle())
    node._active_say_goal_handle = _RaisingGoalHandle()
    node._cancel_active_say()  # darf nicht crashen, obwohl cancel_goal_async() wirft


def test_active_say_goal_handle_cleared_after_result_arrives_normally():
    gh = _FinishingGoalHandle(success=True)
    node = _FakeNode(gh)
    result = node._say_and_wait("Text.", timeout_s=1.0)
    assert result is True
    assert node._active_say_goal_handle is None


def test_active_say_goal_handle_cleared_even_on_say_failure():
    gh = _FinishingGoalHandle(success=False)
    node = _FakeNode(gh)
    result = node._say_and_wait("Text.", timeout_s=1.0)
    assert result is False
    assert node._active_say_goal_handle is None
