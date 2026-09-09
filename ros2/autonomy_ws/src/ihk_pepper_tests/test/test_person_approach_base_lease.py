"""
Tests fuer die BASE-Lease-Integration in person_approach_node.py
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 14). Gleiches Duck-Typing-
Muster wie test_bridge_node_actuator_arbiter.py -- die ECHTEN,
ungebundenen Methoden von PersonApproachNode laufen gegen ein
leichtgewichtiges Fake, kein rclpy.init() und kein echtes Nav2 noetig.
"""
import threading
import time

import ihk_pepper_navigation.person_approach_node as person_approach_node
from ihk_pepper_navigation.person_approach_node import PersonApproachNode
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease, RenewActuatorLease


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
    def __init__(self, result=None, delay_s=0.0):
        self._result = result
        self._delay_s = delay_s
        self._done = delay_s <= 0.0

    def done(self):
        return self._done

    def add_done_callback(self, cb):
        if self._delay_s <= 0:
            self._done = True
            cb(self)
        else:
            def _later():
                time.sleep(self._delay_s)
                self._done = True
                cb(self)
            threading.Thread(target=_later, daemon=True).start()

    def result(self):
        return self._result


class _FakeLeaseClient:
    """Simuliert Acquire-/Renew-/Release-Client -- alle drei teilen
    dieselbe minimale Schnittstelle (wait_for_service()/call_async())."""

    def __init__(self, available=True, granted=True, renew_success=True, reason=""):
        self.available = available
        self.granted = granted
        self.renew_success = renew_success
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
            response.success = self.renew_success
            return _FakeFuture(response)
        assert isinstance(request, ReleaseActuatorLease.Request)
        self.release_calls.append(request)
        response = ReleaseActuatorLease.Response()
        response.success = True
        return _FakeFuture(response)


class _FakeGoalId:
    uuid = b"\x02" * 16


class _FakeActionGoalHandle:
    """Das ApproachPerson-Ziel, das _drive_to_pose() als goal_handle
    entgegennimmt (nur fuer _goal_id_str() verwendet)."""
    def __init__(self):
        self.goal_id = _FakeGoalId()


class _FakeNav2GoalHandle:
    def __init__(self, accepted=True, result_delay_s=0.0, nav2_status=4):
        self.accepted = accepted
        self.cancel_calls = 0
        self._result_delay_s = result_delay_s
        self._nav2_status = nav2_status

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        class _Result:
            pass
        r = _Result()
        r.status = self._nav2_status
        return _FakeFuture(r, delay_s=self._result_delay_s)


class _FakeNav2Client:
    def __init__(self, goal_handle, reachable=True):
        self.goal_handle = goal_handle
        self.reachable = reachable
        self.send_goal_calls = 0

    def wait_for_server(self, timeout_sec=None):
        return self.reachable

    def send_goal_async(self, goal):
        self.send_goal_calls += 1
        return _FakeFuture(self.goal_handle)


class _FakeNode:
    _goal_id_str = staticmethod(PersonApproachNode._goal_id_str)
    _acquire_base_lease = PersonApproachNode._acquire_base_lease
    _renew_base_lease = PersonApproachNode._renew_base_lease
    _release_base_lease = PersonApproachNode._release_base_lease
    _drive_to_pose = PersonApproachNode._drive_to_pose

    def __init__(self, nav2_client, lease_client, params=None):
        self._nav2_client = nav2_client
        self.acquire_lease_client = lease_client
        self.renew_lease_client = lease_client
        self.release_lease_client = lease_client
        self.nav2_moving_pub = _FakePublisher()
        self._params = params or {"nav2_connect_timeout_s": 2.0}

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


# ---- _acquire_base_lease/_renew_base_lease/_release_base_lease (isoliert) ----

def test_acquire_base_lease_returns_granted_and_lease_id():
    lease_client = _FakeLeaseClient(granted=True)
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    granted, lease_id, reason = node._acquire_base_lease(purpose="test", goal_id="g1")
    assert granted is True
    assert lease_id == "base-lease-1"
    assert len(lease_client.acquire_calls) == 1
    assert lease_client.acquire_calls[0].resources == [person_approach_node.BASE]
    assert lease_client.acquire_calls[0].priority == person_approach_node.PRIORITY_NAVIGATION
    assert lease_client.acquire_calls[0].owner_id == person_approach_node.OWNER_ID


def test_acquire_base_lease_fails_closed_when_arbiter_unreachable():
    lease_client = _FakeLeaseClient(available=False)
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    granted, lease_id, reason = node._acquire_base_lease(purpose="test", goal_id="g1")
    assert granted is False
    assert lease_id == ""
    assert "nicht erreichbar" in reason


def test_acquire_base_lease_returns_denied_reason_on_conflict():
    lease_client = _FakeLeaseClient(granted=False, reason="von anderem Owner gehalten")
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    granted, lease_id, reason = node._acquire_base_lease(purpose="test", goal_id="g1")
    assert granted is False
    assert reason == "von anderem Owner gehalten"


def test_renew_base_lease_returns_true_on_success():
    lease_client = _FakeLeaseClient()
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    assert node._renew_base_lease("base-lease-1") is True
    assert len(lease_client.renew_calls) == 1


def test_renew_base_lease_returns_false_when_arbiter_unreachable():
    lease_client = _FakeLeaseClient(available=False)
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    assert node._renew_base_lease("base-lease-1") is False


def test_renew_base_lease_is_a_noop_without_lease_id():
    lease_client = _FakeLeaseClient()
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    assert node._renew_base_lease("") is False
    assert len(lease_client.renew_calls) == 0


def test_release_base_lease_is_a_noop_without_lease_id():
    lease_client = _FakeLeaseClient()
    node = _FakeNode(nav2_client=None, lease_client=lease_client)
    node._release_base_lease("")
    assert len(lease_client.release_calls) == 0


# ---- _drive_to_pose(): vollstaendige Verdrahtung ----

def test_drive_to_pose_never_sends_nav2_goal_when_lease_denied():
    lease_client = _FakeLeaseClient(granted=False, reason="BASE von anderem Owner gehalten")
    nav2_client = _FakeNav2Client(goal_handle=_FakeNav2GoalHandle())
    node = _FakeNode(nav2_client, lease_client)

    ok, reason = node._drive_to_pose(_FakeActionGoalHandle(), pose_stamped=object(), feedback_cb=lambda *a: None)

    assert ok is False
    assert "actuator_arbiter_lease_denied" in reason
    assert nav2_client.send_goal_calls == 0  # KEIN Nav2-Ziel ohne Lease


def test_drive_to_pose_acquires_lease_before_sending_goal_and_releases_after_success():
    lease_client = _FakeLeaseClient(granted=True)
    goal_handle = _FakeNav2GoalHandle(accepted=True, nav2_status=4)  # STATUS_SUCCEEDED
    nav2_client = _FakeNav2Client(goal_handle)
    node = _FakeNode(nav2_client, lease_client)

    ok, reason = node._drive_to_pose(_FakeActionGoalHandle(), pose_stamped=object(), feedback_cb=lambda *a: None)

    assert ok is True
    assert nav2_client.send_goal_calls == 1
    assert len(lease_client.acquire_calls) == 1
    assert len(lease_client.release_calls) == 1  # immer freigegeben nach Abschluss


def test_drive_to_pose_releases_lease_even_when_nav2_rejects_goal():
    lease_client = _FakeLeaseClient(granted=True)
    goal_handle = _FakeNav2GoalHandle(accepted=False)
    nav2_client = _FakeNav2Client(goal_handle)
    node = _FakeNode(nav2_client, lease_client)

    ok, reason = node._drive_to_pose(_FakeActionGoalHandle(), pose_stamped=object(), feedback_cb=lambda *a: None)

    assert ok is False
    assert len(lease_client.release_calls) == 1


def test_drive_to_pose_renews_lease_during_a_longer_drive():
    # Erzwingt ein kurzes Renew-Intervall, damit der Test nicht real
    # 10 Sekunden warten muss.
    original_interval = person_approach_node.BASE_LEASE_RENEW_INTERVAL_S
    person_approach_node.BASE_LEASE_RENEW_INTERVAL_S = 0.05
    try:
        lease_client = _FakeLeaseClient(granted=True)
        # Der Renew-Check laeuft NUR, wenn ein Poll-Zyklus (0.5s, fest in
        # _drive_to_pose()) tatsaechlich per Timeout ausgelaufen ist --
        # das Ergebnis muss also NACH mindestens einem vollen Poll-
        # Intervall eintreffen, damit ueberhaupt ein Renew-Check
        # stattfindet (bei einem frueheren Ergebnis kehrt die Methode
        # schon aus dem ersten result_done.wait() zurueck).
        goal_handle = _FakeNav2GoalHandle(accepted=True, result_delay_s=1.1, nav2_status=4)
        nav2_client = _FakeNav2Client(goal_handle)
        node = _FakeNode(nav2_client, lease_client)

        ok, reason = node._drive_to_pose(
            _FakeActionGoalHandle(), pose_stamped=object(), feedback_cb=lambda *a: None)

        assert ok is True
        assert len(lease_client.renew_calls) >= 1
    finally:
        person_approach_node.BASE_LEASE_RENEW_INTERVAL_S = original_interval


def test_drive_to_pose_aborts_drive_when_lease_renewal_fails():
    original_interval = person_approach_node.BASE_LEASE_RENEW_INTERVAL_S
    person_approach_node.BASE_LEASE_RENEW_INTERVAL_S = 0.05
    try:
        lease_client = _FakeLeaseClient(granted=True, renew_success=False)
        goal_handle = _FakeNav2GoalHandle(accepted=True, result_delay_s=1.0, nav2_status=4)
        nav2_client = _FakeNav2Client(goal_handle)
        node = _FakeNode(nav2_client, lease_client)

        ok, reason = node._drive_to_pose(
            _FakeActionGoalHandle(), pose_stamped=object(), feedback_cb=lambda *a: None)

        assert ok is False
        assert reason == "base_lease_renew_failed"
        assert goal_handle.cancel_calls == 1  # Nav2-Ziel wird aktiv abgebrochen
        assert len(lease_client.release_calls) == 1
    finally:
        person_approach_node.BASE_LEASE_RENEW_INTERVAL_S = original_interval
