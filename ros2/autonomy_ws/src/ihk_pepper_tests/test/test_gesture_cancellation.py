"""
Tests fuer gesture_cancellation.py (Entwicklungsauftrag 04-B, AP8-R1.4/1.5):
CancelSignal, restore_allowed(), breathing_may_reactivate().
"""
from ihk_pepper_bridge.gesture_cancellation import (
    ALL_CANCEL_REASONS,
    CancelSignal,
    GestureCancelReason,
    breathing_may_reactivate,
    restore_allowed,
)


# ---- CancelSignal ----

def test_cancel_signal_starts_unset():
    signal = CancelSignal()
    assert signal.is_set() is False
    assert signal.reason is None


def test_first_set_reason_wins():
    signal = CancelSignal()
    signal.set(GestureCancelReason.EMERGENCY_STOP)
    signal.set(GestureCancelReason.NORMAL_USER_CANCEL)
    assert signal.is_set() is True
    assert signal.reason == GestureCancelReason.EMERGENCY_STOP


def test_a_later_normal_cancel_does_not_override_an_earlier_emergency_stop():
    signal = CancelSignal()
    signal.set(GestureCancelReason.EMERGENCY_STOP)
    signal.set(GestureCancelReason.NORMAL_USER_CANCEL)
    assert signal.reason == GestureCancelReason.EMERGENCY_STOP


def test_duplicate_cancel_with_the_same_reason_stays_idempotent():
    signal = CancelSignal()
    signal.set(GestureCancelReason.TIMEOUT)
    signal.set(GestureCancelReason.TIMEOUT)
    assert signal.reason == GestureCancelReason.TIMEOUT


def test_default_set_reason_is_normal_user_cancel():
    signal = CancelSignal()
    signal.set()
    assert signal.reason == GestureCancelReason.NORMAL_USER_CANCEL


def test_wait_returns_immediately_once_set():
    signal = CancelSignal()
    signal.set(GestureCancelReason.TIMEOUT)
    assert signal.wait(timeout=0.01) is True


# ---- restore_allowed() ----

def test_restore_allowed_for_normal_cancel_with_on_cancel_restore_and_safe_context():
    assert restore_allowed(GestureCancelReason.NORMAL_USER_CANCEL, "restore", True) is True


def test_restore_forbidden_for_normal_cancel_with_on_cancel_restore_but_unsafe_context():
    assert restore_allowed(GestureCancelReason.NORMAL_USER_CANCEL, "restore", False) is False


def test_restore_forbidden_for_normal_cancel_with_on_cancel_hold():
    assert restore_allowed(GestureCancelReason.NORMAL_USER_CANCEL, "hold", True) is False


def test_restore_forbidden_for_every_non_normal_reason_even_with_on_cancel_restore_and_safe_context():
    for reason in ALL_CANCEL_REASONS - {GestureCancelReason.NORMAL_USER_CANCEL}:
        assert restore_allowed(reason, "restore", True) is False, reason


# ---- breathing_may_reactivate() ----

def test_breathing_reactivates_on_normal_completion_when_safe():
    assert breathing_may_reactivate(None, True) is True


def test_breathing_does_not_reactivate_on_normal_completion_when_unsafe():
    assert breathing_may_reactivate(None, False) is False


def test_breathing_reactivates_on_normal_user_cancel_when_safe():
    assert breathing_may_reactivate(GestureCancelReason.NORMAL_USER_CANCEL, True) is True


def test_breathing_reactivates_on_codeword_interrupt_only_when_freshly_confirmed_safe():
    assert breathing_may_reactivate(GestureCancelReason.CODEWORD_INTERRUPT, True) is True
    assert breathing_may_reactivate(GestureCancelReason.CODEWORD_INTERRUPT, False) is False


def test_breathing_never_reactivates_for_safety_critical_reasons_even_when_safe_now():
    for reason in (
        GestureCancelReason.TIMEOUT, GestureCancelReason.LEASE_REVOKED,
        GestureCancelReason.PREEMPTED, GestureCancelReason.SAFETY_INVALID,
        GestureCancelReason.EMERGENCY_STOP, GestureCancelReason.BUMPER_ACTIVE,
        GestureCancelReason.NAVIGATION_STARTED, GestureCancelReason.MAPPING_STARTED,
        GestureCancelReason.INTERACTION_INVALID, GestureCancelReason.PEPPER_UNREACHABLE,
        GestureCancelReason.TRANSPORT_FAILED, GestureCancelReason.NODE_SHUTDOWN,
    ):
        assert breathing_may_reactivate(reason, True) is False, reason
