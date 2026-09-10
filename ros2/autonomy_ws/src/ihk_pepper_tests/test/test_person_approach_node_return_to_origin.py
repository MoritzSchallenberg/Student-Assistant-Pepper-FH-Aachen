"""
Tests fuer CaptureOrigin/ReturnToOrigin in person_approach_node.py
(Entwicklungsauftrag 04-B, AP7, Abschnitt 9/12). Gleiches Duck-Typing-
Muster wie test_person_approach_node_follow.py -- die ECHTEN,
ungebundenen Methoden von PersonApproachNode laufen gegen ein
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
from ihk_pepper_navigation.origin_session import OriginStore
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease, RenewActuatorLease


@pytest.fixture(autouse=True)
def _patch_rclpy_ok():
    original = rclpy.ok
    rclpy.ok = lambda: True
    yield
    rclpy.ok = original


# ---- Fakes ----

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
        self.acquire_calls = []
        self.renew_calls = []
        self.release_calls = []

    def wait_for_service(self, timeout_sec=None):
        return self.available

    def call_async(self, request):
        if isinstance(request, AcquireActuatorLease.Request):
            self.acquire_calls.append(request)
            response = AcquireActuatorLease.Response()
            response.granted = self.granted
            response.lease_id = "base-lease-1" if self.granted else ""
            response.reason = self.reason
            return _FakeFuture(response)
        if isinstance(request, RenewActuatorLease.Request):
            self.renew_calls.append(request)
            response = RenewActuatorLease.Response()
            response.success = True
            return _FakeFuture(response)
        self.release_calls.append(request)
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
    uuid = b"\x04" * 16


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
    def __init__(self, ok=True, x=1.0, y=2.0, yaw=0.3):
        self.ok = ok
        self.x, self.y, self.yaw = x, y, yaw

    def lookup_transform(self, target_frame, source_frame, stamp, timeout):
        if not self.ok:
            raise tf2_ros.LookupException("keine TF (Fake)")
        return _FakeTransform(self.x, self.y, self.yaw)


def _safe_state(**overrides):
    defaults = dict(
        allow_motion=True, localization_valid=True, obstacle_data_valid=True,
        charging_cable_connected=False, bumper_active=False, emergency_stop=False,
        reason="",
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


_DEFAULT_PARAMS = {
    "nav2_connect_timeout_s": 2.0,
    "robot_base_frame": "base_link",
    "tf_lookup_timeout_s": 0.5,
    "return_to_origin_max_age_default_s": 1800.0,
    "return_to_origin_timeout_default_s": 5.0,
}


class _FakeNode:
    _goal_id_str = staticmethod(PersonApproachNode._goal_id_str)
    _acquire_base_lease = PersonApproachNode._acquire_base_lease
    _renew_base_lease = PersonApproachNode._renew_base_lease
    _release_base_lease = PersonApproachNode._release_base_lease
    _drive_to_pose = PersonApproachNode._drive_to_pose
    _get_robot_position_in_frame = PersonApproachNode._get_robot_position_in_frame
    _get_robot_pose_in_frame = PersonApproachNode._get_robot_pose_in_frame
    _on_capture_origin = PersonApproachNode._on_capture_origin
    _build_return_to_origin_safety_context = PersonApproachNode._build_return_to_origin_safety_context
    _execute_return_to_origin = PersonApproachNode._execute_return_to_origin

    def __init__(self, nav2_client=None, lease_client=None, params=None,
                 safety_state=None, mapping_active=False, tf_buffer=None):
        self._nav2_client = nav2_client or _FakeNav2Client()
        lease_client = lease_client or _FakeLeaseClient()
        self.acquire_lease_client = lease_client
        self.renew_lease_client = lease_client
        self.release_lease_client = lease_client
        self.nav2_moving_pub = _FakePublisher()
        self._params = dict(_DEFAULT_PARAMS)
        if params:
            self._params.update(params)
        self._safety_state = safety_state if safety_state is not None else _safe_state()
        self._mapping_active = mapping_active
        self._origin_store = OriginStore()
        self.tf_buffer = tf_buffer if tf_buffer is not None else _FakeTFBuffer()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


def _capture_request(session_id="s1", initial_track_id=1, person_id="", group_id="",
                      interaction_id="", reason=""):
    return types.SimpleNamespace(
        session_id=session_id, initial_track_id=initial_track_id,
        person_id=person_id, group_id=group_id,
        interaction_id=interaction_id, reason=reason,
    )


class _CaptureResponse:
    success = False
    origin_id = ""
    reason = ""


def _return_request(session_id="s1", origin_id="o1", max_origin_age_s=0.0, timeout_s=0.0,
                     interaction_id=""):
    return types.SimpleNamespace(
        session_id=session_id, origin_id=origin_id,
        max_origin_age_s=max_origin_age_s, timeout_s=timeout_s,
        interaction_id=interaction_id,
    )


# ---- CaptureOrigin ----

def test_capture_origin_succeeds_and_stores_the_robot_pose():
    node = _FakeNode(tf_buffer=_FakeTFBuffer(ok=True, x=1.5, y=-2.0, yaw=0.7))
    response = node._on_capture_origin(_capture_request(session_id="s1"), _CaptureResponse())
    assert response.success is True
    assert response.origin_id != ""
    ok, reason, record = node._origin_store.validate(response.origin_id, "s1", max_age_s=60.0)
    assert ok is True
    assert record.x == pytest.approx(1.5)
    assert record.y == pytest.approx(-2.0)
    assert record.yaw_rad == pytest.approx(0.7)
    assert record.frame_id == "map"


def test_capture_origin_fails_without_tf():
    node = _FakeNode(tf_buffer=_FakeTFBuffer(ok=False))
    response = node._on_capture_origin(_capture_request(), _CaptureResponse())
    assert response.success is False
    assert response.reason == "keine_tf_fuer_ursprungspose"


def test_capture_origin_refuses_while_mapping_is_active():
    node = _FakeNode(mapping_active=True)
    response = node._on_capture_origin(_capture_request(), _CaptureResponse())
    assert response.success is False
    assert response.reason == "kartierung_aktiv"


# ---- ReturnToOrigin ----

def _captured_node(**node_kwargs):
    node = _FakeNode(**node_kwargs)
    response = node._on_capture_origin(_capture_request(session_id="s1"), _CaptureResponse())
    assert response.success is True
    return node, response.origin_id


def test_return_to_origin_drives_to_the_captured_pose():
    node, origin_id = _captured_node(tf_buffer=_FakeTFBuffer(x=2.0, y=0.0, yaw=0.0))
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert result.success is True
    assert gh.succeeded is True
    assert node._nav2_client.send_goal_calls == 1
    sent_pose = node._nav2_client.sent_poses[0]
    assert sent_pose.pose.position.x == pytest.approx(2.0)
    assert sent_pose.pose.position.y == pytest.approx(0.0)


def test_return_to_origin_rejects_unknown_origin_id():
    node, _origin_id = _captured_node()
    gh = _FakeGoalHandle(_return_request(origin_id="ghost"))
    result = node._execute_return_to_origin(gh)
    assert result.success is False
    assert result.abort_reason == "ursprung_unbekannt"
    assert node._nav2_client.send_goal_calls == 0


def test_return_to_origin_rejects_a_session_id_mismatch():
    node, origin_id = _captured_node()
    gh = _FakeGoalHandle(_return_request(session_id="other-session", origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert result.success is False
    assert result.abort_reason == "ursprung_gehoert_anderer_sitzung"


def test_return_to_origin_rejects_a_stale_origin():
    node, origin_id = _captured_node()
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id, max_origin_age_s=0.001))
    time.sleep(0.05)
    result = node._execute_return_to_origin(gh)
    assert result.success is False
    assert result.abort_reason == "ursprung_veraltet"


def test_return_to_origin_blocked_by_emergency_stop():
    node, origin_id = _captured_node(safety_state=_safe_state(emergency_stop=True))
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert result.abort_reason == "not_stopp_aktiv"
    assert node._nav2_client.send_goal_calls == 0


def test_return_to_origin_blocked_while_mapping_is_active():
    node, origin_id = _captured_node()
    node._mapping_active = True  # z.B. nach dem Sichern erneut gestartet
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert result.abort_reason == "kartierung_aktiv"


def test_return_to_origin_denied_when_base_lease_unavailable():
    node, origin_id = _captured_node(
        lease_client=_FakeLeaseClient(granted=False, reason="von anderem Owner gehalten"))
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert "actuator_arbiter_lease_denied" in result.abort_reason
    assert node._nav2_client.send_goal_calls == 0


def test_return_to_origin_aborts_when_nav2_unreachable():
    node, origin_id = _captured_node(nav2_client=_FakeNav2Client(reachable=False))
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert result.abort_reason == "nav2_nicht_erreichbar"


def test_return_to_origin_reports_final_pose_on_success():
    node, origin_id = _captured_node(tf_buffer=_FakeTFBuffer(x=3.0, y=4.0, yaw=1.0))
    gh = _FakeGoalHandle(_return_request(origin_id=origin_id))
    result = node._execute_return_to_origin(gh)
    assert result.success is True
    assert result.final_pose.pose.position.x == pytest.approx(3.0)
    assert result.final_pose.pose.position.y == pytest.approx(4.0)


# ---- Entwicklungsauftrag 04-B, AP7.1, Abschnitt 3.4: interaction_id-Bindung ----

def test_capture_origin_stores_the_interaction_id():
    node = _FakeNode()
    response = node._on_capture_origin(
        _capture_request(session_id="s1", interaction_id="authorized_follow"),
        _CaptureResponse())
    assert response.success is True
    _ok, _reason, record = node._origin_store.validate(
        response.origin_id, "s1", max_age_s=60.0, interaction_id="authorized_follow")
    assert record.interaction_id == "authorized_follow"


def test_return_to_origin_rejects_a_different_interaction_id():
    node = _FakeNode()
    capture_response = node._on_capture_origin(
        _capture_request(session_id="s1", interaction_id="authorized_follow"),
        _CaptureResponse())
    gh = _FakeGoalHandle(_return_request(
        origin_id=capture_response.origin_id, interaction_id="single_person_conversation"))
    result = node._execute_return_to_origin(gh)
    assert result.success is False
    assert result.abort_reason == "ursprung_gehoert_anderer_interaktion"
    assert node._nav2_client.send_goal_calls == 0


def test_return_to_origin_accepts_a_matching_interaction_id():
    node = _FakeNode()
    capture_response = node._on_capture_origin(
        _capture_request(session_id="s1", interaction_id="authorized_follow"),
        _CaptureResponse())
    gh = _FakeGoalHandle(_return_request(
        origin_id=capture_response.origin_id, interaction_id="authorized_follow"))
    result = node._execute_return_to_origin(gh)
    assert result.success is True
