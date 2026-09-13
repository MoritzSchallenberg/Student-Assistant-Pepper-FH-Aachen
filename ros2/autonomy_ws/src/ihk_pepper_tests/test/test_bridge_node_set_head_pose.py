"""
Tests fuer die SetHeadPose-Action in bridge_node.py (Entwicklungsauftrag
04-B, AP6, Abschnitt 7/12). Gleiches Duck-Typing-Muster wie
test_bridge_node_actuator_arbiter.py -- die ECHTEN, ungebundenen
Methoden von PepperBridgeNode laufen gegen ein leichtgewichtiges Fake,
kein rclpy.init() noetig.
"""
import threading
import time

import pytest

from ihk_pepper_bridge.bridge_node import (
    HEAD_PITCH_OPERATIONAL_MAX_RAD,
    HEAD_PITCH_OPERATIONAL_MIN_RAD,
    HEAD_YAW_OPERATIONAL_MAX_RAD,
    HEAD_YAW_OPERATIONAL_MIN_RAD,
    PepperBridgeNode,
)
from ihk_pepper_bridge.gesture_execution_policy import PROFILE_OFFLINE_MOCK
from ihk_pepper_interfaces.action import SetHeadPose
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
            response.lease_id = "head-lease-1" if self.granted else ""
            response.reason = self.reason
            response.conflicting_owners = [] if self.granted else ["other-owner"]
            return _FakeFuture(response)
        response = ReleaseActuatorLease.Response()
        response.success = True
        return _FakeFuture(response)


class _FakeInterruptChannel:
    def __init__(self):
        self.stop_motion_calls = 0

    def stop_motion(self):
        self.stop_motion_calls += 1


class _FakeGoalId:
    uuid = b"\x03" * 16


class _FakeGoalHandle:
    def __init__(self, request):
        self.request = request
        self.is_cancel_requested = False
        self.goal_id = _FakeGoalId()
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


class _FakePepperClient:
    def __init__(self, play_trajectory_fn=None, final_yaw=None, final_pitch=None):
        self.play_trajectory_calls = []
        self._play_trajectory_fn = play_trajectory_fn
        self._final_yaw = final_yaw
        self._final_pitch = final_pitch

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        self.play_trajectory_calls.append((joint_names, angle_lists, time_lists))
        if self._play_trajectory_fn:
            self._play_trajectory_fn()

    def get_angle(self, joint):
        if joint == "HeadYaw":
            return self._final_yaw
        if joint == "HeadPitch":
            return self._final_pitch
        return None


class _FakeTime:
    def __init__(self, nanoseconds):
        self.nanoseconds = nanoseconds


class _FakeClock:
    def __init__(self, now_s):
        self._now_s = now_s

    def now(self):
        return _FakeTime(int(self._now_s * 1e9))


class _FakeNode:
    _acquire_lease = PepperBridgeNode._acquire_lease
    _release_lease = PepperBridgeNode._release_lease
    _goal_id_str = staticmethod(PepperBridgeNode._goal_id_str)
    _goal_callback_set_head_pose = PepperBridgeNode._goal_callback_set_head_pose
    _execute_set_head_pose = PepperBridgeNode._execute_set_head_pose
    _resource_motion_denied = PepperBridgeNode._resource_motion_denied

    def __init__(self, dry_run=False, arbiter_available=True, arbiter_granted=True,
                 play_trajectory_fn=None, final_yaw=None, final_pitch=None, now_s=1000.0,
                 execution_profile=PROFILE_OFFLINE_MOCK, allow_head_motion=True):
        # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 5: execution_profile
        # bleibt hier immer offline_mock (diese Datei testet nicht die
        # Ausfuehrungsprofile) -- _resource_motion_denied() ist dadurch
        # strukturell ein No-Op, allow_head_motion=True bleibt trotzdem
        # gesetzt fuer den Fall, dass ein Test explizit
        # execution_profile=supervised_hardware_test uebergibt.
        self._params = {
            "dry_run": dry_run, "execution_profile": execution_profile,
            "allow_head_motion": allow_head_motion,
        }
        self.pepper = _FakePepperClient(
            play_trajectory_fn=play_trajectory_fn, final_yaw=final_yaw, final_pitch=final_pitch)
        self.interrupt_channel = _FakeInterruptChannel()
        self.acquire_lease_client = _FakeArbiterClient(
            available=arbiter_available, granted=arbiter_granted,
            reason="" if arbiter_granted else "Ressourcenkonflikt mit: ['other-owner']",
        )
        self.release_lease_client = _FakeArbiterClient(available=arbiter_available)
        self._now_s = now_s

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock(self._now_s)


def _goal(head_yaw_rad=0.5, head_pitch_rad=-0.1, max_speed_scale=1.0,
          source_time_s=1000.0, max_source_age_s=5.0, owner_id="orient_to_sound"):
    req = SetHeadPose.Goal()
    req.head_yaw_rad = head_yaw_rad
    req.head_pitch_rad = head_pitch_rad
    req.max_speed_scale = max_speed_scale
    req.source_stamp.sec = int(source_time_s)
    req.source_stamp.nanosec = int((source_time_s % 1) * 1e9)
    req.max_source_age_s = max_source_age_s
    req.owner_id = owner_id
    return req


def test_succeeds_and_releases_lease():
    node = _FakeNode(final_yaw=0.5, final_pitch=-0.1)
    goal_handle = _FakeGoalHandle(_goal())
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is True
    assert goal_handle.outcome == "succeeded"
    assert len(node.pepper.play_trajectory_calls) == 1
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1


def test_stale_source_data_is_rejected_without_moving():
    node = _FakeNode(now_s=1010.0)  # 10s nach source_stamp
    goal_handle = _FakeGoalHandle(_goal(source_time_s=1000.0, max_source_age_s=5.0))
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is False
    assert "zu alt" in result.error_message
    assert goal_handle.outcome == "aborted"
    assert node.pepper.play_trajectory_calls == []
    assert node.acquire_lease_client.calls == []  # nie eine Lease angefordert


def test_target_beyond_operational_yaw_bound_is_clamped():
    node = _FakeNode(final_yaw=HEAD_YAW_OPERATIONAL_MAX_RAD, final_pitch=0.0)
    goal_handle = _FakeGoalHandle(_goal(head_yaw_rad=HEAD_YAW_OPERATIONAL_MAX_RAD + 1.0))
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is True
    assert "geklemmt" in result.error_message
    sent_yaw = node.pepper.play_trajectory_calls[0][1][0][0]
    assert sent_yaw == HEAD_YAW_OPERATIONAL_MAX_RAD


def test_target_beyond_operational_pitch_bound_is_clamped():
    node = _FakeNode(final_yaw=0.0, final_pitch=HEAD_PITCH_OPERATIONAL_MIN_RAD)
    goal_handle = _FakeGoalHandle(_goal(head_pitch_rad=HEAD_PITCH_OPERATIONAL_MIN_RAD - 1.0))
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is True
    # angle_lists ist der zweite Positionsparameter von play_trajectory().
    sent_pitch = node.pepper.play_trajectory_calls[0][1][1][0]
    assert sent_pitch == HEAD_PITCH_OPERATIONAL_MIN_RAD


def test_never_exceeds_operational_bounds_even_far_out_of_range():
    node = _FakeNode(final_yaw=0.0, final_pitch=0.0)
    goal_handle = _FakeGoalHandle(_goal(head_yaw_rad=100.0, head_pitch_rad=-100.0))
    result = node._execute_set_head_pose(goal_handle)
    sent_yaw = node.pepper.play_trajectory_calls[0][1][0][0]
    sent_pitch = node.pepper.play_trajectory_calls[0][1][1][0]
    assert HEAD_YAW_OPERATIONAL_MIN_RAD <= sent_yaw <= HEAD_YAW_OPERATIONAL_MAX_RAD
    assert HEAD_PITCH_OPERATIONAL_MIN_RAD <= sent_pitch <= HEAD_PITCH_OPERATIONAL_MAX_RAD


def test_denied_by_arbiter_never_moves():
    node = _FakeNode(arbiter_granted=False)
    goal_handle = _FakeGoalHandle(_goal())
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is False
    assert "HEAD-Lease verweigert" in result.error_message
    assert node.pepper.play_trajectory_calls == []
    assert goal_handle.outcome == "aborted"


def test_arbiter_unreachable_never_moves():
    node = _FakeNode(arbiter_available=False)
    goal_handle = _FakeGoalHandle(_goal())
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is False
    assert node.pepper.play_trajectory_calls == []


def test_cancel_calls_interrupt_channel_and_cancels_goal():
    def _slow_move():
        time.sleep(0.4)

    node = _FakeNode(play_trajectory_fn=_slow_move, final_yaw=0.5, final_pitch=-0.1)
    goal_handle = _FakeGoalHandle(_goal())

    def _cancel_soon():
        time.sleep(0.1)
        goal_handle.is_cancel_requested = True

    threading.Thread(target=_cancel_soon, daemon=True).start()
    result = node._execute_set_head_pose(goal_handle)
    assert node.interrupt_channel.stop_motion_calls == 1
    assert goal_handle.outcome == "canceled"
    assert result.success is False


def test_release_lease_called_even_on_error():
    def _raise():
        raise RuntimeError("qicli kaputt")

    node = _FakeNode(play_trajectory_fn=_raise)
    goal_handle = _FakeGoalHandle(_goal())
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is False
    assert goal_handle.outcome == "aborted"
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1


def test_dry_run_never_calls_play_trajectory():
    node = _FakeNode(dry_run=True)
    goal_handle = _FakeGoalHandle(_goal())
    result = node._execute_set_head_pose(goal_handle)
    assert result.success is True
    assert node.pepper.play_trajectory_calls == []


def test_goal_callback_always_accepts():
    from rclpy.action import GoalResponse
    node = _FakeNode()
    assert node._goal_callback_set_head_pose(_goal()) == GoalResponse.ACCEPT
