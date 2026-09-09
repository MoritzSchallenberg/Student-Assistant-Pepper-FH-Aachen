"""
Tests fuer die echte, autorisierte FollowPerson-Ausfuehrung in
person_approach_node.py (Entwicklungsauftrag 04-B, AP7, Abschnitt 19/20).
Gleiches Duck-Typing-Muster wie test_person_approach_base_lease.py -- die
ECHTEN, ungebundenen Methoden von PersonApproachNode laufen gegen ein
leichtgewichtiges Fake, kein rclpy.init() und kein echtes Nav2 noetig.

`rclpy.ok()` liefert ohne rclpy.init() False -- das wuerde die
`while rclpy.ok():`-Schleife in _execute_follow() nie betreten. Ein
autouse-Fixture patcht das reale rclpy-Modul fuer die Dauer jedes Tests
auf True und stellt es danach wieder her (gleiches Prinzip wie das
Patchen von BASE_LEASE_RENEW_INTERVAL_S im bestehenden Testfile).
"""
import time
import types

import pytest
import rclpy

import ihk_pepper_navigation.person_approach_node as person_approach_node
from ihk_pepper_navigation.person_approach_node import PersonApproachNode
from ihk_pepper_navigation.authorization_grant_cache import AuthorizationGrantCache
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease, RenewActuatorLease
from ihk_pepper_navigation.zone_config import Zone


@pytest.fixture(autouse=True)
def _patch_rclpy_ok():
    original = rclpy.ok
    rclpy.ok = lambda: True
    yield
    rclpy.ok = original


# ---- Fakes (angelehnt an test_person_approach_base_lease.py) ----

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
        assert isinstance(request, ReleaseActuatorLease.Request)
        self.release_calls.append(request)
        response = ReleaseActuatorLease.Response()
        response.success = True
        return _FakeFuture(response)


class _FakeNav2GoalHandle:
    """Ein einzelnes Nav2-Ziel -- liefert das Ergebnis SOFORT (kein
    Poll-Zyklus noetig), ausser replan_after_polls > 0 (siehe unten)."""

    def __init__(self, accepted=True, nav2_status=4, block_once=False):
        self.accepted = accepted
        self.nav2_status = nav2_status
        self.cancel_calls = 0
        self._block_once = block_once
        self._blocked = False

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        class _Result:
            pass
        r = _Result()
        r.status = self.nav2_status

        if self._block_once and not self._blocked:
            # Simuliert eine laufende Fahrt: das Ergebnis wird erst NACH
            # mindestens einem monitor_fn()-Poll-Zyklus fertig (0.5s Poll-
            # Intervall in _drive_to_pose(), fest verdrahtet).
            self._blocked = True

            class _DelayedFuture:
                def __init__(self):
                    self._t0 = time.time()

                def done(self):
                    return time.time() - self._t0 >= 0.6

                def add_done_callback(self, cb):
                    def _later():
                        while time.time() - self._t0 < 0.6:
                            time.sleep(0.01)
                        cb(self)
                    import threading
                    threading.Thread(target=_later, daemon=True).start()

                def result(self):
                    return r
            return _DelayedFuture()
        return _FakeFuture(r)


class _FakeNav2Client:
    def __init__(self, reachable=True, nav2_status=4, block_once=False):
        self.reachable = reachable
        self.nav2_status = nav2_status
        self.block_once = block_once
        self.send_goal_calls = 0
        self.sent_poses = []
        self.goal_handles = []

    def wait_for_server(self, timeout_sec=None):
        return self.reachable

    def send_goal_async(self, goal):
        self.send_goal_calls += 1
        self.sent_poses.append(goal.pose)
        gh = _FakeNav2GoalHandle(accepted=True, nav2_status=self.nav2_status,
                                  block_once=self.block_once)
        self.goal_handles.append(gh)
        return _FakeFuture(gh)


class _FakeGoalId:
    uuid = b"\x03" * 16


def _make_request(track_id=1, grant_id="g1", max_duration_s=60.0,
                   max_track_loss_timeout_s=2.0, desired_follow_distance_m=0.0):
    return types.SimpleNamespace(
        track_id=track_id,
        min_distance_m=0.0,
        authorization_grant_id=grant_id,
        session_id="",
        desired_follow_distance_m=desired_follow_distance_m,
        max_duration_s=max_duration_s,
        max_track_loss_timeout_s=max_track_loss_timeout_s,
        return_to_origin_after_end=False,
    )


class _FakeGoalHandle:
    def __init__(self, request):
        self.request = request
        self.goal_id = _FakeGoalId()
        self.is_cancel_requested = False
        self.feedbacks = []
        self.aborted = False
        self.cancelled = False
        self.succeeded = False

    def publish_feedback(self, fb):
        self.feedbacks.append(fb)

    def abort(self):
        self.aborted = True

    def canceled(self):
        self.cancelled = True

    def succeed(self):
        self.succeeded = True


def _safe_state(**overrides):
    defaults = dict(
        allow_motion=True, allow_person_approach=True, localization_valid=True,
        obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, bumper_active=False, emergency_stop=False,
        reason="",
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _track(track_id=1, x=3.0, y=0.0, confidence=0.9, frame_id="base_link"):
    return types.SimpleNamespace(
        track_id=track_id, confidence=confidence, has_3d_position=True,
        position_3d=types.SimpleNamespace(x=x, y=y), frame_id=frame_id,
        last_seen=0,
    )


_DEFAULT_PARAMS = {
    "nav2_connect_timeout_s": 2.0,
    "min_confidence": 0.5,
    "robot_base_frame": "base_link",
    "tf_lookup_timeout_s": 0.5,
    "follow_person_target_distance_m": 1.2,
    "follow_person_minimum_distance_m": 0.8,
    "follow_person_maximum_distance_m": 4.0,
    # Hoch gesetzt, damit "reached"-Wartezeiten den Test nicht verlangsamen.
    "follow_person_goal_update_rate_hz": 1000.0,
    "follow_person_minimum_goal_shift_m": 0.25,
    "follow_person_minimum_goal_yaw_change_rad": 0.20,
    "follow_person_loss_timeout_s": 2.0,
    "follow_person_maximum_duration_s": 300.0,
    "follow_person_allow_in_crowds": False,
    "follow_person_crowd_proximity_m": 1.0,
    "follow_person_minimum_battery_percent": 20.0,
}


class _FakeNode:
    _goal_id_str = staticmethod(PersonApproachNode._goal_id_str)
    _acquire_base_lease = PersonApproachNode._acquire_base_lease
    _renew_base_lease = PersonApproachNode._renew_base_lease
    _release_base_lease = PersonApproachNode._release_base_lease
    _drive_to_pose = PersonApproachNode._drive_to_pose
    _validate_target = PersonApproachNode._validate_target
    _get_robot_position_in_frame = PersonApproachNode._get_robot_position_in_frame
    _build_follow_safety_context = PersonApproachNode._build_follow_safety_context
    _execute_follow = PersonApproachNode._execute_follow

    def __init__(self, nav2_client=None, lease_client=None, params=None,
                 tracks=None, safety_state=None, latest_health=None, zones=None):
        self._nav2_client = nav2_client or _FakeNav2Client()
        lease_client = lease_client or _FakeLeaseClient()
        self.acquire_lease_client = lease_client
        self.renew_lease_client = lease_client
        self.release_lease_client = lease_client
        self.nav2_moving_pub = _FakePublisher()
        self._params = dict(_DEFAULT_PARAMS)
        if params:
            self._params.update(params)
        self._tracks = tracks if tracks is not None else {1: (_track(), time.time())}
        self._safety_state = safety_state if safety_state is not None else _safe_state()
        self._latest_health = latest_health
        self.zones = zones if zones is not None else {}
        self._grant_cache = AuthorizationGrantCache()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


def _grant(node, grant_id="g1", track_id=1, expires_in_s=60.0):
    node._grant_cache.add(grant_id, "p1", track_id, "follow_speaker", time.time() + expires_in_s)


# ---- Autorisierung ----

def test_missing_grant_denies_follow_person():
    node = _FakeNode()
    gh = _FakeGoalHandle(_make_request(grant_id=""))
    result = node._execute_follow(gh)
    assert result.success is False
    assert result.abort_reason == "authorization_denied:keine_grant_id"
    assert gh.aborted is True
    assert node._nav2_client.send_goal_calls == 0


def test_grant_for_wrong_track_denies_follow_person():
    node = _FakeNode()
    _grant(node, track_id=99)
    gh = _FakeGoalHandle(_make_request(track_id=1))
    result = node._execute_follow(gh)
    assert result.success is False
    assert result.abort_reason == "authorization_denied:grant_falscher_track"


def test_expired_grant_denies_follow_person():
    node = _FakeNode()
    _grant(node, expires_in_s=-1.0)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "authorization_denied:grant_abgelaufen"


# ---- Sicherheitsbedingungen (Abschnitt 20) ----

def test_emergency_stop_aborts_follow_person():
    node = _FakeNode(safety_state=_safe_state(emergency_stop=True))
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "safety_abort:not_stopp_aktiv"
    assert node._nav2_client.send_goal_calls == 0


def test_allow_person_approach_false_aborts_follow_person():
    node = _FakeNode(safety_state=_safe_state(allow_person_approach=False))
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "safety_abort:allow_person_approach_false"


def test_low_battery_aborts_follow_person():
    node = _FakeNode(latest_health=types.SimpleNamespace(battery_percent=5.0))
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "safety_abort:akku_niedrig"


def test_crowd_ambiguous_aborts_follow_person():
    tracks = {
        1: (_track(track_id=1, x=3.0, y=0.0), time.time()),
        2: (_track(track_id=2, x=3.2, y=0.0), time.time()),  # 0.2m entfernt < crowd_proximity_m
    }
    node = _FakeNode(tracks=tracks)
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "safety_abort:menschenmenge_mehrdeutig"


def test_person_in_keepout_zone_aborts_follow_person():
    zone = Zone(id="verboten", type="keepout",
                polygon=[(2.0, -1.0), (4.0, -1.0), (4.0, 1.0), (2.0, 1.0)])
    node = _FakeNode(zones={"verboten": zone})
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "safety_abort:ziel_in_keepout_zone"


# ---- Track-/Zeitbedingungen ----

def test_track_loss_aborts_follow_person():
    node = _FakeNode(tracks={})
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "person_lost"


def test_cancel_request_cancels_follow_person():
    node = _FakeNode()
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    gh.is_cancel_requested = True
    result = node._execute_follow(gh)
    assert result.success is False
    assert result.abort_reason == "cancelled"
    assert gh.cancelled is True
    assert node._nav2_client.send_goal_calls == 0


def test_maximum_duration_exceeded_aborts_follow_person():
    node = _FakeNode()
    _grant(node)
    gh = _FakeGoalHandle(_make_request(max_duration_s=-1.0))  # sofort ueberschritten
    result = node._execute_follow(gh)
    assert result.abort_reason == "maximum_follow_duration_exceeded"
    assert node._nav2_client.send_goal_calls == 0


# ---- Nav2-Anbindung ----

def test_nav2_unreachable_aborts_follow_person():
    node = _FakeNode(nav2_client=_FakeNav2Client(reachable=False))
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert result.abort_reason == "nav2_nicht_erreichbar"


def test_base_lease_denied_aborts_follow_person():
    node = _FakeNode(lease_client=_FakeLeaseClient(granted=False, reason="von anderem Owner gehalten"))
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    result = node._execute_follow(gh)
    assert "actuator_arbiter_lease_denied" in result.abort_reason
    assert node._nav2_client.send_goal_calls == 0


def test_successful_follow_drives_to_an_approach_pose_not_the_raw_person_position():
    # Person 3m entfernt, gewuenschter Gespraechsabstand 1.2m --
    # das gesendete Nav2-Ziel darf NICHT bei (3.0, 0.0) liegen (Auftrag:
    # niemals direkt auf die Person zufahren). Das Fake haelt die
    # Roboterposition konstant, daher wird nach jedem abgeschlossenen
    # Fahrsegment sofort ein weiteres gesendet (in echt waere der
    # Roboter dann bereits am Ziel) -- ein kurzes Zeitlimit sorgt fuer
    # einen deterministischen, schnellen Testabschluss.
    node = _FakeNode(tracks={1: (_track(x=3.0, y=0.0), time.time())})
    _grant(node)
    gh = _FakeGoalHandle(_make_request(max_duration_s=0.05))
    result = node._execute_follow(gh)
    assert node._nav2_client.send_goal_calls >= 1
    sent_pose = node._nav2_client.sent_poses[0]
    assert abs(sent_pose.pose.position.x - 3.0) > 0.5  # deutlich vor der Person
    assert abs(sent_pose.pose.position.x - 1.8) < 1e-6  # 3.0 - 1.2 Zieldistanz


def test_base_lease_is_released_after_each_drive_segment():
    node = _FakeNode(tracks={})  # sofortiger Trackverlust nach EINER Sicherheitspruefung
    _grant(node)
    gh = _FakeGoalHandle(_make_request())
    node._execute_follow(gh)
    # Kein Fahrsegment wurde ueberhaupt gestartet (Trackverlust VOR
    # _drive_to_pose) -- damit auch keine Lease angefragt.
    assert len(node.acquire_lease_client.acquire_calls) == 0


def test_person_barely_moving_does_not_cancel_the_active_drive():
    # Bewusst NICHT ueber die Gesamtzahl gesendeter Nav2-Ziele geprueft --
    # das Fake haelt die Roboterposition konstant (_get_robot_position_
    # in_frame() liefert im base_link-Kurzschluss immer (0,0)), daher
    # sendet die aeussere Schleife nach JEDEM abgeschlossenen Fahrsegment
    # zwangslaeufig ein weiteres (in echt waere der Roboter dann bereits
    # am Ziel). Die eigentliche Aussage "keine unnoetige Neuplanung bei
    # winziger Bewegung" wird direkt am ERSTEN Fahrsegment geprueft: es
    # darf WAEHREND der Fahrt nicht abgebrochen worden sein.
    tracks = {1: (_track(x=3.0, y=0.0), time.time())}
    nav2_client = _FakeNav2Client(block_once=True)
    node = _FakeNode(nav2_client=nav2_client, tracks=tracks)
    _grant(node)
    # Kurzes Zeitlimit -- der Testlauf endet deterministisch durch
    # Zeitueberschreitung, statt auf eine bestimmte Anzahl Iterationen zu
    # vertrauen.
    gh = _FakeGoalHandle(_make_request(max_duration_s=1.3))

    def _tiny_move():
        time.sleep(0.2)
        node._tracks[1] = (_track(x=3.0, y=0.05), time.time())  # weit unter der Schwelle

    import threading
    mover = threading.Thread(target=_tiny_move, daemon=True)
    mover.start()
    result = node._execute_follow(gh)
    mover.join()

    assert nav2_client.goal_handles[0].cancel_calls == 0
    assert result.abort_reason == "maximum_follow_duration_exceeded"


def test_person_moving_significantly_triggers_replanning_not_an_abort():
    tracks = {1: (_track(x=3.0, y=0.0), time.time())}
    nav2_client = _FakeNav2Client(block_once=True)
    node = _FakeNode(nav2_client=nav2_client, tracks=tracks)
    _grant(node)
    gh = _FakeGoalHandle(_make_request(max_duration_s=1.3))

    def _big_move():
        time.sleep(0.2)
        node._tracks[1] = (_track(x=3.0, y=1.0), time.time())  # deutlich ueber der Schwelle

    import threading
    mover = threading.Thread(target=_big_move, daemon=True)
    mover.start()
    result = node._execute_follow(gh)
    mover.join()

    # Der erste Fahrauftrag wurde per monitor_abort:replan_needed
    # abgebrochen (kein echter Fehlerabbruch) -- ein ZWEITES Ziel mit der
    # neuen Personenposition wurde gesendet.
    assert nav2_client.goal_handles[0].cancel_calls >= 1
    assert nav2_client.send_goal_calls >= 2
