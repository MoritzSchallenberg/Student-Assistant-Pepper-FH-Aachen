"""
Tests fuer PlanGroupObservationPose/PositionForGroup in
person_approach_node.py (Entwicklungsauftrag 04-B, AP7.1, Abschnitt 17:
Gruppenunterhaltung). Gleiches Duck-Typing-Muster wie
test_person_approach_node_return_to_origin.py/test_person_approach_node_follow.py --
die ECHTEN, ungebundenen Methoden von PersonApproachNode laufen gegen ein
leichtgewichtiges Fake, kein rclpy.init() und kein echtes Nav2/TF noetig.
"""
import math
import time
import types

import pytest
import rclpy
import tf2_ros

import ihk_pepper_navigation.person_approach_node as person_approach_node
from ihk_pepper_navigation.person_approach_node import PersonApproachNode


@pytest.fixture(autouse=True)
def _patch_rclpy_ok():
    original = rclpy.ok
    rclpy.ok = lambda: True
    yield
    rclpy.ok = original


# ---- Fakes (siehe test_person_approach_node_return_to_origin.py/
#      test_person_approach_node_follow.py fuer dasselbe Muster) ----

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


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeFuture:
    def __init__(self, result=None):
        self._result = result

    def done(self):
        return True

    def add_done_callback(self, cb):
        cb(self)

    def result(self):
        return self._result


class _FakeLeaseClient:
    def __init__(self, available=True, granted=True, reason=""):
        self.available = available
        self.granted = granted
        self.reason = reason

    def wait_for_service(self, timeout_sec=None):
        return self.available

    def call_async(self, request):
        from ihk_pepper_interfaces.srv import (
            AcquireActuatorLease, ReleaseActuatorLease, RenewActuatorLease,
        )
        if isinstance(request, AcquireActuatorLease.Request):
            response = AcquireActuatorLease.Response()
            response.granted = self.granted
            response.lease_id = "base-lease-1" if self.granted else ""
            response.reason = self.reason
            return _FakeFuture(response)
        if isinstance(request, RenewActuatorLease.Request):
            response = RenewActuatorLease.Response()
            response.success = True
            return _FakeFuture(response)
        response = ReleaseActuatorLease.Response()
        response.success = True
        return _FakeFuture(response)


class _FakeNav2GoalHandle:
    def __init__(self, accepted=True, nav2_status=4):
        self.accepted = accepted
        self.nav2_status = nav2_status
        self.cancel_calls = 0

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        class _Result:
            pass
        r = _Result()
        r.status = self.nav2_status
        return _FakeFuture(r)


class _FakeNav2Client:
    def __init__(self, reachable=True, nav2_status=4):
        self.reachable = reachable
        self.nav2_status = nav2_status
        self.send_goal_calls = 0
        self.sent_poses = []

    def wait_for_server(self, timeout_sec=None):
        return self.reachable

    def send_goal_async(self, goal):
        self.send_goal_calls += 1
        self.sent_poses.append(goal.pose)
        return _FakeFuture(_FakeNav2GoalHandle(accepted=True, nav2_status=self.nav2_status))


class _FakeGoalId:
    uuid = b"\x05" * 16


class _FakeGoalHandle:
    def __init__(self, request):
        self.request = request
        self.goal_id = _FakeGoalId()
        self.is_cancel_requested = False
        self.feedbacks = []
        self.aborted = False
        self.succeeded = False

    def publish_feedback(self, fb):
        self.feedbacks.append(fb)

    def abort(self):
        self.aborted = True

    def succeed(self):
        self.succeeded = True


class _FakeTransform:
    def __init__(self, x, y, yaw):
        self.transform = types.SimpleNamespace(
            translation=types.SimpleNamespace(x=x, y=y, z=0.0),
            rotation=types.SimpleNamespace(
                x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0)),
        )


class _FakeTFBuffer:
    def __init__(self, ok=True, x=0.0, y=0.0, yaw=0.0):
        self.ok = ok
        self.x, self.y, self.yaw = x, y, yaw

    def lookup_transform(self, target_frame, source_frame, stamp, timeout):
        if not self.ok:
            raise tf2_ros.LookupException("keine TF (Fake)")
        return _FakeTransform(self.x, self.y, self.yaw)


def _safe_state(**overrides):
    defaults = dict(allow_person_approach=True, reason="")
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _track(x=3.0, y=0.3, frame_id="map", has_3d_position=True):
    return types.SimpleNamespace(
        has_3d_position=has_3d_position, frame_id=frame_id,
        position_3d=types.SimpleNamespace(x=x, y=y),
    )


def _group(group_id="g1", member_track_ids=(1, 2), stable=True):
    return types.SimpleNamespace(
        group_id=group_id, member_track_ids=list(member_track_ids), stable=stable,
    )


def _groups_msg(*groups):
    return types.SimpleNamespace(groups=list(groups))


_DEFAULT_PARAMS = {
    "nav2_connect_timeout_s": 2.0,
    "robot_base_frame": "base_link",
    "tf_lookup_timeout_s": 0.5,
    "group_camera_horizontal_fov_deg": 87.0,
    "group_minimum_person_distance_m": 0.8,
    "group_maximum_travel_distance_m": 5.0,
    "group_position_timeout_s": 60.0,
}


class _FakeNode:
    _goal_id_str = staticmethod(PersonApproachNode._goal_id_str)
    _acquire_base_lease = PersonApproachNode._acquire_base_lease
    _renew_base_lease = PersonApproachNode._renew_base_lease
    _release_base_lease = PersonApproachNode._release_base_lease
    _drive_to_pose = PersonApproachNode._drive_to_pose
    _get_robot_position_in_frame = PersonApproachNode._get_robot_position_in_frame
    _get_robot_pose_in_frame = PersonApproachNode._get_robot_pose_in_frame
    _safety_ok_for_approach = PersonApproachNode._safety_ok_for_approach
    _on_groups = PersonApproachNode._on_groups
    _group_by_id = PersonApproachNode._group_by_id
    _group_member_positions_and_frame = PersonApproachNode._group_member_positions_and_frame
    _on_plan_group_observation_pose = PersonApproachNode._on_plan_group_observation_pose
    _execute_position_for_group = PersonApproachNode._execute_position_for_group

    def __init__(self, nav2_client=None, lease_client=None, params=None,
                 tracks=None, safety_state=None, groups=None, tf_buffer=None, zones=None):
        self._nav2_client = nav2_client or _FakeNav2Client()
        lease_client = lease_client or _FakeLeaseClient()
        self.acquire_lease_client = lease_client
        self.renew_lease_client = lease_client
        self.release_lease_client = lease_client
        self.nav2_moving_pub = _FakePublisher()
        self._params = dict(_DEFAULT_PARAMS)
        if params:
            self._params.update(params)
        self._tracks = tracks if tracks is not None else {
            1: (_track(x=3.0, y=0.3), time.time()),
            2: (_track(x=3.0, y=-0.3), time.time()),
        }
        self._safety_state = safety_state if safety_state is not None else _safe_state()
        self._latest_groups = groups
        self.tf_buffer = tf_buffer if tf_buffer is not None else _FakeTFBuffer()
        self.zones = zones if zones is not None else {}

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


class _PlanResponse:
    valid = False
    reason = ""
    target_x = 0.0
    target_y = 0.0
    target_yaw_rad = 0.0
    expected_angular_span_rad = 0.0
    distance_to_nearest_person_m = 0.0


def _plan_request(group_id="g1"):
    return types.SimpleNamespace(group_id=group_id)


def _position_request(group_id="g1"):
    return types.SimpleNamespace(group_id=group_id)


# ---- _group_by_id / _group_member_positions_and_frame ----

def test_group_by_id_finds_the_matching_group():
    node = _FakeNode(groups=_groups_msg(_group(group_id="g1"), _group(group_id="g2")))
    assert node._group_by_id("g2").group_id == "g2"


def test_group_by_id_returns_none_without_any_groups_received():
    node = _FakeNode(groups=None)
    assert node._group_by_id("g1") is None


def test_group_by_id_returns_none_for_an_unknown_id():
    node = _FakeNode(groups=_groups_msg(_group(group_id="g1")))
    assert node._group_by_id("ghost") is None


def test_group_member_positions_skips_members_without_3d_position():
    node = _FakeNode(tracks={
        1: (_track(x=1.0, y=0.0, has_3d_position=True), time.time()),
        2: (_track(has_3d_position=False), time.time()),
    })
    positions, frame_id, ok, reason = node._group_member_positions_and_frame(
        _group(member_track_ids=(1, 2)))
    assert ok is True
    assert positions == [(1.0, 0.0)]
    assert frame_id == "map"


def test_group_member_positions_rejects_mixed_frames():
    node = _FakeNode(tracks={
        1: (_track(frame_id="map"), time.time()),
        2: (_track(frame_id="base_link"), time.time()),
    })
    positions, frame_id, ok, reason = node._group_member_positions_and_frame(
        _group(member_track_ids=(1, 2)))
    assert ok is False
    assert reason == "gemischte_frames_in_gruppe"


# ---- PlanGroupObservationPose ----

def test_plan_group_observation_pose_succeeds_for_a_stable_group():
    node = _FakeNode(groups=_groups_msg(_group()))
    response = node._on_plan_group_observation_pose(_plan_request(), _PlanResponse())
    assert response.valid is True
    assert response.reason == "ok"


def test_plan_group_observation_pose_rejects_an_unknown_group():
    node = _FakeNode(groups=_groups_msg(_group(group_id="other")))
    response = node._on_plan_group_observation_pose(_plan_request("g1"), _PlanResponse())
    assert response.valid is False
    assert response.reason == "gruppe_unbekannt"


def test_plan_group_observation_pose_rejects_an_unstable_group():
    node = _FakeNode(groups=_groups_msg(_group(stable=False)))
    response = node._on_plan_group_observation_pose(_plan_request(), _PlanResponse())
    assert response.valid is False
    assert response.reason == "gruppe_nicht_stabil"


def test_plan_group_observation_pose_rejects_too_few_members_with_position():
    node = _FakeNode(
        groups=_groups_msg(_group()),
        tracks={1: (_track(has_3d_position=False), time.time())},
    )
    response = node._on_plan_group_observation_pose(_plan_request(), _PlanResponse())
    assert response.valid is False
    assert response.reason == "zu_wenige_mitglieder_mit_position"


def test_plan_group_observation_pose_rejects_without_tf():
    node = _FakeNode(groups=_groups_msg(_group()), tf_buffer=_FakeTFBuffer(ok=False))
    response = node._on_plan_group_observation_pose(_plan_request(), _PlanResponse())
    assert response.valid is False
    assert response.reason == "keine_tf_fuer_roboterpose"


# ---- PositionForGroup ----

def test_position_for_group_drives_to_the_planned_pose():
    node = _FakeNode(groups=_groups_msg(_group()))
    gh = _FakeGoalHandle(_position_request())
    result = node._execute_position_for_group(gh)
    assert result.success is True
    assert gh.succeeded is True
    assert node._nav2_client.send_goal_calls == 1


def test_position_for_group_rejects_without_group_id():
    node = _FakeNode(groups=_groups_msg(_group()))
    gh = _FakeGoalHandle(_position_request(group_id=""))
    result = node._execute_position_for_group(gh)
    assert result.success is False
    assert result.abort_reason == "keine_gruppen_id"
    assert node._nav2_client.send_goal_calls == 0


def test_position_for_group_blocked_by_safety():
    node = _FakeNode(
        groups=_groups_msg(_group()),
        safety_state=_safe_state(allow_person_approach=False, reason="anhalten"),
    )
    gh = _FakeGoalHandle(_position_request())
    result = node._execute_position_for_group(gh)
    assert result.success is False
    assert result.abort_reason == "safety_abort:anhalten"
    assert node._nav2_client.send_goal_calls == 0


def test_position_for_group_rejects_an_unknown_group():
    node = _FakeNode(groups=_groups_msg(_group(group_id="other")))
    gh = _FakeGoalHandle(_position_request("g1"))
    result = node._execute_position_for_group(gh)
    assert result.success is False
    assert result.abort_reason == "gruppe_unbekannt_oder_nicht_stabil"


def test_position_for_group_rejects_an_unstable_group():
    node = _FakeNode(groups=_groups_msg(_group(stable=False)))
    gh = _FakeGoalHandle(_position_request())
    result = node._execute_position_for_group(gh)
    assert result.success is False
    assert result.abort_reason == "gruppe_unbekannt_oder_nicht_stabil"


def test_position_for_group_aborts_when_nav2_is_unreachable():
    node = _FakeNode(groups=_groups_msg(_group()), nav2_client=_FakeNav2Client(reachable=False))
    gh = _FakeGoalHandle(_position_request())
    result = node._execute_position_for_group(gh)
    assert result.success is False
    assert result.abort_reason == "nav2_nicht_erreichbar"


def test_position_for_group_denied_when_base_lease_unavailable():
    node = _FakeNode(
        groups=_groups_msg(_group()),
        lease_client=_FakeLeaseClient(granted=False, reason="von anderem Owner gehalten"),
    )
    gh = _FakeGoalHandle(_position_request())
    result = node._execute_position_for_group(gh)
    assert "actuator_arbiter_lease_denied" in result.abort_reason
    assert node._nav2_client.send_goal_calls == 0


def test_position_for_group_never_drives_onto_the_group_center():
    # Verteidigung in der Tiefe (siehe test_group_observation_pose.py): auch
    # ueber den vollen PositionForGroup-Pfad darf das gesendete Nav2-Ziel
    # nicht auf dem Gruppenzentrum liegen.
    node = _FakeNode(groups=_groups_msg(_group()))
    gh = _FakeGoalHandle(_position_request())
    result = node._execute_position_for_group(gh)
    assert result.success is True
    sent_pose = node._nav2_client.sent_poses[0]
    center = (3.0, 0.0)
    dist_to_center = math.hypot(
        sent_pose.pose.position.x - center[0], sent_pose.pose.position.y - center[1])
    assert dist_to_center >= 0.3
