"""
Tests fuer die Aktuator-Arbiter-Integration in bridge_node.py
(Entwicklungsauftrag 04-B, AP5B). Gleiches Duck-Typing-Muster wie
test_dialogue_thinking_loop.py: die ECHTEN, ungebundenen Methoden von
PepperBridgeNode laufen gegen ein leichtgewichtiges Fake -- kein
rclpy.init() noetig.
"""
import threading
import time

from ihk_pepper_bridge.bridge_node import PepperBridgeNode
from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_bridge.gesture_execution_policy import GestureExecutionPolicy, PROFILE_OFFLINE_MOCK
from ihk_pepper_interfaces.action import PlayGesture, Say
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease


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


class _FakeFuture:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self):
        return self._result


class _FakeArbiterClient:
    """Simuliert sowohl den Acquire- als auch den Release-Client (beide
    haben dieselbe minimale Schnittstelle: wait_for_service()/call_async())."""

    def __init__(self, available=True, granted=True, reason=""):
        self.available = available
        self.granted = granted
        self.reason = reason
        self.calls = []

    def wait_for_service(self, timeout_sec=None):
        return self.available

    def call_async(self, request):
        self.calls.append(request)
        if isinstance(request, AcquireActuatorLease.Request):
            response = AcquireActuatorLease.Response()
            response.granted = self.granted
            response.lease_id = "lease-1" if self.granted else ""
            response.reason = self.reason
            response.conflicting_owners = [] if self.granted else ["other-owner"]
            return _FakeFuture(response)
        response = ReleaseActuatorLease.Response()
        response.success = True
        return _FakeFuture(response)


class _FakeInterruptChannel:
    def __init__(self):
        self.stop_speech_calls = 0
        self.stop_motion_calls = 0

    def stop_speech(self):
        self.stop_speech_calls += 1

    def stop_motion(self):
        self.stop_motion_calls += 1


class _FakeGoalId:
    uuid = b"\x01" * 16


class _FakeGoalHandle:
    def __init__(self, request):
        self.request = request
        self.is_cancel_requested = False
        self.goal_id = _FakeGoalId()
        self.feedback = []
        self.outcome = None  # "succeeded" | "aborted" | "canceled"

    def publish_feedback(self, fb):
        self.feedback.append(fb)

    def succeed(self):
        self.outcome = "succeeded"

    def abort(self):
        self.outcome = "aborted"

    def canceled(self):
        self.outcome = "canceled"


def _say_request(text="Hallo", allow_interrupt=True, max_duration_s=0.0):
    req = Say.Goal()
    req.text = text
    req.allow_interrupt = allow_interrupt
    req.max_duration_s = max_duration_s
    return req


def _gesture_request(name="greet_open", speed_scale=1.0):
    req = PlayGesture.Goal()
    req.gesture_name = name
    req.speed_scale = speed_scale
    return req


class _FakeNode:
    """Bindet die ECHTEN Methoden von PepperBridgeNode."""

    _acquire_lease = PepperBridgeNode._acquire_lease
    _release_lease = PepperBridgeNode._release_lease
    _goal_id_str = staticmethod(PepperBridgeNode._goal_id_str)
    _goal_callback_say = PepperBridgeNode._goal_callback_say
    _goal_callback_gesture = PepperBridgeNode._goal_callback_gesture
    _execute_say = PepperBridgeNode._execute_say
    _execute_gesture = PepperBridgeNode._execute_gesture
    _on_nav2_moving = PepperBridgeNode._on_nav2_moving
    _current_runtime_context = PepperBridgeNode._current_runtime_context

    def __init__(self, gesture_dir, dry_run=True, arbiter_available=True, arbiter_granted=True,
                 say_fn=None, execution_profile=PROFILE_OFFLINE_MOCK):
        self._params = {"dry_run": dry_run, "execution_profile": execution_profile}
        self.gesture_policy = GestureExecutionPolicy()
        self.catalog = GestureCatalog(gesture_dir)
        assert self.catalog.reload() == []
        self.pepper = _FakePepperClient(say_fn=say_fn)
        self.interrupt_channel = _FakeInterruptChannel()
        self.acquire_lease_client = _FakeArbiterClient(
            available=arbiter_available, granted=arbiter_granted,
            reason="" if arbiter_granted else "Ressourcenkonflikt mit: ['other-owner']",
        )
        self.release_lease_client = _FakeArbiterClient(available=arbiter_available)
        self._say_active = threading.Event()
        self._nav2_moving = False
        self.speaking_pub = _FakePublisher()
        self.gesture_in_progress_pub = _FakePublisher()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(msg)


class _FakePepperClient:
    def __init__(self, say_fn=None):
        self.say_text_only_calls = []
        self._say_fn = say_fn

    def say_text_only(self, text):
        self.say_text_only_calls.append(text)
        if self._say_fn:
            self._say_fn(text)

    def snapshot_joints(self, joints):
        # Neutrale, je Gelenk sicherheitsmargen-gueltige Werte -- ein
        # flaches 0.1 fuer JEDES Gelenk waere fuer manche Gelenke
        # (z.B. RShoulderRoll) ausserhalb der Sicherheitsmarge und wuerde
        # die (absichtlich strenge) Verteidigung-in-der-Tiefe-Pruefung in
        # kinematic_compiler.py auslösen.
        from ihk_pepper_bridge.kinematic_compiler import NEUTRAL_STAND_POSE
        return {j: NEUTRAL_STAND_POSE.get(j, 0.0) for j in joints}

    def restore_joints(self, snapshot, duration=1.5):
        pass

    def set_breathing(self, enabled, part=None):
        pass

    def get_angle(self, joint):
        from ihk_pepper_bridge.kinematic_compiler import NEUTRAL_STAND_POSE
        return NEUTRAL_STAND_POSE.get(joint, 0.0)

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        pass


def _gesture_dir(tmp_path):
    import os
    import shutil
    from ament_index_python.packages import get_package_share_directory
    real_dir = os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")
    dest = str(tmp_path)
    shutil.copy(os.path.join(real_dir, "greet_open.yaml"), os.path.join(dest, "greet_open.yaml"))
    return dest


# ---- Say ----

def test_say_goal_callback_rejects_empty_text(tmp_path):
    from rclpy.action import GoalResponse
    node = _FakeNode(_gesture_dir(tmp_path))
    req = _say_request(text="")
    assert node._goal_callback_say(req) == GoalResponse.REJECT


def test_say_rejects_dangerous_text_at_bridge_boundary(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    goal_handle = _FakeGoalHandle(_say_request(text="Hallo `rm -rf /`"))
    result = node._execute_say(goal_handle)
    assert result.success is False
    assert goal_handle.outcome == "aborted"
    assert node.pepper.say_text_only_calls == []
    assert node.acquire_lease_client.calls == []  # nie eine Lease angefordert


def test_say_denied_by_arbiter_never_calls_say(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), arbiter_granted=False)
    goal_handle = _FakeGoalHandle(_say_request())
    result = node._execute_say(goal_handle)
    assert result.success is False
    assert "Ressourcenkonflikt" in result.error_message
    assert node.pepper.say_text_only_calls == []
    assert goal_handle.outcome == "aborted"


def test_say_succeeds_and_releases_lease(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False)
    goal_handle = _FakeGoalHandle(_say_request(text="Hallo Welt"))
    result = node._execute_say(goal_handle)
    assert result.success is True
    assert goal_handle.outcome == "succeeded"
    assert node.pepper.say_text_only_calls == ["Hallo Welt"]
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1
    assert release_requests[0].lease_id == "lease-1"


def test_say_speaking_pub_goes_false_after_success(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False)
    goal_handle = _FakeGoalHandle(_say_request())
    node._execute_say(goal_handle)
    assert [m.data for m in node.speaking_pub.published] == [True, False]


def test_say_cancel_calls_interrupt_channel_and_cancels_goal(tmp_path):
    def _slow_say(text):
        time.sleep(0.5)

    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, say_fn=_slow_say)
    goal_handle = _FakeGoalHandle(_say_request(allow_interrupt=True))

    def _cancel_soon():
        time.sleep(0.15)
        goal_handle.is_cancel_requested = True

    threading.Thread(target=_cancel_soon, daemon=True).start()
    result = node._execute_say(goal_handle)
    assert node.interrupt_channel.stop_speech_calls == 1
    assert goal_handle.outcome == "canceled"
    assert result.success is False


def test_say_allow_interrupt_false_ignores_normal_cancel(tmp_path):
    def _quick_say(text):
        time.sleep(0.05)

    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, say_fn=_quick_say)
    goal_handle = _FakeGoalHandle(_say_request(allow_interrupt=False))
    goal_handle.is_cancel_requested = True  # von Anfang an "angefordert"
    result = node._execute_say(goal_handle)
    # allow_interrupt=False -> normaler Cancel wird ignoriert, Say laeuft
    # bis zum natuerlichen Ende durch.
    assert result.success is True
    assert node.interrupt_channel.stop_speech_calls == 0


def test_say_max_duration_s_stops_the_call(tmp_path):
    def _slow_say(text):
        time.sleep(2.0)

    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, say_fn=_slow_say)
    goal_handle = _FakeGoalHandle(_say_request(max_duration_s=0.2))
    started = time.time()
    result = node._execute_say(goal_handle)
    elapsed = time.time() - started
    assert elapsed < 2.0  # nicht bis zum natuerlichen Ende (2.0s) gewartet
    assert result.success is False
    assert node.interrupt_channel.stop_speech_calls == 1


# ---- PlayGesture ----

def test_gesture_goal_callback_rejects_empty_name(tmp_path):
    from rclpy.action import GoalResponse
    node = _FakeNode(_gesture_dir(tmp_path))
    req = _gesture_request(name="")
    assert node._goal_callback_gesture(req) == GoalResponse.REJECT


def test_gesture_unknown_name_aborts_without_acquiring_lease(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    goal_handle = _FakeGoalHandle(_gesture_request(name="does_not_exist"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert goal_handle.outcome == "aborted"
    assert node.acquire_lease_client.calls == []


def test_gesture_denied_by_arbiter_never_plays(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), arbiter_granted=False)
    goal_handle = _FakeGoalHandle(_gesture_request())
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "Ressourcenkonflikt" in result.error_message
    assert [m.data for m in node.gesture_in_progress_pub.published] == []


def test_gesture_succeeds_and_releases_lease(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False)
    goal_handle = _FakeGoalHandle(_gesture_request())
    result = node._execute_gesture(goal_handle)
    assert result.success is True
    assert goal_handle.outcome == "succeeded"
    assert [m.data for m in node.gesture_in_progress_pub.published] == [True, False]
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1


def test_gesture_acquire_request_carries_derived_resources(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False)
    goal_handle = _FakeGoalHandle(_gesture_request(name="greet_open"))
    node._execute_gesture(goal_handle)
    acquire_requests = [r for r in node.acquire_lease_client.calls
                        if isinstance(r, AcquireActuatorLease.Request)]
    assert len(acquire_requests) == 1
    # greet_open bewegt Kopf+beide Arme (siehe config/gestures/greet_open.yaml).
    assert set(acquire_requests[0].resources) == {"HEAD", "LEFT_ARM", "RIGHT_ARM"}


# ---- Entwicklungsauftrag 04-B, AP8.1: Ausfuehrungsrichtlinie an der Bridge ----

def test_gesture_execution_policy_rejects_a_dry_run_validated_gesture_in_production(tmp_path):
    # greet_open.yaml ist dry_run_validated, NICHT live_validated (siehe
    # config/gestures/greet_open.yaml) -- production darf es nicht
    # ausfuehren, selbst wenn der Arbiter grosszuegig gewaehrt haette.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION)
    goal_handle = _FakeGoalHandle(_gesture_request(name="greet_open"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "tested_status_unzureichend" in result.error_message
    assert goal_handle.outcome == "aborted"
    # Keine Lease, kein Thread, keine Hardwareaktion -- die Ablehnung
    # geschieht VOR jedem Ressourcenzugriff.
    assert node.acquire_lease_client.calls == []
    assert [m.data for m in node.gesture_in_progress_pub.published] == []


def test_gesture_execution_policy_allows_the_same_gesture_in_offline_mock(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_OFFLINE_MOCK)
    goal_handle = _FakeGoalHandle(_gesture_request(name="greet_open"))
    result = node._execute_gesture(goal_handle)
    assert result.success is True


def test_a_direct_action_call_cannot_bypass_the_policy_via_a_higher_speed_scale(tmp_path):
    # Auftrag Abschnitt 5: "Ein direkter Aufruf von /pepper_bridge/
    # play_gesture umgeht ihn nicht" -- selbst mit einem manipulierten
    # speed_scale bleibt tested_status massgeblich.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION)
    goal_handle = _FakeGoalHandle(_gesture_request(name="greet_open", speed_scale=0.5))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "tested_status_unzureichend" in result.error_message
