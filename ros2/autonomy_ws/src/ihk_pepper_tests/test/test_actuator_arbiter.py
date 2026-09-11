"""
Tests fuer die reine Aktuator-Arbiter-Kernlogik (Entwicklungsauftrag
04-B, AP5B). Kein ROS -- reine Python-Zustandsautomat-Tests mit einer
steuerbaren Fake-Uhr (monotone Zeitbasis, injizierbar).
"""
import pytest

from ihk_pepper_interaction.actuator_arbiter import (
    BASE,
    HEAD,
    LEFT_ARM,
    LEDS,
    PRIORITY_ATTRACT,
    PRIORITY_DIALOGUE,
    PRIORITY_EMERGENCY_STOP,
    PRIORITY_NAVIGATION,
    PRIORITY_PRESENTATION,
    RIGHT_ARM,
    SPEECH,
    TABLET,
    TORSO,
    ActuatorArbiter,
)


class _FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture()
def clock():
    return _FakeClock()


@pytest.fixture()
def arbiter(clock):
    return ActuatorArbiter(now_fn=clock)


# ---- Grundfunktionen ----

def test_single_lease_is_granted(arbiter):
    result = arbiter.acquire("dialog", {SPEECH}, "say", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is True
    assert result.lease.resources == frozenset({SPEECH})


def test_atomic_multi_resource_acquire_all_or_nothing(arbiter):
    # HEAD ist frei, LEFT_ARM ist belegt -> die GESAMTE Anfrage muss
    # scheitern, HEAD darf NICHT teilweise gewaehrt werden.
    arbiter.acquire("gesture-a", {LEFT_ARM}, "wave", PRIORITY_DIALOGUE, safety_ok=True)
    result = arbiter.acquire("gesture-b", {HEAD, LEFT_ARM}, "combo", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is False
    assert arbiter.is_locked(HEAD) is False  # kein Teil-Erfolg


def test_conflicting_resource_is_rejected(arbiter):
    arbiter.acquire("a", {HEAD}, "nod", PRIORITY_DIALOGUE, safety_ok=True)
    result = arbiter.acquire("b", {HEAD}, "shake", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is False
    assert "a" in result.conflicting_owners


def test_same_resource_never_double_granted(arbiter):
    arbiter.acquire("a", {LEFT_ARM}, "x", PRIORITY_DIALOGUE, safety_ok=True)
    result = arbiter.acquire("b", {LEFT_ARM}, "y", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is False
    active = arbiter.active_leases()
    assert len(active) == 1


def test_non_overlapping_resources_run_in_parallel(arbiter):
    r1 = arbiter.acquire("dialog", {SPEECH}, "say", PRIORITY_DIALOGUE, safety_ok=True)
    r2 = arbiter.acquire("gesture", {LEFT_ARM}, "wave", PRIORITY_DIALOGUE, safety_ok=True)
    assert r1.granted is True
    assert r2.granted is True


def test_speech_and_right_arm_parallel_but_not_two_head_actions(arbiter):
    assert arbiter.acquire("d", {SPEECH}, "say", PRIORITY_DIALOGUE, safety_ok=True).granted
    assert arbiter.acquire("g", {RIGHT_ARM}, "wave", PRIORITY_DIALOGUE, safety_ok=True).granted
    assert arbiter.acquire("h1", {HEAD}, "nod", PRIORITY_DIALOGUE, safety_ok=True).granted
    assert not arbiter.acquire("h2", {HEAD}, "shake", PRIORITY_DIALOGUE, safety_ok=True).granted


def test_leds_and_tablet_are_never_exclusive(arbiter):
    assert arbiter.acquire("a", {LEDS}, "x", PRIORITY_DIALOGUE, safety_ok=True).granted
    assert arbiter.acquire("b", {LEDS}, "y", PRIORITY_DIALOGUE, safety_ok=True).granted
    assert arbiter.acquire("c", {TABLET}, "z", PRIORITY_DIALOGUE, safety_ok=True).granted


def test_torso_and_base_are_mutually_exclusive_even_without_direct_overlap(arbiter):
    assert arbiter.acquire("nav", {BASE}, "drive", PRIORITY_NAVIGATION, safety_ok=True).granted
    # TORSO ueberschneidet sich nicht direkt mit BASE, ist aber laut
    # Abschnitt 8 trotzdem verboten (Kippgefahr).
    result = arbiter.acquire("g", {TORSO}, "bow", PRIORITY_NAVIGATION, safety_ok=True)
    assert result.granted is False


def test_unknown_resource_rejected():
    arbiter = ActuatorArbiter(now_fn=lambda: 0.0)
    result = arbiter.acquire("a", {"WHEELS"}, "x", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is False


def test_empty_resource_set_rejected(arbiter):
    result = arbiter.acquire("a", set(), "x", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is False


# ---- Ablauf/Renew/Release ----

def test_lease_expires_after_ttl(arbiter, clock):
    arbiter.acquire("a", {HEAD}, "x", PRIORITY_DIALOGUE, safety_ok=True, ttl_s=5.0)
    assert arbiter.is_locked(HEAD) is True
    clock.advance(5.1)
    assert arbiter.is_locked(HEAD) is False


def test_renew_extends_ttl(arbiter, clock):
    result = arbiter.acquire("a", {HEAD}, "x", PRIORITY_DIALOGUE, safety_ok=True, ttl_s=2.0)
    clock.advance(1.5)
    assert arbiter.renew(result.lease.lease_id, ttl_s=5.0) is True
    clock.advance(3.0)  # insgesamt 4.5s seit Erwerb, aber nur 3.0s seit renew()
    assert arbiter.is_locked(HEAD) is True


def test_renew_unknown_lease_returns_false_not_an_exception(arbiter):
    assert arbiter.renew("does-not-exist") is False


def test_release_frees_the_resource(arbiter):
    result = arbiter.acquire("a", {HEAD}, "x", PRIORITY_DIALOGUE, safety_ok=True)
    assert arbiter.release(result.lease.lease_id) is True
    assert arbiter.is_locked(HEAD) is False


def test_double_release_is_idempotent(arbiter):
    result = arbiter.acquire("a", {HEAD}, "x", PRIORITY_DIALOGUE, safety_ok=True)
    assert arbiter.release(result.lease.lease_id) is True
    assert arbiter.release(result.lease.lease_id) is False  # kein Fehler, nur False


def test_release_unknown_lease_is_idempotent_not_an_exception(arbiter):
    assert arbiter.release("never-existed") is False


# ---- Prioritaet/Praemption ----

def test_higher_priority_preempts_lower_priority(arbiter):
    low = arbiter.acquire("attract", {HEAD}, "idle_look", PRIORITY_ATTRACT, safety_ok=True)
    assert low.granted is True
    high = arbiter.acquire("dialog", {HEAD}, "nod", PRIORITY_DIALOGUE, safety_ok=True)
    assert high.granted is True
    assert low.lease.lease_id in {le.lease_id for le in high.preempted_leases}
    assert arbiter.get_lease(low.lease.lease_id) is None


def test_lower_priority_cannot_preempt_higher_priority(arbiter):
    arbiter.acquire("dialog", {HEAD}, "nod", PRIORITY_DIALOGUE, safety_ok=True)
    result = arbiter.acquire("attract", {HEAD}, "idle_look", PRIORITY_ATTRACT, safety_ok=True)
    assert result.granted is False


def test_safety_critical_lease_cannot_be_preempted_by_normal_priority(arbiter):
    arbiter.acquire("estop", {HEAD, LEFT_ARM, RIGHT_ARM}, "halt", PRIORITY_EMERGENCY_STOP, safety_ok=True)
    result = arbiter.acquire("dialog", {HEAD}, "nod", PRIORITY_DIALOGUE, safety_ok=True)
    assert result.granted is False


def test_emergency_revoke_all_ignores_safety_ok_and_priority(arbiter):
    arbiter.acquire("dialog", {SPEECH}, "say", PRIORITY_DIALOGUE, safety_ok=True)
    arbiter.acquire("gesture", {LEFT_ARM}, "wave", PRIORITY_PRESENTATION, safety_ok=True)
    revoked = arbiter.emergency_revoke_all("Bumper ausgeloest")
    assert len(revoked) == 2
    assert arbiter.active_leases() == []


def test_emergency_revoke_all_on_empty_arbiter_is_a_safe_noop(arbiter):
    assert arbiter.emergency_revoke_all("test") == []


# ---- Sicherheit ----

def test_acquire_rejected_when_safety_not_ok(arbiter):
    result = arbiter.acquire("dialog", {HEAD}, "nod", PRIORITY_DIALOGUE, safety_ok=False)
    assert result.granted is False
    assert "SafetyState" in result.reason


def test_fresh_arbiter_starts_with_no_active_leases(arbiter):
    assert arbiter.active_leases() == []


def test_monotonic_time_basis_is_used_not_wall_clock(clock):
    arbiter = ActuatorArbiter(now_fn=clock)
    result = arbiter.acquire("a", {HEAD}, "x", safety_ok=True, priority=PRIORITY_DIALOGUE, ttl_s=1.0)
    assert result.lease.started_at == clock.t
    assert result.lease.expires_at == clock.t + 1.0


# ---- Entwicklungsauftrag 04-B, AP8.3: gleicher Owner, verschiedene Ziele ----

def test_same_owner_different_goal_id_conflicts_on_overlapping_resources(arbiter):
    # Bestaetigter Fund (siehe DEVELOPMENT_ORDER_04_B_REPORT.md, AP8
    # Commit 1/11, Abschnitt 3.5): zwei PlayGesture-Ziele DERSELBEN
    # Bridge mit unterschiedlicher goal_id duerfen NIE beide RIGHT_ARM
    # gleichzeitig halten.
    first = arbiter.acquire(
        "pepper_bridge", {RIGHT_ARM}, "play_gesture:wave_right", PRIORITY_DIALOGUE,
        safety_ok=True, goal_id="goal-1")
    assert first.granted is True
    second = arbiter.acquire(
        "pepper_bridge", {RIGHT_ARM}, "play_gesture:t_pose", PRIORITY_DIALOGUE,
        safety_ok=True, goal_id="goal-2")
    assert second.granted is False
    assert "pepper_bridge" in second.conflicting_owners
    # Niemals zwei parallele Hardwaretrajektorien -- die erste Lease
    # bleibt unveraendert aktiv.
    assert arbiter.get_lease(first.lease.lease_id) is not None


def test_same_owner_disjoint_resources_run_in_parallel(arbiter):
    first = arbiter.acquire(
        "pepper_bridge", {RIGHT_ARM}, "play_gesture:wave_right", PRIORITY_DIALOGUE,
        safety_ok=True, goal_id="goal-1")
    second = arbiter.acquire(
        "pepper_bridge", {LEFT_ARM}, "play_gesture:point_to_self", PRIORITY_DIALOGUE,
        safety_ok=True, goal_id="goal-2")
    assert first.granted is True
    assert second.granted is True


def test_same_owner_same_goal_id_can_reacquire_without_self_conflict(arbiter):
    # Ein echtes Re-Acquire/eine Erneuerung DESSELBEN Ziels (dieselbe
    # goal_id) darf nicht an der eigenen, noch aktiven Lease scheitern.
    first = arbiter.acquire(
        "pepper_bridge", {RIGHT_ARM}, "play_gesture:wave_right", PRIORITY_DIALOGUE,
        safety_ok=True, goal_id="goal-1")
    assert first.granted is True
    second = arbiter.acquire(
        "pepper_bridge", {RIGHT_ARM}, "play_gesture:wave_right", PRIORITY_DIALOGUE,
        safety_ok=True, goal_id="goal-1")
    assert second.granted is True


def test_same_owner_empty_goal_id_still_conflicts_with_itself(arbiter):
    # Ein leeres goal_id (Aufrufer, die keins mitgeben) darf NIE als
    # "dasselbe Ziel" gelten -- sonst waere genau derselbe Fehler unter
    # einem anderen Namen wieder da.
    first = arbiter.acquire(
        "legacy_owner", {HEAD}, "purpose_a", PRIORITY_DIALOGUE, safety_ok=True)
    assert first.granted is True
    second = arbiter.acquire(
        "legacy_owner", {HEAD}, "purpose_b", PRIORITY_DIALOGUE, safety_ok=True)
    assert second.granted is False


def test_different_owners_with_the_same_goal_id_still_conflict(arbiter):
    # goal_id-Uebereinstimmung allein reicht NICHT -- der Ausschluss gilt
    # nur fuer DENSELBEN owner_id UND dieselbe goal_id zusammen.
    first = arbiter.acquire(
        "owner_a", {HEAD}, "purpose_a", PRIORITY_DIALOGUE, safety_ok=True, goal_id="shared-id")
    assert first.granted is True
    second = arbiter.acquire(
        "owner_b", {HEAD}, "purpose_b", PRIORITY_DIALOGUE, safety_ok=True, goal_id="shared-id")
    assert second.granted is False
