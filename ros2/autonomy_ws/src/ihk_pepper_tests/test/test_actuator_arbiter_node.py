"""
Tests fuer actuator_arbiter_node.py (Entwicklungsauftrag 04-B, AP5B).
Gleiches Duck-Typing-Muster wie test_dialogue_thinking_loop.py: die
ECHTEN, ungebundenen Methoden von ActuatorArbiterNode laufen gegen ein
leichtgewichtiges Fake -- kein rclpy.init() noetig.
"""
import time

from ihk_pepper_interaction.actuator_arbiter import ActuatorArbiter, HEAD, PRIORITY_DIALOGUE, SPEECH
from ihk_pepper_interaction.actuator_arbiter_node import ActuatorArbiterNode
from ihk_pepper_interfaces.msg import SafetyState
from ihk_pepper_interfaces.srv import (
    AcquireActuatorLease,
    CancelActuation,
    ReleaseActuatorLease,
    RenewActuatorLease,
)


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(msg)


class _FakeNode:
    _on_safety_state = ActuatorArbiterNode._on_safety_state
    _safety_ok = ActuatorArbiterNode._safety_ok
    _effective_priority = ActuatorArbiterNode._effective_priority
    _handle_acquire = ActuatorArbiterNode._handle_acquire
    _handle_renew = ActuatorArbiterNode._handle_renew
    _handle_release = ActuatorArbiterNode._handle_release
    _handle_cancel = ActuatorArbiterNode._handle_cancel
    _get_default_ttl = ActuatorArbiterNode._get_default_ttl
    _publish_state = ActuatorArbiterNode._publish_state

    def __init__(self):
        self._params = {"default_ttl_s": 30.0}
        self._arbiter = ActuatorArbiter(now_fn=time.monotonic)
        self._safety_state = None
        self._safety_state_received_at = None
        self._last_abort_reason = ""
        self._last_abort_confirmed = False
        self.state_pub = _FakePublisher()
        self.diagnostics_pub = _FakePublisher()
        self.base_lease_valid_pub = _FakePublisher()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        class _C:
            def now(self_inner):
                class _T:
                    def to_msg(self_inner2):
                        return None
                return _T()
        return _C()

    def mark_safety_ok(self, emergency_stop=False, bumper_active=False, age_s=0.0):
        msg = SafetyState()
        msg.emergency_stop = emergency_stop
        msg.bumper_active = bumper_active
        self._on_safety_state(msg)
        if age_s:
            self._safety_state_received_at = time.monotonic() - age_s


def _acquire_request(owner_id="dialog", resources=(SPEECH,), priority=PRIORITY_DIALOGUE, ttl_s=30.0, goal_id=""):
    req = AcquireActuatorLease.Request()
    req.owner_id = owner_id
    req.resources = list(resources)
    req.purpose = "test"
    req.priority = priority
    req.ttl_s = ttl_s
    req.goal_id = goal_id
    return req


def test_acquire_rejected_before_any_safety_state_received():
    node = _FakeNode()
    response = node._handle_acquire(_acquire_request(), AcquireActuatorLease.Response())
    assert response.granted is False


def test_acquire_granted_after_fresh_safety_ok():
    node = _FakeNode()
    node.mark_safety_ok()
    response = node._handle_acquire(_acquire_request(), AcquireActuatorLease.Response())
    assert response.granted is True
    assert response.lease_id != ""


def test_acquire_rejected_with_stale_safety_state():
    node = _FakeNode()
    node.mark_safety_ok(age_s=999.0)
    response = node._handle_acquire(_acquire_request(), AcquireActuatorLease.Response())
    assert response.granted is False


def test_untrusted_owner_cannot_claim_emergency_priority():
    node = _FakeNode()
    node.mark_safety_ok()
    from ihk_pepper_interaction.actuator_arbiter import PRIORITY_EMERGENCY_STOP, PRIORITY_RETURN_TO_SAFE
    effective = node._effective_priority("run_dialogue_action_server", PRIORITY_EMERGENCY_STOP)
    assert effective == PRIORITY_RETURN_TO_SAFE


def test_trusted_owner_prefix_keeps_emergency_priority():
    node = _FakeNode()
    from ihk_pepper_interaction.actuator_arbiter import PRIORITY_EMERGENCY_STOP
    effective = node._effective_priority("motion_guard_node", PRIORITY_EMERGENCY_STOP)
    assert effective == PRIORITY_EMERGENCY_STOP


def test_bumper_immediately_revokes_all_leases():
    node = _FakeNode()
    node.mark_safety_ok()
    node._handle_acquire(_acquire_request(owner_id="a", resources=(HEAD,)), AcquireActuatorLease.Response())
    assert node._arbiter.active_leases()
    node.mark_safety_ok(bumper_active=True)
    assert node._arbiter.active_leases() == []
    assert node._last_abort_confirmed is True


def test_renew_and_release_roundtrip():
    node = _FakeNode()
    node.mark_safety_ok()
    acquire_resp = node._handle_acquire(_acquire_request(), AcquireActuatorLease.Response())
    renew_req = RenewActuatorLease.Request()
    renew_req.lease_id = acquire_resp.lease_id
    renew_req.ttl_s = 60.0
    renew_resp = node._handle_renew(renew_req, RenewActuatorLease.Response())
    assert renew_resp.success is True

    release_req = ReleaseActuatorLease.Request()
    release_req.lease_id = acquire_resp.lease_id
    release_resp = node._handle_release(release_req, ReleaseActuatorLease.Response())
    assert release_resp.success is True


def test_cancel_by_lease_id_revokes_lease():
    node = _FakeNode()
    node.mark_safety_ok()
    acquire_resp = node._handle_acquire(_acquire_request(goal_id="goal-1"), AcquireActuatorLease.Response())
    cancel_req = CancelActuation.Request()
    cancel_req.lease_id = acquire_resp.lease_id
    cancel_req.reason = "user_stop"
    cancel_resp = node._handle_cancel(cancel_req, CancelActuation.Response())
    assert cancel_resp.found is True
    assert node._arbiter.active_leases() == []


def test_cancel_by_goal_id_revokes_lease():
    node = _FakeNode()
    node.mark_safety_ok()
    node._handle_acquire(_acquire_request(goal_id="goal-42"), AcquireActuatorLease.Response())
    cancel_req = CancelActuation.Request()
    cancel_req.goal_id = "goal-42"
    cancel_resp = node._handle_cancel(cancel_req, CancelActuation.Response())
    assert cancel_resp.found is True


def test_cancel_unknown_lease_reports_not_found():
    node = _FakeNode()
    node.mark_safety_ok()
    cancel_req = CancelActuation.Request()
    cancel_req.lease_id = "does-not-exist"
    cancel_resp = node._handle_cancel(cancel_req, CancelActuation.Response())
    assert cancel_resp.found is False
    assert cancel_resp.already_inactive is True


def test_publish_state_reports_base_lease_valid():
    from ihk_pepper_interaction.actuator_arbiter import BASE
    node = _FakeNode()
    node.mark_safety_ok()
    node._handle_acquire(_acquire_request(resources=(BASE,)), AcquireActuatorLease.Response())
    assert node.base_lease_valid_pub.published[-1].data is True


def test_publish_state_base_lease_invalid_when_no_base_lease():
    node = _FakeNode()
    node.mark_safety_ok()
    node._publish_state()
    assert node.base_lease_valid_pub.published[-1].data is False
