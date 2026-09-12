"""
Tests fuer die Aktuator-Arbiter-Integration in bridge_node.py
(Entwicklungsauftrag 04-B, AP5B). Gleiches Duck-Typing-Muster wie
test_dialogue_thinking_loop.py: die ECHTEN, ungebundenen Methoden von
PepperBridgeNode laufen gegen ein leichtgewichtiges Fake -- kein
rclpy.init() noetig.
"""
import threading
import time

from std_msgs.msg import Bool, UInt8

from ihk_pepper_bridge.bridge_node import PepperBridgeNode
from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_bridge.gesture_cancellation import CancelSignal, GestureCancelReason
from ihk_pepper_bridge.gesture_execution_policy import GestureExecutionPolicy, PROFILE_OFFLINE_MOCK
from ihk_pepper_interfaces.action import PlayGesture, Say
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


class _FakeFuture:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self):
        return self._result


class _FakeArbiterClient:
    """Simuliert Acquire-, Release- UND Renew-Client (alle drei haben
    dieselbe minimale Schnittstelle: wait_for_service()/call_async())."""

    def __init__(self, available=True, granted=True, reason="", renew_succeeds=True):
        self.available = available
        self.granted = granted
        self.reason = reason
        self.renew_succeeds = renew_succeeds
        self.calls = []

    def wait_for_service(self, timeout_sec=None):
        return self.available

    def call_async(self, request):
        from ihk_pepper_interfaces.srv import RenewActuatorLease
        self.calls.append(request)
        if isinstance(request, AcquireActuatorLease.Request):
            response = AcquireActuatorLease.Response()
            response.granted = self.granted
            response.lease_id = "lease-1" if self.granted else ""
            response.reason = self.reason
            response.conflicting_owners = [] if self.granted else ["other-owner"]
            return _FakeFuture(response)
        if isinstance(request, RenewActuatorLease.Request):
            response = RenewActuatorLease.Response()
            response.success = self.renew_succeeds
            response.reason = "" if self.renew_succeeds else "simulierter Renew-Fehlschlag"
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


class _TestDoubleFakeCollisionProofBackend:
    """AUSDRUECKLICH ein TEST-DOUBLE, KEIN echtes Kollisions-Backend
    (Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 2.3/3.5): simuliert
    lediglich, dass ein SPAETERES, tatsaechlich funktionierendes
    Kollisions-Backend collision_checked=True liefern koennte, damit
    Tests den production-Freigabemechanismus selbst nachweisen koennen,
    OHNE einen echten JointAndTimingValidator-only-Report faelschlich als
    Kollisionsnachweis zu behaupten (das war der bestaetigte Fund 2.3 --
    ein reiner Joint-/Timing-Report lieferte 'pass' bei
    collision_checked=false und durfte trotzdem in production laufen).
    Wird NIE als reales Backend dokumentiert/benannt."""

    name = "test_double_fake_collision_proof_NOT_A_REAL_BACKEND"

    def check(self, gesture, plan, start_pose, compile_error):
        from ihk_pepper_bridge.trajectory_safety import TrajectorySafetyReport
        return TrajectorySafetyReport(
            gesture_name=gesture.name,
            verdict="pass",
            backend_names=[self.name],
            collision_checked=True,
            collision_backend_note=(
                "TEST-DOUBLE (_TestDoubleFakeCollisionProofBackend): simuliert ein "
                "ECHTES Kollisions-Backend fuer Testzwecke -- ist selbst KEINES."
            ),
            affected_joints=list(plan.joint_names) if plan is not None else [],
        )


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
    _on_safety_state_for_gestures = PepperBridgeNode._on_safety_state_for_gestures
    _on_mapping_active = PepperBridgeNode._on_mapping_active
    _on_interaction_state = PepperBridgeNode._on_interaction_state
    _on_lease_revoked = PepperBridgeNode._on_lease_revoked
    _on_authorized_command = PepperBridgeNode._on_authorized_command
    _current_runtime_context = PepperBridgeNode._current_runtime_context
    # Entwicklungsauftrag 04-B, AP8-R1: neue, seit diesem Auftrag
    # ebenfalls ECHTE (nicht ein zweites Mal nachgebaute) Methoden.
    _classify_safety_cancel_reason = PepperBridgeNode._classify_safety_cancel_reason
    _register_active_execution = PepperBridgeNode._register_active_execution
    _is_lease_revoked = PepperBridgeNode._is_lease_revoked
    _get_active_execution = PepperBridgeNode._get_active_execution
    _local_resource_conflict = PepperBridgeNode._local_resource_conflict
    _unregister_active_execution = PepperBridgeNode._unregister_active_execution
    _renew_lease = PepperBridgeNode._renew_lease
    _watchdog_check = PepperBridgeNode._watchdog_check
    _quarantine_unconfirmed_execution = PepperBridgeNode._quarantine_unconfirmed_execution
    shutdown_and_wait_for_terminal = PepperBridgeNode.shutdown_and_wait_for_terminal

    def __init__(self, gesture_dir, dry_run=True, arbiter_available=True, arbiter_granted=True,
                 say_fn=None, execution_profile=PROFILE_OFFLINE_MOCK,
                 safety_ok=None, pepper_reachable=None, nav2_moving=None, mapping_active=None,
                 play_trajectory_sleep_s=0.0):
        from ihk_pepper_bridge import safety_topics
        self._params = {
            "dry_run": dry_run, "execution_profile": execution_profile,
            "safety_state_max_age_s": 2.0, "nav2_moving_max_age_s": 2.0,
            "mapping_active_max_age_s": 2.0, "interaction_state_max_age_s": 2.0,
            "pepper_reachable_max_age_s": 12.0,
        }
        self.gesture_policy = GestureExecutionPolicy()
        # Entwicklungsauftrag 04-B, AP8-R1.8: None (Standard) laesst
        # GestureCatalog.play() ihre eigene Standard-
        # TrajectorySafetyValidator()-Instanz bauen -- ohne echtes
        # Kollisions-Backend also strukturell 'inconclusive'. Ein Test
        # kann hier explizit einen JointAndTimingValidator-only-Validator
        # injizieren, um ein 'pass'-Szenario zu simulieren.
        self.gesture_safety_validator = None
        self.catalog = GestureCatalog(gesture_dir)
        assert self.catalog.reload() == []
        self.pepper = _FakePepperClient(say_fn=say_fn, play_trajectory_sleep_s=play_trajectory_sleep_s)
        self.interrupt_channel = _FakeInterruptChannel()
        self.acquire_lease_client = _FakeArbiterClient(
            available=arbiter_available, granted=arbiter_granted,
            reason="" if arbiter_granted else "Ressourcenkonflikt mit: ['other-owner']",
        )
        self.release_lease_client = _FakeArbiterClient(available=arbiter_available)
        self.renew_lease_client = _FakeArbiterClient(available=arbiter_available)
        self._say_active = threading.Event()
        # Entwicklungsauftrag 04-B, AP8.2: dieselben Fresh*-Instanzen wie
        # der echte Node -- per Default UNBEFUELLT (is_fresh()==False),
        # damit ein Test, der einen konkreten Wert braucht, ihn explizit
        # setzt statt sich auf einen stillen Zufallsstand zu verlassen.
        self._nav2_moving = False
        self._nav2_moving_fresh = safety_topics.FreshBool(True)
        self._safety_ok_fresh = safety_topics.FreshBool(False)
        self._mapping_active_fresh = safety_topics.FreshBool(True)
        self._interaction_state_fresh = safety_topics.FreshValue(None)
        self._pepper_reachable_fresh = safety_topics.FreshBool(False)
        # Entwicklungsauftrag 04-B, AP8-R1.7: derselbe Lock wie im echten
        # Node -- _on_lease_revoked()/_register_active_execution() etc.
        # sind ECHTE, ungebundene Methoden (s.o.) und erwarten ihn.
        self._active_execution_lock = threading.Lock()
        self._active_gesture_cancel_events = {}
        self._revoked_lease_ids = set()
        self._quarantined_lease_ids = set()
        # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.1.
        self._active_executions = {}
        self._last_emergency_stop = None
        self._last_bumper_active = None
        self._shutting_down = False
        now = time.monotonic()  # _current_runtime_context() vergleicht gegen time.monotonic()
        if nav2_moving is not None:
            self._nav2_moving_fresh.update(nav2_moving, now)
        if safety_ok is not None:
            self._safety_ok_fresh.update(safety_ok, now)
        if mapping_active is not None:
            self._mapping_active_fresh.update(mapping_active, now)
        if pepper_reachable is not None:
            self._pepper_reachable_fresh.update(pepper_reachable, now)
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
    def __init__(self, say_fn=None, play_trajectory_sleep_s=0.0):
        self.say_text_only_calls = []
        self._say_fn = say_fn
        self._play_trajectory_sleep_s = play_trajectory_sleep_s
        self.play_trajectory_calls = []
        self.set_angle_calls = []

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

    def set_angle(self, joint, angle, duration=1.0):
        # Entwicklungsauftrag 04-B, AP8-R1.9: fuer v1-Gesten-Tests noetig
        # (GestureCatalog._play_v1() ruft dies pro Schritt auf).
        self.set_angle_calls.append((joint, angle, duration))

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        self.play_trajectory_calls.append((joint_names, angle_lists, time_lists))
        if self._play_trajectory_sleep_s:
            time.sleep(self._play_trajectory_sleep_s)


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

def test_gesture_execution_policy_rejects_a_draft_gesture_in_production(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R1 (bestaetigter Fund 3.9): greet_open.yaml
    # wurde in AP8 Commit 6/11 wegen einer Trajektorien-Migration korrekt
    # von dry_run_validated auf draft zurueckgestuft -- dieser Test
    # pruefte seitdem (unbemerkt) nur noch die Ablehnung eines DRAFT-
    # Status, obwohl sein Name/Kommentar weiterhin dry_run_validated
    # behauptete. Umbenannt + auf 'draft' praezisiert; die dry_run_validated-
    # Ablehnung wird jetzt in einem SEPARATEN Test mit einer explizit
    # dry_run_validated-Fixture geprueft (siehe unten).
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


def _dry_run_validated_gesture_dir(tmp_path):
    import yaml
    data = {
        "name": "explicitly_dry_run_validated",
        "schema_version": 2,
        "tested_status": "dry_run_validated",
        "tested_date": "2026-09-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"RShoulderPitch": 0.3}},
        ],
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "explicitly_dry_run_validated.yaml", "w") as f:
        yaml.safe_dump(data, f)
    return str(tmp_path)


def test_gesture_execution_policy_rejects_a_dry_run_validated_gesture_in_production(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R1, Abschnitt 13 ('Korrigierter
    # Policy-Test'): eigene, explizit dry_run_validated Fixture statt
    # einer Kataloggeste, deren Status sich mit der Zeit aendern kann --
    # 'draft' und 'dry_run_validated' werden damit GETRENNT gegen
    # production geprueft (siehe test_gesture_execution_policy_rejects_a_draft_gesture_in_production
    # oben).
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(
        _dry_run_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="explicitly_dry_run_validated"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "tested_status_unzureichend" in result.error_message
    assert goal_handle.outcome == "aborted"
    assert node.acquire_lease_client.calls == []
    assert [m.data for m in node.gesture_in_progress_pub.published] == []


def test_gesture_execution_policy_allows_a_dry_run_validated_gesture_in_supervised_hardware_test(tmp_path):
    # Gegenprobe: dieselbe dry_run_validated-Geste ist in
    # supervised_hardware_test (Mindestanforderung dry_run_validated)
    # sehr wohl zulaessig.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _dry_run_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="explicitly_dry_run_validated"))
    result = node._execute_gesture(goal_handle)
    assert result.success is True


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


def test_a_direct_action_call_cannot_bypass_speed_scale_rules_with_an_out_of_range_value(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R1.1/13: ein direkter Action-Aufruf
    # kann die Speed-Scale-Regeln ebenso wenig umgehen wie tested_status
    # -- ein Wert ausserhalb des zulaessigen Bereichs wird VOR jedem
    # Ressourcenzugriff abgelehnt, nicht stillschweigend geklemmt.
    node = _FakeNode(_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_OFFLINE_MOCK)
    goal_handle = _FakeGoalHandle(_gesture_request(name="greet_open", speed_scale=100.0))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "speed_scale_ausserhalb_bereich" in result.error_message
    assert node.acquire_lease_client.calls == []


# ---- Entwicklungsauftrag 04-B, AP8-R1.9: v1-Gesten in production sperren ----

def _v1_live_validated_gesture_dir(tmp_path):
    import yaml
    data = {
        "name": "t_pose_like",
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "steps": [{"joint": "RShoulderPitch", "angle": -1.0, "duration": 1.0}],
        # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.7: max_duration_s
        # muss fuer hardwarefaehige Profile gesetzt/endlich/positiv sein.
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "t_pose_like.yaml", "w") as f:
        yaml.safe_dump(data, f)
    return str(tmp_path)


def test_v1_gesture_is_rejected_in_production_regardless_of_tested_status(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R1.9 (bestaetigter Fund 3.6): solange
    # der v1-Pfad nicht dieselben Sicherheitsgarantien wie v2 besitzt
    # (kein echtes Mid-Flight-Cancel, kein Watchdog waehrend eines
    # einzelnen set_angle()-Aufrufs), wird schema_version==1 in production
    # STRUKTURELL abgelehnt -- SELBST bei tested_status=live_validated
    # (t_pose.yaml behaelt seinen historischen Status, dieser darf die
    # neue Laufzeitsperre aber nicht umgehen).
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(
        _v1_live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="t_pose_like"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == "legacy_v1_not_safely_interruptible"
    assert goal_handle.outcome == "aborted"
    # Keine Lease, kein Thread, keine Hardwareaktion.
    assert node.acquire_lease_client.calls == []


def test_v1_gesture_is_allowed_in_supervised_hardware_test(tmp_path):
    # Gegenprobe: die neue Sperre gilt NUR fuer production -- v1 bleibt in
    # supervised_hardware_test (mit menschlicher Aufsicht) nutzbar.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _v1_live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="t_pose_like"))
    result = node._execute_gesture(goal_handle)
    assert result.success is True


def _live_validated_gesture_dir(tmp_path):
    # schema_version 2 (wie greet_open.yaml oben) -- nutzt play_trajectory(),
    # nicht set_angle()/restore_joints() (die dieses Fake nicht bedient,
    # siehe _FakePepperClient).
    import yaml
    data = {
        "name": "live_wave",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"RShoulderPitch": 0.3}},
        ],
        # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.7: max_duration_s
        # muss fuer hardwarefaehige Profile gesetzt/endlich/positiv sein --
        # grosszuegig ueber der kompilierten Solldauer (0.3s), damit
        # Tests mit einer simulierten Transportverzoegerung
        # (play_trajectory_sleep_s) nicht faelschlich in TIMEOUT laufen,
        # sofern sie nicht GENAU das testen wollen.
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "live_wave.yaml", "w") as f:
        yaml.safe_dump(data, f)
    return str(tmp_path)


def test_production_profile_rejects_without_a_real_collision_proof(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R1.8 (bestaetigter Fund 3.7): OHNE ein
    # echtes Kollisions-Backend liefert der Standard-TrajectorySafetyValidator
    # strukturell 'inconclusive' -- production verweigert das, selbst mit
    # frischen, sicheren Laufzeitwerten und tested_status=live_validated.
    # Ersetzt den frueheren (vor AP8-R1) Test, der noch annahm, production
    # koenne ohne jeden Kollisionsnachweis erfolgreich laufen.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "inconclusive" in result.error_message


def test_production_profile_succeeds_once_a_real_collision_proof_backend_is_injected(tmp_path):
    # Gegenprobe: der Mechanismus selbst funktioniert -- sobald ein
    # Kollisions-Backend TATSAECHLICH collision_checked=True liefert
    # (hier durch _TestDoubleFakeCollisionProofBackend simuliert, siehe
    # dessen Docstring -- AUSDRUECKLICH kein reiner JointAndTimingValidator
    # mehr, das war der bestaetigte Fund 2.3: 'pass' allein reicht NICHT),
    # darf production tatsaechlich laufen. Injektion ueber
    # node.gesture_safety_validator (siehe PepperBridgeNode.__init__),
    # damit gesture_catalog.py/bridge_node.py fuer ein spaeteres echtes
    # Backend nicht geaendert werden muessen.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    from ihk_pepper_bridge.trajectory_safety import JointAndTimingValidator, TrajectorySafetyValidator
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    node.gesture_safety_validator = TrajectorySafetyValidator(
        backends=[JointAndTimingValidator(), _TestDoubleFakeCollisionProofBackend()])
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is True


def test_production_profile_rejects_when_safety_state_is_stale(tmp_path):
    # Ohne update() (siehe _FakeNode-Default) bleibt _safety_ok_fresh
    # "nie empfangen" -- entspricht einem veralteten/fehlenden SafetyState.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "safety_state_ungueltig_oder_unbekannt" in result.error_message


def test_a_genuinely_aged_out_safety_state_is_treated_as_stale(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    # SafetyState kam vor 10s an (max_age_s=2.0 im Fake-Default) -- gilt
    # als veraltet, obwohl der letzte WERT selbst "ok" war.
    node._safety_ok_fresh.update(True, time.monotonic() - 10.0)
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "safety_state_ungueltig_oder_unbekannt" in result.error_message


def test_on_safety_state_handler_treats_emergency_stop_as_not_ok(tmp_path):
    from ihk_pepper_interfaces.msg import SafetyState
    node = _FakeNode(_gesture_dir(tmp_path))
    node._on_safety_state_for_gestures(SafetyState(emergency_stop=True, bumper_active=False))
    ctx = node._current_runtime_context()
    assert ctx.safety_ok is False


def test_on_safety_state_handler_treats_bumper_active_as_not_ok(tmp_path):
    from ihk_pepper_interfaces.msg import SafetyState
    node = _FakeNode(_gesture_dir(tmp_path))
    node._on_safety_state_for_gestures(SafetyState(emergency_stop=False, bumper_active=True))
    ctx = node._current_runtime_context()
    assert ctx.safety_ok is False


def test_on_mapping_active_handler_updates_the_runtime_context(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    node._on_mapping_active(Bool(data=True))
    assert node._current_runtime_context().mapping_active is True
    node._on_mapping_active(Bool(data=False))
    assert node._current_runtime_context().mapping_active is False


def test_on_interaction_state_handler_decodes_the_enum_name(tmp_path):
    from ihk_pepper_interaction.interaction_state import InteractionState
    node = _FakeNode(_gesture_dir(tmp_path))
    node._on_interaction_state(UInt8(data=int(InteractionState.CONVERSATION_READY)))
    assert node._current_runtime_context().current_interaction_state == "CONVERSATION_READY"


def test_lease_revocation_during_a_running_gesture_aborts_it_and_is_not_success(tmp_path):
    # Entwicklungsauftrag 04-B, AP8.3: ein Lease-Widerruf muss das
    # EXAKT betroffene, gerade laufende Ziel abbrechen -- niemals als
    # Erfolg gemeldet werden, selbst wenn catalog.play() ohne Exception
    # zurueckkehrt.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    from ihk_pepper_bridge.trajectory_safety import JointAndTimingValidator, TrajectorySafetyValidator
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    # Entwicklungsauftrag 04-B, AP8-R1.8/AP8-R2 2.3: dieser Test prueft
    # Lease-Widerruf, nicht das Kollisions-Backend -- ein Test-Double mit
    # collision_checked=True wird injiziert, damit die Geste ueberhaupt
    # startet (production wuerde sonst schon vorher ablehnen, siehe
    # _TestDoubleFakeCollisionProofBackend-Docstring).
    node.gesture_safety_validator = TrajectorySafetyValidator(
        backends=[JointAndTimingValidator(), _TestDoubleFakeCollisionProofBackend()])
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _revoke_soon():
        # Wartet, bis die Lease tatsaechlich erworben und registriert ist.
        for _ in range(50):
            if node._active_gesture_cancel_events:
                break
            time.sleep(0.01)
        lease_id = next(iter(node._active_gesture_cancel_events))
        from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
        node._on_lease_revoked(ActuatorLeaseMsg(
            lease_id=lease_id, owner_id="pepper_bridge", goal_id="", preempted=True,
            preempted_reason="praemptiert durch 'motion_guard' (Prioritaet 1)",
        ))

    threading.Thread(target=_revoke_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    # Entwicklungsauftrag 04-B, AP8-R1.4: error_message traegt jetzt den
    # strukturierten GestureCancelReason-Code (statt eines freien
    # deutschen Strings).
    assert result.error_message == GestureCancelReason.LEASE_REVOKED
    assert goal_handle.outcome == "aborted"
    # Nach Abschluss der Geste ist die Lease-Registrierung wieder sauber.
    assert node._active_gesture_cancel_events == {}
    assert node._revoked_lease_ids == set()


def test_lease_revocation_for_a_different_owner_has_no_effect(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    node._active_gesture_cancel_events["some-lease"] = threading.Event()
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
    node._on_lease_revoked(ActuatorLeaseMsg(
        lease_id="some-lease", owner_id="run_dialogue_action_server", goal_id="", preempted=True,
        preempted_reason="irrelevant",
    ))
    assert node._active_gesture_cancel_events["some-lease"].is_set() is False
    assert "some-lease" not in node._revoked_lease_ids


def test_lease_revocation_is_idempotent_for_repeated_notifications(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R1.4: _active_gesture_cancel_events
    # enthaelt im echten Betrieb IMMER ein CancelSignal (nicht mehr ein
    # blosses threading.Event, siehe _execute_gesture()).
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    node._active_gesture_cancel_events["lease-x"] = signal
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
    msg = ActuatorLeaseMsg(
        lease_id="lease-x", owner_id="pepper_bridge", goal_id="", preempted=True,
        preempted_reason="doppelt",
    )
    node._on_lease_revoked(msg)
    node._on_lease_revoked(msg)
    assert signal.is_set() is True  # kein Fehler durch den zweiten Aufruf
    assert signal.reason == GestureCancelReason.LEASE_REVOKED


def test_an_old_revocation_does_not_affect_a_later_unrelated_goal(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
    node._on_lease_revoked(ActuatorLeaseMsg(
        lease_id="old-lease", owner_id="pepper_bridge", goal_id="", preempted=True,
        preempted_reason="alt",
    ))
    # Ein spaeteres, voellig unabhaengiges Ziel mit einer ANDEREN lease_id
    # ist davon nicht betroffen.
    new_event = threading.Event()
    node._active_gesture_cancel_events["new-lease"] = new_event
    assert new_event.is_set() is False
    assert "new-lease" not in node._revoked_lease_ids


def test_gesture_becoming_unsafe_between_first_and_second_check_is_rejected(tmp_path):
    # Entwicklungsauftrag 04-B, AP8.2: der Laufzeitkontext kann sich
    # zwischen der ersten Pruefung (vor Lease-Erwerb) und der zweiten
    # (unmittelbar vor Transportstart) aendern -- hier wird SafetyState
    # WAEHREND der Lease-Anforderung (simuliert durch einen praeparierten
    # Arbiter-Client) ungueltig.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_PRODUCTION
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )

    original_call_async = node.acquire_lease_client.call_async

    def _call_async_and_then_go_unsafe(request):
        result = original_call_async(request)
        node._safety_ok_fresh.update(False, time.monotonic())
        return result

    node.acquire_lease_client.call_async = _call_async_and_then_go_unsafe
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert "safety_state_ungueltig_oder_unbekannt" in result.error_message
    # Die soeben erworbene Lease wurde wieder freigegeben, nicht gehalten.
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1


# ---- Entwicklungsauftrag 04-B, AP8-R1.3: Laufzeit-Watchdog waehrend der Geste ----

def _wait_until_registered(node, timeout=2.0):
    """Wartet, bis _execute_gesture() die Lease tatsaechlich registriert
    hat (siehe _register_active_execution()), und liefert deren lease_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if node._active_gesture_cancel_events:
            return next(iter(node._active_gesture_cancel_events))
        time.sleep(0.01)
    raise TimeoutError("Gestenausfuehrung hat nie ein aktives CancelSignal registriert.")


def _head_gesture_dir(tmp_path):
    """Kopfgeste (HeadYaw) fuer den Mapping-Watchdog-Test -- live_wave
    (RShoulderPitch) zaehlt NICHT als Kopfgeste (gesture.affects_head())."""
    import yaml
    data = {
        "name": "live_head_move",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"HeadYaw": 0.2}},
        ],
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "live_head_move.yaml", "w") as f:
        yaml.safe_dump(data, f)
    return str(tmp_path)


def _interaction_restricted_gesture_dir(tmp_path):
    import yaml
    data = {
        "name": "live_conversation_only",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "allowed_interaction_states": ["CONVERSATION_READY"],
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"RShoulderPitch": 0.3}},
        ],
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "live_conversation_only.yaml", "w") as f:
        yaml.safe_dump(data, f)
    return str(tmp_path)


def test_watchdog_aborts_when_safety_becomes_invalid_during_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _go_unsafe_soon():
        _wait_until_registered(node)
        node._safety_ok_fresh.update(False, time.monotonic())

    threading.Thread(target=_go_unsafe_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.SAFETY_INVALID
    assert goal_handle.outcome == "aborted"


def test_watchdog_aborts_with_emergency_stop_reason_during_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    from ihk_pepper_interfaces.msg import SafetyState
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _emergency_stop_soon():
        _wait_until_registered(node)
        node._on_safety_state_for_gestures(SafetyState(emergency_stop=True, bumper_active=False))

    threading.Thread(target=_emergency_stop_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.EMERGENCY_STOP


def test_watchdog_aborts_with_bumper_reason_during_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    from ihk_pepper_interfaces.msg import SafetyState
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _bumper_soon():
        _wait_until_registered(node)
        node._on_safety_state_for_gestures(SafetyState(emergency_stop=False, bumper_active=True))

    threading.Thread(target=_bumper_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.BUMPER_ACTIVE


def test_watchdog_aborts_when_nav2_starts_moving_during_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _start_moving_soon():
        _wait_until_registered(node)
        node._nav2_moving_fresh.update(True, time.monotonic())

    threading.Thread(target=_start_moving_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.NAVIGATION_STARTED


def test_watchdog_aborts_when_mapping_starts_during_a_head_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _head_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_head_move"))

    def _start_mapping_soon():
        _wait_until_registered(node)
        node._mapping_active_fresh.update(True, time.monotonic())

    threading.Thread(target=_start_mapping_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.MAPPING_STARTED


def test_watchdog_aborts_when_interaction_state_becomes_invalid_during_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _interaction_restricted_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    node._interaction_state_fresh.update("CONVERSATION_READY", time.monotonic())
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_conversation_only"))

    def _change_state_soon():
        _wait_until_registered(node)
        node._interaction_state_fresh.update("IDLE", time.monotonic())

    threading.Thread(target=_change_state_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.INTERACTION_INVALID


def test_watchdog_aborts_when_pepper_becomes_unreachable_during_gesture(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _go_unreachable_soon():
        _wait_until_registered(node)
        node._pepper_reachable_fresh.update(False, time.monotonic())

    threading.Thread(target=_go_unreachable_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.PEPPER_UNREACHABLE


def _short_max_duration_gesture_dir(tmp_path):
    """max_duration_s deutlich kuerzer als eine simulierte
    Transportverzoegerung -- fuer den harten Bewegungsdeckel-Test
    (Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.7)."""
    import yaml
    data = {
        "name": "live_short_deadline",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.1, "joints": {"RShoulderPitch": 0.1}},
        ],
        "max_duration_s": 0.2,
    }
    with open(tmp_path / "live_short_deadline.yaml", "w") as f:
        yaml.safe_dump(data, f)
    return str(tmp_path)


def test_watchdog_aborts_on_hard_timeout_exceeding_max_duration_s(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.7 (bestaetigter Fund
    # 2.7): der harte Bewegungsdeckel ist jetzt EXAKT
    # transport_started_at + gesture.max_duration_s (0.2s hier) -- KEINE
    # zusaetzliche Marge mehr. Eine simulierte Transportverzoegerung
    # (0.5s, laenger als 0.2s, aber kuerzer als die Standard-Grace-Zeit
    # 2.0s) muss VOR ihrem natuerlichen Ende hart abgebrochen werden.
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _short_max_duration_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_short_deadline"))
    started = time.time()
    result = node._execute_gesture(goal_handle)
    elapsed = time.time() - started
    assert result.success is False
    assert result.error_message == GestureCancelReason.TIMEOUT
    # Wurde deutlich vor dem natuerlichen Ende (0.5s) erkannt -- der
    # Watchdog reagiert an der naechsten Poll-Grenze nach Ueberschreiten
    # von max_duration_s=0.2s.
    assert elapsed < 1.0


def test_no_success_and_no_lease_release_while_transport_thread_is_still_running(tmp_path, monkeypatch):
    # Entwicklungsauftrag 04-B, AP8-R1.6 (bestaetigter Fund 3.4): der
    # Hintergrund-Thread ignoriert die Cancel-Grace-Zeit (play_trajectory
    # kehrt erst NACH der Grace-Zeit zurueck) -- die Action darf NIE
    # Erfolg melden und die Lease NICHT sofort freigeben.
    from ihk_pepper_bridge import bridge_node as bridge_node_module
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    monkeypatch.setattr(bridge_node_module, "GESTURE_CANCEL_GRACE_S", 0.1)
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=1.0,  # laenger als die verkuerzte Grace-Zeit
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _cancel_soon():
        _wait_until_registered(node)
        goal_handle.is_cancel_requested = True

    threading.Thread(target=_cancel_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == "cancel_unconfirmed"
    assert goal_handle.outcome == "aborted"
    # Lease bleibt quarantaeniert -- NICHT sofort freigegeben.
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 0
    lease_id = next(iter(node._active_gesture_cancel_events))
    assert lease_id in node._quarantined_lease_ids
    # Nach dem tatsaechlichen (verspaeteten) Ende des Hintergrund-Threads
    # wird die Lease genau einmal bereinigt.
    for _ in range(200):
        if not node._active_gesture_cancel_events:
            break
        time.sleep(0.01)
    assert node._active_gesture_cancel_events == {}
    assert lease_id not in node._quarantined_lease_ids
    # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.1/3.3: derselbe
    # Nachweis gilt auch fuer den REICHHALTIGEREN Ausfuehrungsdatensatz --
    # exakt EIN Cleanup, keine haengengebliebene lokale Ressourcensperre.
    assert lease_id not in node._active_executions
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1


def test_second_goal_on_the_same_resource_is_blocked_while_first_is_quarantined(tmp_path, monkeypatch):
    from ihk_pepper_bridge import bridge_node as bridge_node_module
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    monkeypatch.setattr(bridge_node_module, "GESTURE_CANCEL_GRACE_S", 0.1)
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=1.0,
    )
    # Nur EINE Lease-ID wird vom Fake-Arbiter je vergeben ("lease-1") --
    # ein zweiter Erwerbsversuch auf dieselbe Ressource wird deshalb hier
    # ueber granted=False simuliert, SOBALD die erste Ausfuehrung noch
    # eine (quarantaenierte) Lease haelt.
    goal_handle_1 = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _cancel_first_soon():
        _wait_until_registered(node)
        goal_handle_1.is_cancel_requested = True

    threading.Thread(target=_cancel_first_soon, daemon=True).start()
    result_1 = node._execute_gesture(goal_handle_1)
    assert result_1.error_message == "cancel_unconfirmed"

    # Waehrend die erste Lease noch quarantaeniert ist (Hintergrund-Thread
    # laeuft noch), simuliert der Fake-Arbiter-Client einen Konflikt fuer
    # ein zweites Ziel auf derselben Ressource.
    assert node._quarantined_lease_ids  # noch nicht bereinigt
    node.acquire_lease_client.granted = False
    node.acquire_lease_client.reason = "Ressourcenkonflikt mit: ['pepper_bridge']"
    goal_handle_2 = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result_2 = node._execute_gesture(goal_handle_2)
    assert result_2.success is False
    assert "Ressourcenkonflikt" in result_2.error_message


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.3: lokale Ressourcenquarantaene ----

def test_local_resource_conflict_blocks_a_second_target_even_if_the_arbiter_would_grant_it(tmp_path):
    # Anders als der obige Test simuliert der Fake-Arbiter hier KEINEN
    # Konflikt (granted bleibt True) -- die LOKALE Ressourcenquarantaene
    # (_local_resource_conflict()) muss das zweite Ziel trotzdem
    # blockieren, BEVOR ueberhaupt eine zweite Acquire-Anfrage gestellt
    # wird (simuliert einen neu gestarteten/zurueckgesetzten Arbiter, der
    # die Ressource faelschlich fuer frei haelt).
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=1.0,
    )
    goal_handle_1 = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _cancel_first_soon():
        _wait_until_registered(node)
        goal_handle_1.is_cancel_requested = True

    import threading as _threading
    from ihk_pepper_bridge import bridge_node as bridge_node_module
    original_grace = bridge_node_module.GESTURE_CANCEL_GRACE_S
    bridge_node_module.GESTURE_CANCEL_GRACE_S = 0.1
    try:
        _threading.Thread(target=_cancel_first_soon, daemon=True).start()
        result_1 = node._execute_gesture(goal_handle_1)
        assert result_1.error_message == "cancel_unconfirmed"
        assert node._active_executions  # noch nicht bereinigt

        acquire_requests_before = len([r for r in node.acquire_lease_client.calls
                                       if isinstance(r, AcquireActuatorLease.Request)])
        goal_handle_2 = _FakeGoalHandle(_gesture_request(name="live_wave"))
        result_2 = node._execute_gesture(goal_handle_2)
        acquire_requests_after = len([r for r in node.acquire_lease_client.calls
                                      if isinstance(r, AcquireActuatorLease.Request)])
        assert result_2.success is False
        assert "lokal blockiert" in result_2.error_message
        # Die lokale Pruefung hat abgelehnt, BEVOR ueberhaupt eine zweite
        # Acquire-Anfrage an den (hier grosszuegigen) Arbiter ging.
        assert acquire_requests_after == acquire_requests_before
    finally:
        bridge_node_module.GESTURE_CANCEL_GRACE_S = original_grace


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.3: Lease-Erneuerung ----

def test_watchdog_renews_the_lease_when_half_the_ttl_has_elapsed(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.3/2.2: direkter,
    # deterministischer Test von _watchdog_check()s Erneuerungslogik --
    # ueber die volle _execute_gesture()-Zeitsteuerung waere die
    # Standard-TTL (mindestens 15s, Erneuerung erst bei 7.5s) zu langsam
    # fuer einen Unit-Test.
    from ihk_pepper_bridge.gesture_cancellation import ActiveGestureExecution, CancelSignal
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    gesture = node.catalog.get("live_wave")
    execution = ActiveGestureExecution(
        lease_id="lease-1", goal_id="goal-1", owner_id="pepper_bridge",
        resources={"RIGHT_ARM"}, gesture_name="live_wave", cancel_signal=CancelSignal(),
    )
    execution.transport_started_monotonic_s = time.monotonic()
    # Simuliert, dass die Haelfte der TTL (hier 10s) bereits verstrichen ist.
    execution.last_renewed_monotonic_s = time.monotonic() - 6.0
    node._active_executions["lease-1"] = execution

    node._watchdog_check(gesture, execution, PROFILE_SUPERVISED_HARDWARE_TEST, 1.0, lease_ttl_s=10.0)

    renew_requests = [r for r in node.renew_lease_client.calls if isinstance(r, RenewActuatorLease.Request)]
    assert len(renew_requests) == 1
    assert renew_requests[0].lease_id == "lease-1"
    assert execution.cancel_signal.is_set() is False  # Erneuerung erfolgreich -- kein Abbruch


def test_watchdog_does_not_renew_before_half_the_ttl_has_elapsed(tmp_path):
    from ihk_pepper_bridge.gesture_cancellation import ActiveGestureExecution, CancelSignal
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    gesture = node.catalog.get("live_wave")
    execution = ActiveGestureExecution(
        lease_id="lease-1", goal_id="goal-1", owner_id="pepper_bridge",
        resources={"RIGHT_ARM"}, gesture_name="live_wave", cancel_signal=CancelSignal(),
    )
    execution.transport_started_monotonic_s = time.monotonic()
    execution.last_renewed_monotonic_s = time.monotonic()  # gerade erst erneuert
    node._active_executions["lease-1"] = execution

    node._watchdog_check(gesture, execution, PROFILE_SUPERVISED_HARDWARE_TEST, 1.0, lease_ttl_s=10.0)

    assert node.renew_lease_client.calls == []


def test_failed_lease_renewal_sets_lease_revoked_reason(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.3 ('bei fehlgeschlagener
    # Erneuerung das Ziel abbrechen'): direkter _watchdog_check()-Test wie
    # oben -- ueber die volle Standard-TTL (>=15s) waere dies ueber
    # _execute_gesture() nicht in vertretbarer Testzeit auszuloesen.
    from ihk_pepper_bridge.gesture_cancellation import ActiveGestureExecution, CancelSignal
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    node.renew_lease_client.renew_succeeds = False
    gesture = node.catalog.get("live_wave")
    execution = ActiveGestureExecution(
        lease_id="lease-1", goal_id="goal-1", owner_id="pepper_bridge",
        resources={"RIGHT_ARM"}, gesture_name="live_wave", cancel_signal=CancelSignal(),
    )
    execution.transport_started_monotonic_s = time.monotonic()
    execution.last_renewed_monotonic_s = time.monotonic() - 6.0
    node._active_executions["lease-1"] = execution

    node._watchdog_check(gesture, execution, PROFILE_SUPERVISED_HARDWARE_TEST, 1.0, lease_ttl_s=10.0)

    assert execution.cancel_signal.is_set() is True
    assert execution.cancel_signal.reason == GestureCancelReason.LEASE_REVOKED
    # Die lokale Ressourcenquarantaene (der Ausfuehrungsdatensatz selbst)
    # bleibt unabhaengig vom fehlgeschlagenen Renew bestehen -- nur ein
    # expliziter Cleanup entfernt ihn.
    assert "lease-1" in node._active_executions


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.8: goal_id-Bindung von Revocations ----

def test_lease_revocation_with_a_different_goal_id_does_not_affect_the_active_target(tmp_path):
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    already_revoked = node._register_active_execution(
        "lease-1", signal, goal_id="goal-real", resources={"HEAD"}, gesture_name="wave")
    assert already_revoked is False

    node._on_lease_revoked(ActuatorLeaseMsg(
        lease_id="lease-1", owner_id="pepper_bridge", goal_id="goal-WRONG", preempted=True,
        preempted_reason="verwechselte/veraltete Nachricht",
    ))
    assert signal.is_set() is False
    assert "lease-1" not in node._revoked_lease_ids


def test_lease_revocation_with_the_matching_goal_id_does_affect_the_active_target(tmp_path):
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    node._register_active_execution(
        "lease-1", signal, goal_id="goal-real", resources={"HEAD"}, gesture_name="wave")

    node._on_lease_revoked(ActuatorLeaseMsg(
        lease_id="lease-1", owner_id="pepper_bridge", goal_id="goal-real", preempted=True,
        preempted_reason="korrekt zugeordnet",
    ))
    assert signal.is_set() is True
    assert signal.reason == GestureCancelReason.LEASE_REVOKED


def test_lease_revocation_without_any_goal_id_in_the_message_still_applies(tmp_path):
    # Rueckwaertskompatibilitaet: eine Revocation-Nachricht OHNE goal_id
    # (leerer String) bleibt rein lease_id-basiert wirksam.
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    node._register_active_execution(
        "lease-1", signal, goal_id="goal-real", resources={"HEAD"}, gesture_name="wave")

    node._on_lease_revoked(ActuatorLeaseMsg(
        lease_id="lease-1", owner_id="pepper_bridge", goal_id="", preempted=True,
        preempted_reason="keine goal_id mitgeliefert",
    ))
    assert signal.is_set() is True


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.8: ungebundenes Cancel -> PREEMPTED ----

def test_unbound_ros_cancel_sets_preempted_not_normal_user_cancel(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2 (bestaetigter Fund 2.8): ein
    # allgemeines ROS-Action-Cancel beweist NICHT, dass ein normaler
    # Benutzer abgebrochen hat -- gilt fail-closed als PREEMPTED, NICHT
    # mehr automatisch als NORMAL_USER_CANCEL (verbietet Restore auch bei
    # on_cancel='restore').
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    import yaml
    data = {
        "name": "live_wave_restore",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "on_cancel": "restore",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"RShoulderPitch": 0.3}},
        ],
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "live_wave_restore.yaml", "w") as f:
        yaml.safe_dump(data, f)
    node = _FakeNode(
        str(tmp_path), dry_run=False, execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave_restore"))

    def _cancel_soon():
        _wait_until_registered(node)
        goal_handle.is_cancel_requested = True

    threading.Thread(target=_cancel_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.PREEMPTED
    # ROS2-Konvention bleibt erhalten: ein tatsaechlich angefordertes
    # Action-Cancel wird weiterhin ueber canceled() gemeldet.
    assert goal_handle.outcome == "canceled"
    # KEIN Restore, obwohl on_cancel='restore' UND Safety frisch/gueltig
    # ist -- nur ein nachweislich GEBUNDENER NORMAL_USER_CANCEL duerfte
    # restaurieren, den es hier nicht gibt.
    assert len(node.pepper.play_trajectory_calls) == 1


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.10: Shutdown-Reihenfolge ----

def test_shutdown_during_a_running_gesture_sets_node_shutdown_and_waits_for_it_to_end(tmp_path):
    node = _FakeNode(
        _gesture_dir(tmp_path), dry_run=False,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.4,
    )
    goal_handle = _FakeGoalHandle(_gesture_request())
    result_box = {}

    def _run_gesture():
        result_box["result"] = node._execute_gesture(goal_handle)

    t = threading.Thread(target=_run_gesture, daemon=True)
    t.start()
    _wait_until_registered(node)
    started = time.time()
    still_pending = node.shutdown_and_wait_for_terminal(timeout_s=3.0)
    elapsed = time.time() - started
    t.join(timeout=3.0)
    # Kein noch offener Rest -- die Geste war laengst durch den Shutdown
    # abgebrochen und bestaetigt beendet, BEVOR die Frist ablief.
    assert still_pending == []
    assert elapsed < 3.0
    assert node.interrupt_channel.stop_motion_calls >= 1
    assert node._shutting_down is True
    assert result_box["result"].success is False
    assert result_box["result"].error_message == GestureCancelReason.NODE_SHUTDOWN
    # Der Ausfuehrungsdatensatz ist nach bestaetigtem Ende bereinigt --
    # KEINE dauerhaft haengende Quarantaene fuer eine tatsaechlich
    # beendete Ausfuehrung.
    assert "lease-1" not in node._active_executions


def test_shutdown_reports_an_unconfirmed_execution_as_quarantined_after_the_timeout(tmp_path):
    # Eine Ausfuehrung, deren Hintergrund-Thread die Shutdown-Frist
    # ueberschreitet, wird SICHTBAR als quarantaeniert gemeldet -- sie
    # bleibt in _active_executions (also lokal ressourcengesperrt), der
    # Node wird aber trotzdem abgebaut (main() faehrt danach fort).
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    node._register_active_execution(
        "lease-stuck", signal, goal_id="goal-stuck", resources={"HEAD"}, gesture_name="wave")
    still_pending = node.shutdown_and_wait_for_terminal(timeout_s=0.3)
    assert still_pending == ["lease-stuck"]
    assert signal.reason == GestureCancelReason.NODE_SHUTDOWN
    # Kein Reset/Entsperren -- der Datensatz bleibt bestehen, bis ein
    # spaeterer, tatsaechlicher Cleanup ihn entfernt.
    assert "lease-stuck" in node._active_executions


def test_shutdown_with_no_active_executions_does_not_call_interrupt(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    still_pending = node.shutdown_and_wait_for_terminal(timeout_s=1.0)
    assert still_pending == []
    assert node.interrupt_channel.stop_motion_calls == 0
    assert node._shutting_down is True


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.8: Codewort "Eisenbahn" -> CODEWORD_INTERRUPT ----

def _authorized_command(command="interrupt_and_look", authorization_status="not_required",
                        event_id="evt-1"):
    from ihk_pepper_interfaces.msg import InteractionCommand
    msg = InteractionCommand()
    msg.command = command
    msg.authorization_status = authorization_status
    msg.event_id = event_id
    return msg


def test_codeword_interrupt_preempts_a_running_gesture_and_never_restores(tmp_path):
    from ihk_pepper_bridge.gesture_execution_policy import PROFILE_SUPERVISED_HARDWARE_TEST
    import yaml
    data = {
        "name": "live_wave_restore",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "on_cancel": "restore",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"RShoulderPitch": 0.3}},
        ],
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "live_wave_restore.yaml", "w") as f:
        yaml.safe_dump(data, f)
    node = _FakeNode(
        str(tmp_path), dry_run=False, execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave_restore"))

    def _send_codeword_soon():
        _wait_until_registered(node)
        node._on_authorized_command(_authorized_command())

    threading.Thread(target=_send_codeword_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.CODEWORD_INTERRUPT
    # Kein ROS-Cancel wurde ueber die Action selbst angefordert -- die
    # Bridge bricht das Ziel EIGENSTAENDIG ab (goal_handle.abort(), nicht
    # canceled()).
    assert goal_handle.outcome == "aborted"
    assert node.interrupt_channel.stop_motion_calls >= 1
    # KEIN Restore, obwohl on_cancel='restore' -- CODEWORD_INTERRUPT ist
    # NIE ein restorefaehiger Grund (siehe restore_allowed()).
    assert len(node.pepper.play_trajectory_calls) == 1


def test_codeword_interrupt_ignored_when_authorization_is_denied_or_pending(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    node._register_active_execution(
        "lease-1", signal, goal_id="goal-1", resources={"HEAD"}, gesture_name="wave")

    node._on_authorized_command(_authorized_command(authorization_status="denied"))
    assert signal.is_set() is False
    node._on_authorized_command(_authorized_command(authorization_status="pending_confirmation"))
    assert signal.is_set() is False
    assert node.interrupt_channel.stop_motion_calls == 0


def test_codeword_interrupt_ignores_unrelated_commands(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    signal = CancelSignal()
    node._register_active_execution(
        "lease-1", signal, goal_id="goal-1", resources={"HEAD"}, gesture_name="wave")

    node._on_authorized_command(_authorized_command(command="stop"))
    assert signal.is_set() is False
    node._on_authorized_command(_authorized_command(command="dialogue_text"))
    assert signal.is_set() is False


def test_codeword_interrupt_with_no_active_gesture_does_not_call_interrupt(tmp_path):
    node = _FakeNode(_gesture_dir(tmp_path))
    node._on_authorized_command(_authorized_command())
    assert node.interrupt_channel.stop_motion_calls == 0
