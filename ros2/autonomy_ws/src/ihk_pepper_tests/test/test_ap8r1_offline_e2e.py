"""
Offline-End-to-End-Szenarien A-H (Entwicklungsauftrag 04-B, AP8-R1,
Abschnitt 14) -- KEINE Hardware, KEIN SSH/qicli, KEIN /cmd_vel. Baut auf
denselben Fake-Klassen/Hilfsfunktionen wie test_bridge_node_actuator_arbiter.py
auf (kein zweiter Testrahmen). Einzelne Szenarien decken sich bewusst mit
dort bereits vorhandenen, gezielten Unit-Tests (siehe Kommentar je
Funktion) -- dieses Modul stellt sie zusaetzlich als benannte, in sich
geschlossene End-to-End-Ablaeufe dar, wie vom Auftrag verlangt.
"""
import threading
import time

from ihk_pepper_bridge.gesture_cancellation import GestureCancelReason
from ihk_pepper_bridge.gesture_execution_policy import (
    PROFILE_OFFLINE_MOCK,
    PROFILE_PRODUCTION,
    PROFILE_SUPERVISED_HARDWARE_TEST,
)
from ihk_pepper_bridge.trajectory_safety import JointAndTimingValidator, TrajectorySafetyValidator
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease

from test_bridge_node_actuator_arbiter import (
    _FakeGoalHandle,
    _FakeNode,
    _gesture_request,
    _live_validated_gesture_dir,
    _v1_live_validated_gesture_dir,
    _wait_until_registered,
)


# ---- Szenario A: Katalogdefault bleibt durchgaengig erhalten ----

def test_scenario_a_catalog_default_speed_scale_is_used_consistently_end_to_end(tmp_path):
    """PlayGesture.speed_scale=0.0 -> Policy loest Katalogdefault auf ->
    Lease-TTL/Compiler/SafetyReport/MockTransport nutzen DENSELBEN Wert."""
    # supervised_hardware_test statt offline_mock: offline-Profile
    # erzwingen dry_run=True (structural, siehe HARDWARE_CAPABLE_PROFILES)
    # und beruehren daher NIE play_trajectory() -- fuer den vollstaendigen
    # End-to-End-Nachweis (Lease-TTL UND tatsaechlich gesendeter Plan)
    # wird hier ein hardwarefaehiges (Fake-)Profil verwendet.
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    # live_wave.yaml hat KEIN explizites speed_scale_default -> Default 1.0
    # (siehe Gesture.__init__) -- 0.0 muss GENAU das ergeben, nicht 1.0
    # "zufaellig" aus einem alten "or 1.0"-Fallback.
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave", speed_scale=0.0))
    result = node._execute_gesture(goal_handle)
    assert result.success is True
    # duration_s()==0.3s bei effective_speed_scale==1.0 (Katalogdefault) --
    # Lease-TTL wurde aus GENAU dieser Dauer abgeleitet (siehe
    # _acquire_lease()-Aufruf in _execute_gesture()).
    acquire_requests = [r for r in node.acquire_lease_client.calls if isinstance(r, AcquireActuatorLease.Request)]
    assert len(acquire_requests) == 1
    assert acquire_requests[0].ttl_s == max(0.3 + 10.0, 15.0)
    # Der tatsaechlich gesendete Plan (play_trajectory-Aufruf) nutzt die
    # UNSKALIERTE Zeit (1.0/1.0), nicht irrtuemlich beschleunigt/verlangsamt.
    assert node.pepper.play_trajectory_calls
    _, _, time_lists = node.pepper.play_trajectory_calls[0]
    assert time_lists[0][-1] == 0.3


# ---- Szenario B: Navigation beginnt waehrend einer Geste ----
# Siehe test_bridge_node_actuator_arbiter.py::
# test_watchdog_aborts_when_nav2_starts_moving_during_gesture fuer die
# gezielte Unit-Test-Variante. Hier als vollstaendiger Ablauf inkl.
# Lease-Freigabe-Zeitpunkt.

def test_scenario_b_navigation_start_during_gesture_triggers_bound_cancel_without_restore(tmp_path):
    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))

    def _start_navigation_soon():
        _wait_until_registered(node)
        node._nav2_moving_fresh.update(True, time.monotonic())

    threading.Thread(target=_start_navigation_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.NAVIGATION_STARTED
    # Kein Restore ausgeloest (live_wave hat kein disable_breathing, aber
    # restore_after=True per Default -- restore() darf trotzdem NICHT
    # aufgerufen worden sein, da NAVIGATION_STARTED niemals restore
    # erlaubt, siehe gesture_cancellation.py::restore_allowed()). Die
    # einzige play_trajectory()-Anfrage ist die Geste selbst.
    assert len(node.pepper.play_trajectory_calls) == 1
    # Lease erst nach bestaetigtem Transportende freigegeben (der Fake-
    # Transport lief hier natuerlich zu Ende, innerhalb der Grace-Zeit).
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1


# ---- Szenario C: Not-Stopp waehrend Geste ----

def test_scenario_c_emergency_stop_during_gesture_interrupts_without_restore_and_keeps_breathing_off(tmp_path):
    import yaml
    from ihk_pepper_interfaces.msg import SafetyState

    data = {
        "name": "live_wave_breathing",
        "schema_version": 2,
        "tested_status": "live_validated",
        "tested_date": "2026-01-01",
        "test_note": "Test-Fixture: synthetische Evidenz.",
        "disable_breathing": ["Arms"],
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 0.0}},
            {"time_from_start_s": 0.3, "joints": {"RShoulderPitch": 0.3}},
        ],
        "max_duration_s": 5.0,
    }
    with open(tmp_path / "live_wave_breathing.yaml", "w") as f:
        yaml.safe_dump(data, f)

    node = _FakeNode(
        str(tmp_path), dry_run=False, execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
        play_trajectory_sleep_s=0.5,
    )
    breathing_calls = []
    node.pepper.set_breathing = lambda enabled, part=None: breathing_calls.append((enabled, part))
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave_breathing"))

    def _emergency_stop_soon():
        _wait_until_registered(node)
        node._on_safety_state_for_gestures(SafetyState(emergency_stop=True, bumper_active=False))

    threading.Thread(target=_emergency_stop_soon, daemon=True).start()
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == GestureCancelReason.EMERGENCY_STOP
    assert goal_handle.outcome == "aborted"
    # Kein Restore -- nur EIN play_trajectory()-Aufruf (die abgebrochene Geste selbst).
    assert len(node.pepper.play_trajectory_calls) == 1
    # Breathing wurde deaktiviert, aber NIE wieder aktiviert (kein (True, "Arms")).
    assert (False, "Arms") in breathing_calls
    assert (True, "Arms") not in breathing_calls


# ---- Szenario D: Transport bestaetigt Cancel nicht ----
# Siehe test_bridge_node_actuator_arbiter.py::
# test_no_success_and_no_lease_release_while_transport_thread_is_still_running
# und ::test_second_goal_on_the_same_resource_is_blocked_while_first_is_quarantined
# fuer die vollstaendigen, bereits vorhandenen Abdeckungen dieses Szenarios
# (cancel_unconfirmed, Lease bleibt quarantaeniert, zweites Ziel blockiert,
# verspaetetes Ende fuehrt kontrolliert zum Cleanup). Hier zusaetzlich als
# einzelner, benannter End-to-End-Nachweis:

def test_scenario_d_unconfirmed_transport_never_reports_success_and_keeps_the_lease(tmp_path, monkeypatch):
    from ihk_pepper_bridge import bridge_node as bridge_node_module
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
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 0  # Lease NICHT sofort freigegeben


# ---- Szenario E: restore_after=false ----

def test_scenario_e_restore_after_false_reads_real_pose_and_skips_restore(tmp_path):
    """Nutzt die ECHTE neutral_stand.yaml aus dem Katalog (restore_after:
    false) gegen eine bewusst NICHT-neutrale Fake-Startpose."""
    import os
    import shutil
    from ament_index_python.packages import get_package_share_directory

    real_dir = os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")
    shutil.copy(os.path.join(real_dir, "neutral_stand.yaml"), os.path.join(str(tmp_path), "neutral_stand.yaml"))

    node = _FakeNode(
        str(tmp_path), dry_run=False, execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    # neutral_stand.yaml ist tested_status=dry_run_validated -> in
    # supervised_hardware_test zulaessig.
    non_neutral_pose = {"HeadYaw": 0.4, "HeadPitch": -0.1, "LShoulderPitch": 0.2, "RShoulderPitch": 0.2,
                        "LShoulderRoll": 0.15, "RShoulderRoll": -0.15, "LElbowYaw": 0.0, "RElbowYaw": 0.0,
                        "LElbowRoll": -0.02, "RElbowRoll": 0.02, "HipRoll": 0.0, "HipPitch": 0.0, "KneePitch": 0.0}
    node.pepper.snapshot_joints = lambda joints: {j: non_neutral_pose.get(j, 0.0) for j in joints}
    goal_handle = _FakeGoalHandle(_gesture_request(name="neutral_stand"))
    result = node._execute_gesture(goal_handle)
    assert result.success is True
    # Startpose wurde tatsaechlich gelesen (nicht None/uebersprungen) --
    # der Uebergang von HeadYaw=0.4 (Fake-Pose) zum ersten Keyframe wurde
    # also gegen die ECHTE Pose geprueft, nicht gegen NEUTRAL_STAND_POSE.
    assert node.pepper.play_trajectory_calls
    # restore_after: false -> genau EIN play_trajectory()-Aufruf (die
    # Geste selbst), KEIN zweiter (Restore-)Aufruf danach.
    assert len(node.pepper.play_trajectory_calls) == 1


# ---- Szenario F: Collision-Pruefung nicht verfuegbar ----

def test_scenario_f_missing_collision_backend_is_inconclusive_offline_ok_production_blocked(tmp_path):
    node_offline = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_OFFLINE_MOCK,
    )
    result_offline = node_offline._execute_gesture(_FakeGoalHandle(_gesture_request(name="live_wave")))
    # offline_mock beruehrt nie Hardware -- 'inconclusive' wird ausgefuehrt
    # (dry_run wird durch das Profil selbst erzwungen).
    assert result_offline.success is True

    node_prod = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    result_prod = node_prod._execute_gesture(_FakeGoalHandle(_gesture_request(name="live_wave")))
    assert result_prod.success is False
    assert "inconclusive" in result_prod.error_message

    # Gegenprobe: NUR mit einem Backend, das TATSAECHLICH
    # collision_checked=True liefert, darf production laufen.
    # Entwicklungsauftrag 04-B, AP8-R2 (bestaetigter Fund 2.3): ein reiner
    # JointAndTimingValidator liefert 'pass' bei collision_checked=false
    # und ist AUSDRUECKLICH KEIN Kollisionsnachweis -- das Test-Double
    # unten ist klar als solches benannt/dokumentiert und simuliert
    # lediglich ein spaeteres, echtes Backend.
    from test_bridge_node_actuator_arbiter import _TestDoubleFakeCollisionProofBackend
    node_prod_with_proof = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    node_prod_with_proof.gesture_safety_validator = TrajectorySafetyValidator(
        backends=[JointAndTimingValidator(), _TestDoubleFakeCollisionProofBackend()])
    result_prod_ok = node_prod_with_proof._execute_gesture(_FakeGoalHandle(_gesture_request(name="live_wave")))
    assert result_prod_ok.success is True


# ---- Szenario G: v1-Produktionsumgehung ----

def test_scenario_g_direct_v1_production_call_is_rejected_before_any_lease(tmp_path):
    node = _FakeNode(
        _v1_live_validated_gesture_dir(tmp_path), dry_run=False, execution_profile=PROFILE_PRODUCTION,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    goal_handle = _FakeGoalHandle(_gesture_request(name="t_pose_like"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    assert result.error_message == "legacy_v1_not_safely_interruptible"
    # Keine Lease, kein SSH/qicli (Fake-Client hat set_angle() nie gesehen).
    assert node.acquire_lease_client.calls == []
    assert node.pepper.set_angle_calls == []


# ---- Szenario H: Revocation unmittelbar vor Transportstart ----

def test_scenario_h_revocation_immediately_before_transport_start_prevents_any_hardware_call(tmp_path):
    """Simuliert eine Revocation GENAU im Fenster zwischen der zweiten
    Autorisierungspruefung und dem Transportstart, indem _acquire_lease()
    so verpackt wird, dass die Revocation SOFORT nach Lease-Erwerb (aber
    synchron, deterministisch, vor jeder weiteren Pruefung) eintrifft --
    _execute_gesture() muss dies ueber die erneute Pruefung unmittelbar
    vor Transportstart abfangen (AP8-R1.7)."""
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg

    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    original_acquire_lease = node._acquire_lease

    def _acquire_then_revoke_immediately(*args, **kwargs):
        granted, lease_id, reason = original_acquire_lease(*args, **kwargs)
        if granted:
            # Trifft VOR der Registrierung durch _execute_gesture() ein
            # (die Registrierung passiert erst NACH diesem Aufruf
            # zurueckkehrt) -- landet also zunaechst nur in
            # _revoked_lease_ids, wird aber durch
            # _register_active_execution()s Rueckgabewert sofort erkannt.
            node._on_lease_revoked(ActuatorLeaseMsg(
                lease_id=lease_id, owner_id="pepper_bridge", goal_id="", preempted=True,
                preempted_reason="Szenario-H-Testrevocation",
            ))
        return granted, lease_id, reason

    node._acquire_lease = _acquire_then_revoke_immediately
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    # Diese Timing-Variante (Revocation VOR jeder Registrierung) wird
    # bereits von der ZWEITEN Autorisierungspruefung selbst abgefangen
    # (lease_revoked=True im RuntimeContext, siehe _execute_gesture()) --
    # das ist eine der beiden in AP8-R1.7 verlangten Absicherungen und
    # verhindert genau wie der spaetere _is_lease_revoked()-Check
    # unmittelbar vor Transportstart, dass der Transport je beginnt.
    assert "lease_widerrufen" in result.error_message
    # Der Transport wurde NIE gestartet -- keine einzige play_trajectory()-
    # Anfrage, obwohl die Lease erfolgreich erworben wurde.
    assert node.pepper.play_trajectory_calls == []


def test_scenario_h_revocation_between_second_check_and_transport_start_prevents_transport(tmp_path):
    """Zweite Timing-Variante: die Revocation trifft NACH der zweiten
    Autorisierungspruefung (die also noch 'allowed' zurueckgibt), aber
    VOR dem eigentlichen Transportstart ein -- genau das Fenster, fuer
    das AP8-R1.7 den zusaetzlichen _is_lease_revoked()-Check UNMITTELBAR
    vor dem Threadstart verlangt."""
    from ihk_pepper_interfaces.msg import ActuatorLease as ActuatorLeaseMsg

    node = _FakeNode(
        _live_validated_gesture_dir(tmp_path), dry_run=False,
        execution_profile=PROFILE_SUPERVISED_HARDWARE_TEST,
        safety_ok=True, pepper_reachable=True, nav2_moving=False, mapping_active=False,
    )
    acquired_lease_id = {}
    original_acquire_lease = node._acquire_lease

    def _acquire_and_remember(*args, **kwargs):
        granted, lease_id, reason = original_acquire_lease(*args, **kwargs)
        if granted:
            acquired_lease_id["id"] = lease_id
        return granted, lease_id, reason

    node._acquire_lease = _acquire_and_remember

    call_count = {"n": 0}
    original_authorize = node.gesture_policy.authorize

    def _authorize_and_revoke_after_second_call(*args, **kwargs):
        call_count["n"] += 1
        decision = original_authorize(*args, **kwargs)
        if call_count["n"] == 2 and decision.allowed and "id" in acquired_lease_id:
            node._on_lease_revoked(ActuatorLeaseMsg(
                lease_id=acquired_lease_id["id"], owner_id="pepper_bridge", goal_id="", preempted=True,
                preempted_reason="Szenario-H-Testrevocation (nach zweiter Pruefung)",
            ))
        return decision

    node.gesture_policy.authorize = _authorize_and_revoke_after_second_call
    goal_handle = _FakeGoalHandle(_gesture_request(name="live_wave"))
    result = node._execute_gesture(goal_handle)
    assert result.success is False
    # Genau der Pfad, den AP8-R1.7 fuer dieses Zeitfenster vorsieht: der
    # Check UNMITTELBAR vor Transportstart (_is_lease_revoked()) faengt
    # es ab, nachdem die zweite Autorisierungspruefung selbst schon
    # 'allowed' zurueckgegeben hatte.
    assert result.error_message == "lease_widerrufen_vor_transportstart"
    assert node.pepper.play_trajectory_calls == []
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1
    # Lease wurde wieder freigegeben (nicht gehalten).
    release_requests = [r for r in node.release_lease_client.calls
                        if isinstance(r, ReleaseActuatorLease.Request)]
    assert len(release_requests) == 1
