"""
Tests fuer orient_to_sound_node.py (Entwicklungsauftrag 04-B, AP6,
Abschnitt 7/12). Gleiches Duck-Typing-Muster wie
test_person_approach_base_lease.py -- die ECHTEN, ungebundenen Methoden
von OrientToSoundNode laufen gegen ein leichtgewichtiges Fake, kein
rclpy.init() und kein echter SetHeadPose-Server noetig.
"""
import threading
import time

import pytest

from ihk_pepper_interaction.orient_to_sound_node import (
    HEAD_PITCH_SAFE_OBSERVATION_RAD,
    HEAD_YAW_OPERATIONAL_MAX_RAD,
    HEAD_YAW_OPERATIONAL_MIN_RAD,
    OrientToSoundNode,
)
from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interaction.safety_topics import FreshBool
from ihk_pepper_interfaces.action import OrientToSound, SetHeadPose
from ihk_pepper_interfaces.msg import SafetyState
from std_msgs.msg import Bool, String, UInt8


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def info(self, *a, **kw):
        pass

    def warn(self, *a, **kw):
        pass


class _FakeStamp:
    def to_msg(self):
        return "stamp"


class _FakeNowResult:
    def __init__(self, nanoseconds):
        self.nanoseconds = nanoseconds


class _FakeClock:
    def __init__(self, now_s):
        self._now_s = now_s

    def now(self):
        return _FakeNowResult(int(self._now_s * 1e9))


class _FakeFuture:
    def __init__(self, value=None, delay_s=0.0):
        self._value = value
        self._delay_s = delay_s

    def add_done_callback(self, cb):
        if self._delay_s <= 0:
            cb(self)
        else:
            def _later():
                time.sleep(self._delay_s)
                cb(self)
            threading.Thread(target=_later, daemon=True).start()

    def result(self):
        return self._value


class _FakeHeadGoalHandle:
    def __init__(self, accepted=True, success=True, error_message="", final_yaw=0.0,
                 result_delay_s=0.0):
        self.accepted = accepted
        self.cancel_calls = 0
        self._success = success
        self._error_message = error_message
        self._final_yaw = final_yaw
        self._result_delay_s = result_delay_s

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        class _R:
            pass
        r = _R()
        result = SetHeadPose.Result()
        result.success = self._success
        result.error_message = self._error_message
        result.final_head_yaw_rad = self._final_yaw
        r.result = result
        return _FakeFuture(r, delay_s=self._result_delay_s)


class _FakeSetHeadPoseClient:
    def __init__(self, goal_handle, reachable=True):
        self.goal_handle = goal_handle
        self.reachable = reachable
        self.sent_goals = []

    def wait_for_server(self, timeout_sec=None):
        return self.reachable

    def send_goal_async(self, goal):
        self.sent_goals.append(goal)
        return _FakeFuture(self.goal_handle)


class _FakeOrientGoalHandle:
    def __init__(self, request):
        self.request = request
        self.is_cancel_requested = False
        self.feedback = []
        self.outcome = None

    def publish_feedback(self, fb):
        self.feedback.append(fb)

    def succeed(self):
        self.outcome = "succeeded"

    def abort(self):
        self.outcome = "aborted"

    def canceled(self):
        self.outcome = "canceled"


class _FakeNode:
    _on_interaction_state = OrientToSoundNode._on_interaction_state
    _on_mapping_active = OrientToSoundNode._on_mapping_active
    _on_nav2_moving = OrientToSoundNode._on_nav2_moving
    _on_connection_state = OrientToSoundNode._on_connection_state
    _on_safety_state = OrientToSoundNode._on_safety_state
    _conversation_active = OrientToSoundNode._conversation_active
    _safety_ok_for_orientation = OrientToSoundNode._safety_ok_for_orientation
    _goal_callback = OrientToSoundNode._goal_callback
    _cancel_callback = OrientToSoundNode._cancel_callback
    _execute = OrientToSoundNode._execute
    _send_goal_and_wait = OrientToSoundNode._send_goal_and_wait

    def __init__(self, set_head_pose_client=None, now_s=1000.0, params=None):
        self._interaction_state_value = InteractionState.IDLE
        self._interaction_state_received_at = None
        self._mapping_active = FreshBool(True)
        self._nav2_moving = FreshBool(True)
        self._connection_state_value = "disconnected"
        self._connection_state_received_at = None
        self._safety_state = None
        self._safety_state_received_at = None
        self.set_head_pose_client = set_head_pose_client
        self._now_s = now_s
        self._params = params or {
            "interaction_state_max_age_s": 3.0,
            "mapping_active_max_age_s": 2.0,
            "nav2_moving_max_age_s": 1.0,
            "connection_state_max_age_s": 5.0,
        }

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock(self._now_s)


def _make_all_clear_node(set_head_pose_client=None, now_s=1000.0):
    node = _FakeNode(set_head_pose_client=set_head_pose_client, now_s=now_s)
    node._interaction_state_value = InteractionState.IDLE
    node._interaction_state_received_at = now_s
    node._mapping_active.update(False, now_s)
    node._nav2_moving.update(False, now_s)
    node._connection_state_value = "connected"
    node._connection_state_received_at = now_s
    safety = SafetyState()
    safety.emergency_stop = False
    safety.bumper_active = False
    node._safety_state = safety
    node._safety_state_received_at = now_s
    return node


def _orient_goal(azimuth_rad=0.5, measured_at_s=1000.0, max_measurement_age_s=5.0):
    req = OrientToSound.Goal()
    req.wakeword_event_id = "event-1"
    req.azimuth_rad_base_link = azimuth_rad
    req.measured_at.sec = int(measured_at_s)
    req.measured_at.nanosec = int((measured_at_s % 1) * 1e9)
    req.max_measurement_age_s = max_measurement_age_s
    return req


# ---- _conversation_active ----

def test_conversation_active_fails_closed_when_never_received():
    node = _FakeNode()
    assert node._conversation_active() is True


def test_conversation_active_false_when_fresh_idle(monkeypatch):
    node = _FakeNode(now_s=1000.0)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node._on_interaction_state(UInt8(data=int(InteractionState.IDLE)))
    assert node._conversation_active() is False


def test_conversation_active_true_when_engaged(monkeypatch):
    node = _FakeNode()
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node._on_interaction_state(UInt8(data=int(InteractionState.ENGAGED)))
    assert node._conversation_active() is True


# ---- _safety_ok_for_orientation ----

def test_safety_ok_when_all_clear(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    ok, reason = node._safety_ok_for_orientation()
    assert ok is True
    assert reason == ""


def test_safety_blocked_by_conversation_active(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    node._interaction_state_value = InteractionState.ENGAGED
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False
    assert "Gespraech" in reason


def test_safety_blocked_by_mapping_active(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    node._mapping_active.update(True, 1000.0)
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False
    assert "Mapping" in reason


def test_safety_blocked_by_nav2_moving(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    node._nav2_moving.update(True, 1000.0)
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False
    assert "Nav2" in reason


def test_safety_blocked_by_stale_connection_state(monkeypatch):
    node = _make_all_clear_node(now_s=1000.0)
    new_now = 1000.0 + 10.0
    monkeypatch.setattr(time, "monotonic", lambda: new_now)
    # NUR connection_state veralten lassen -- alle anderen Signale auf
    # den neuen Zeitpunkt "auffrischen", damit isoliert genau dieser
    # Blockierungsgrund geprueft wird (sonst wuerde zuerst
    # conversation_active durch das ebenfalls veraltete interaction_state
    # blockieren).
    node._interaction_state_received_at = new_now
    node._mapping_active.update(False, new_now)
    node._nav2_moving.update(False, new_now)
    node._safety_state_received_at = new_now
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False
    assert "Verbindung" in reason


def test_safety_blocked_by_disconnected_state(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    node._connection_state_value = "disconnected"
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False


def test_safety_blocked_by_stale_safety_state(monkeypatch):
    node = _make_all_clear_node(now_s=1000.0)
    new_now = 1000.0 + 10.0
    monkeypatch.setattr(time, "monotonic", lambda: new_now)
    node._interaction_state_received_at = new_now
    node._mapping_active.update(False, new_now)
    node._nav2_moving.update(False, new_now)
    node._connection_state_received_at = new_now
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False


def test_safety_blocked_by_emergency_stop(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    node._safety_state.emergency_stop = True
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False
    assert "Sicherheitsereignis" in reason


def test_safety_blocked_by_bumper(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    node = _make_all_clear_node(now_s=1000.0)
    node._safety_state.bumper_active = True
    ok, reason = node._safety_ok_for_orientation()
    assert ok is False


# ---- _execute ----

def test_execute_rejects_stale_measurement_without_calling_set_head_pose(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    client = _FakeSetHeadPoseClient(_FakeHeadGoalHandle())
    node = _make_all_clear_node(set_head_pose_client=client, now_s=1010.0)  # 10s nach measured_at
    goal_handle = _FakeOrientGoalHandle(_orient_goal(measured_at_s=1000.0, max_measurement_age_s=5.0))
    result = node._execute(goal_handle)
    assert result.success is False
    assert "zu alt" in result.error_message
    assert goal_handle.outcome == "aborted"
    assert client.sent_goals == []


def test_execute_rejects_when_safety_not_ok(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    client = _FakeSetHeadPoseClient(_FakeHeadGoalHandle())
    node = _make_all_clear_node(set_head_pose_client=client, now_s=1000.0)
    node._interaction_state_value = InteractionState.ENGAGED
    goal_handle = _FakeOrientGoalHandle(_orient_goal())
    result = node._execute(goal_handle)
    assert result.success is False
    assert client.sent_goals == []
    assert goal_handle.outcome == "aborted"


def test_execute_succeeds_and_uses_fixed_safe_pitch(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    head_gh = _FakeHeadGoalHandle(accepted=True, success=True, final_yaw=0.5)
    client = _FakeSetHeadPoseClient(head_gh)
    node = _make_all_clear_node(set_head_pose_client=client, now_s=1000.0)
    goal_handle = _FakeOrientGoalHandle(_orient_goal(azimuth_rad=0.5))
    result = node._execute(goal_handle)
    assert result.success is True
    assert goal_handle.outcome == "succeeded"
    assert len(client.sent_goals) == 1
    assert client.sent_goals[0].head_pitch_rad == HEAD_PITCH_SAFE_OBSERVATION_RAD


def test_execute_clamps_azimuth_to_operational_yaw_bounds(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    head_gh = _FakeHeadGoalHandle(accepted=True, success=True)
    client = _FakeSetHeadPoseClient(head_gh)
    node = _make_all_clear_node(set_head_pose_client=client, now_s=1000.0)
    goal_handle = _FakeOrientGoalHandle(_orient_goal(azimuth_rad=100.0))
    node._execute(goal_handle)
    assert client.sent_goals[0].head_yaw_rad == HEAD_YAW_OPERATIONAL_MAX_RAD


def test_execute_aborts_when_set_head_pose_unreachable(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    client = _FakeSetHeadPoseClient(_FakeHeadGoalHandle(), reachable=False)
    node = _make_all_clear_node(set_head_pose_client=client, now_s=1000.0)
    goal_handle = _FakeOrientGoalHandle(_orient_goal())
    result = node._execute(goal_handle)
    assert result.success is False
    assert "nicht erreichbar" in result.error_message


def test_execute_propagates_set_head_pose_failure(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    head_gh = _FakeHeadGoalHandle(accepted=True, success=False, error_message="HEAD-Lease verweigert: x")
    client = _FakeSetHeadPoseClient(head_gh)
    node = _make_all_clear_node(set_head_pose_client=client, now_s=1000.0)
    goal_handle = _FakeOrientGoalHandle(_orient_goal())
    result = node._execute(goal_handle)
    assert result.success is False
    assert "HEAD-Lease" in result.error_message
    assert goal_handle.outcome == "aborted"


# ---- _send_goal_and_wait ----

def test_send_goal_and_wait_cancels_set_head_pose_on_own_cancel():
    head_gh = _FakeHeadGoalHandle(accepted=True, success=True, result_delay_s=5.0)
    client = _FakeSetHeadPoseClient(head_gh)
    node = _FakeNode(set_head_pose_client=client)
    orient_goal_handle = _FakeOrientGoalHandle(_orient_goal())

    def _cancel_soon():
        time.sleep(0.05)
        orient_goal_handle.is_cancel_requested = True

    threading.Thread(target=_cancel_soon, daemon=True).start()
    head_goal = SetHeadPose.Goal()
    head_goal.head_yaw_rad = 0.3
    success, final_yaw, error = node._send_goal_and_wait(head_goal, orient_goal_handle, timeout_s=5.0)
    assert success is False
    assert error == "abgebrochen"
    assert head_gh.cancel_calls == 1


def test_send_goal_and_wait_returns_false_on_rejected_goal():
    head_gh = _FakeHeadGoalHandle(accepted=False)
    client = _FakeSetHeadPoseClient(head_gh)
    node = _FakeNode(set_head_pose_client=client)
    orient_goal_handle = _FakeOrientGoalHandle(_orient_goal())
    head_goal = SetHeadPose.Goal()
    success, final_yaw, error = node._send_goal_and_wait(head_goal, orient_goal_handle, timeout_s=2.0)
    assert success is False
    assert "abgelehnt" in error
