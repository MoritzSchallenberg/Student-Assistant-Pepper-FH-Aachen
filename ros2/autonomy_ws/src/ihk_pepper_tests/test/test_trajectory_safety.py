"""
Tests fuer trajectory_safety.py (Entwicklungsauftrag 04-B, AP8.5):
TrajectorySafetyValidator/-Backend-Schnittstelle, JointAndTimingValidator,
DisabledCollisionBackend.
"""
import pytest

from ihk_pepper_bridge.gesture_catalog import Gesture
from ihk_pepper_bridge.kinematic_compiler import COMPILER_VERSION
from ihk_pepper_bridge.trajectory_safety import (
    DisabledCollisionBackend,
    JointAndTimingValidator,
    TrajectorySafetyBackend,
    TrajectorySafetyReport,
    TrajectorySafetyValidator,
)


def _gesture(keyframes, **overrides):
    data = {"schema_version": 2, "name": "test_gesture", "keyframes": keyframes}
    data.update(overrides)
    return Gesture(data, source_path="test")


# ---- TrajectorySafetyReport ----

def test_report_rejects_invalid_verdict():
    with pytest.raises(ValueError):
        TrajectorySafetyReport(gesture_name="x", verdict="mostly_fine")


# ---- TrajectorySafetyValidator Konstruktion ----

def test_validator_requires_joint_and_timing_backend():
    with pytest.raises(ValueError, match="JointAndTimingValidator"):
        TrajectorySafetyValidator(backends=[DisabledCollisionBackend()])


def test_validator_defaults_to_joint_and_timing_backend():
    validator = TrajectorySafetyValidator()
    assert any(isinstance(b, JointAndTimingValidator) for b in validator.backends)


# ---- JointAndTimingValidator: kompiliert erfolgreich ----

def test_valid_gesture_yields_pass_verdict_from_joint_and_timing_validator_alone():
    # Entwicklungsauftrag 04-B, AP8-R1.8: der STANDARD-Validator enthaelt
    # seit diesem Auftrag zusaetzlich DisabledCollisionBackend (siehe
    # test_default_validator_is_inconclusive_without_a_real_collision_backend
    # unten) -- 'pass' ist deshalb nur mit JointAndTimingValidator ALLEIN
    # erreichbar (bewusst explizit konstruiert, nicht der Default).
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator()])
    report = validator.validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.verdict == "pass"
    assert report.joint_timing_errors == []


def test_default_validator_is_inconclusive_without_a_real_collision_backend():
    # Entwicklungsauftrag 04-B, AP8-R1.8 (bestaetigter Fund 3.7): der
    # STANDARDPFAD (TrajectorySafetyValidator() ohne explizite backends)
    # darf NIEMALS gleichzeitig verdict='pass' UND collision_checked=false
    # melden -- das saehe wie ein (nicht vorhandener) Kollisionsnachweis
    # aus. Ohne echtes Kollisions-Backend ist der Standardreport deshalb
    # STRUKTURELL 'inconclusive'.
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    report = TrajectorySafetyValidator().validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.verdict == "inconclusive"
    assert report.collision_checked is False
    assert report.joint_timing_errors == []
    assert report.compiler_version == COMPILER_VERSION
    assert "HeadYaw" in report.affected_joints


def test_invalid_gesture_yields_fail_verdict_with_error_message():
    # t=0-Sprung: start_pose weicht vom ersten Keyframe ab.
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.5}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    report = TrajectorySafetyValidator().validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.verdict == "fail"
    assert report.joint_timing_errors  # mindestens eine Fehlermeldung
    assert any("Geschwindigkeit" in e for e in report.joint_timing_errors)


def test_compile_error_is_never_silently_swallowed_into_a_pass():
    gesture = _gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}}],
        max_duration_s=0.1,
    )
    report = TrajectorySafetyValidator().validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.verdict == "fail"


# ---- Konservative Hinweisflaggen (AP8.5) ----

def test_hip_and_knee_motion_triggers_manual_review_flag():
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HipPitch": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HipPitch": 0.1}},
    ])
    report = TrajectorySafetyValidator().validate(gesture, start_pose={"HipPitch": 0.0})
    assert any("Huefte/Knie" in m for m in report.requires_manual_review)


def test_simultaneous_torso_and_arm_motion_triggers_manual_review_flag():
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HipPitch": 0.0, "LShoulderPitch": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HipPitch": 0.1, "LShoulderPitch": 0.3}},
    ])
    report = TrajectorySafetyValidator().validate(
        gesture, start_pose={"HipPitch": 0.0, "LShoulderPitch": 0.0})
    assert any("Torso" in m for m in report.requires_manual_review)


def test_bilateral_arm_motion_triggers_manual_review_flag():
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.0, "RShoulderPitch": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.3, "RShoulderPitch": -0.3}},
    ])
    report = TrajectorySafetyValidator().validate(
        gesture, start_pose={"LShoulderPitch": 0.0, "RShoulderPitch": 0.0})
    assert any("Bilaterale" in m for m in report.requires_manual_review)


def test_combined_head_and_arm_motion_triggers_manual_review_flag():
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.0, "RShoulderPitch": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadPitch": -0.1, "RShoulderPitch": 0.3}},
    ])
    report = TrajectorySafetyValidator().validate(
        gesture, start_pose={"HeadPitch": 0.0, "RShoulderPitch": 0.0})
    assert any("Gesichtsbereich" in m for m in report.requires_manual_review)


def test_self_hug_symbolic_always_carries_the_contactless_reminder():
    gesture = _gesture(
        [{"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.3}}],
        name="self_hug_symbolic",
    )
    report = TrajectorySafetyValidator().validate(gesture, start_pose={"LShoulderPitch": 0.0})
    assert any("kontaktlos" in m for m in report.requires_manual_review)


def test_simple_single_joint_head_gesture_has_no_manual_review_flags():
    # JointAndTimingValidator allein, um die kollisionsbezogene
    # requires_manual_review-Notiz von DisabledCollisionBackend (siehe
    # dortiger Test) nicht mit den kinematischen Hinweisflaggen zu
    # vermischen.
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator()])
    report = validator.validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.requires_manual_review == []


# ---- DisabledCollisionBackend ----

def test_disabled_collision_backend_reports_inconclusive_and_no_collision_claim():
    gesture = _gesture([{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}}])
    backend = DisabledCollisionBackend()
    report = backend.check(gesture, plan=None, start_pose=None, compile_error=None)
    assert report.verdict == "inconclusive"
    assert report.collision_checked is False
    assert "KEINE" in report.collision_backend_note


def test_validator_with_both_backends_stays_inconclusive_even_if_joint_timing_passes():
    # Entwicklungsauftrag 04-B, AP8.7: 'inconclusive' darf NIE automatisch
    # zu einem 'pass' verwaschen werden, nur weil EIN anderes Backend
    # bestanden hat.
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator(), DisabledCollisionBackend()])
    report = validator.validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.verdict == "inconclusive"
    assert "disabled_collision" in report.backend_names
    assert "joint_and_timing" in report.backend_names


def test_validator_fail_overrides_inconclusive_in_merged_verdict():
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.5}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator(), DisabledCollisionBackend()])
    report = validator.validate(gesture, start_pose={"HeadYaw": 0.0})
    assert report.verdict == "fail"


# ---- Vorkompilierten Plan wiederverwenden (synchronisierte Vorschau) ----

def test_validate_accepts_a_precompiled_plan_without_recompiling():
    from ihk_pepper_bridge.kinematic_compiler import KinematicCompiler
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    plan = KinematicCompiler().compile(gesture, start_pose={"HeadYaw": 0.0})
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator()])
    report = validator.validate(gesture, plan=plan)
    assert report.verdict == "pass"
    assert report.effective_duration_s == pytest.approx(1.0)


# ---- Entwicklungsauftrag 04-B, AP8-R1.8: Vertrauensgrenze bei vorkompilierten Plaenen ----

def test_a_plan_for_a_different_gesture_name_is_rejected():
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    from ihk_pepper_bridge.kinematic_compiler import KinematicCompiler
    other_gesture = _gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}}],
        name="a_completely_different_gesture",
    )
    foreign_plan = KinematicCompiler().compile(other_gesture, start_pose={"HeadYaw": 0.0})
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator()])
    report = validator.validate(gesture, plan=foreign_plan)
    assert report.verdict == "fail"
    assert any("source_gesture_name" in e for e in report.joint_timing_errors)


def test_a_plan_with_a_different_joint_set_is_rejected():
    from ihk_pepper_bridge.kinematic_compiler import KinematicCompiler
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    other_gesture = _gesture(
        [{"time_from_start_s": 0.0, "joints": {"HipPitch": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"HipPitch": 0.1}}],
        name="test_gesture",  # gleicher Name, ABER andere Gelenke
    )
    mismatched_plan = KinematicCompiler().compile(other_gesture, start_pose={"HipPitch": 0.0})
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator()])
    report = validator.validate(gesture, plan=mismatched_plan)
    assert report.verdict == "fail"
    assert any("Gelenkmenge" in e for e in report.joint_timing_errors)


def test_a_plan_with_an_implausible_duration_for_the_given_speed_scale_is_rejected():
    from ihk_pepper_bridge.kinematic_compiler import KinematicCompiler
    gesture = _gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ])
    # Bei speed_scale=1.0 kompiliert (Dauer 1.0s) -- als speed_scale=0.5
    # ausgegeben (erwartete Dauer waere 2.0s): Diskrepanz muss auffallen.
    plan_at_wrong_scale = KinematicCompiler().compile(gesture, speed_scale=1.0, start_pose={"HeadYaw": 0.0})
    validator = TrajectorySafetyValidator(backends=[JointAndTimingValidator()])
    report = validator.validate(gesture, speed_scale=0.5, plan=plan_at_wrong_scale)
    assert report.verdict == "fail"
    assert any("max_duration_s" in e for e in report.joint_timing_errors)


# ---- TrajectorySafetyBackend-Basisklasse ----

def test_base_backend_check_is_not_implemented():
    with pytest.raises(NotImplementedError):
        TrajectorySafetyBackend().check(None, None, None, None)
