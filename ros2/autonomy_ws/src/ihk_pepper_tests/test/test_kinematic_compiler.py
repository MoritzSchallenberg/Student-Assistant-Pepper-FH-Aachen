import pytest

from ihk_pepper_bridge.gesture_catalog import Gesture
from ihk_pepper_bridge.kinematic_compiler import (
    KinematicCompiler,
    KinematicCompileError,
    NEUTRAL_STAND_POSE,
    fill_missing_joint_holds,
)


def _v2_gesture(keyframes, **overrides):
    data = {
        "schema_version": 2,
        "name": "test_gesture",
        "keyframes": keyframes,
    }
    data.update(overrides)
    return Gesture(data, source_path="test")


# ---- fill_missing_joint_holds (reine Funktion) ----

def test_fill_missing_joint_holds_carries_last_known_value_forward():
    keyframes = [
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1, "HeadPitch": 0.2}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.3}},  # HeadPitch fehlt hier
    ]
    filled = fill_missing_joint_holds(keyframes, ["HeadYaw", "HeadPitch"], start_pose={})
    assert filled[1]["joints"]["HeadPitch"] == 0.2  # Haltewert aus Keyframe 0


def test_fill_missing_joint_holds_uses_start_pose_for_joint_absent_at_t0():
    keyframes = [
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2, "HipRoll": 0.05}},
    ]
    filled = fill_missing_joint_holds(
        keyframes, ["HeadYaw", "HipRoll"], start_pose={"HipRoll": 0.01},
    )
    assert filled[0]["joints"]["HipRoll"] == 0.01  # kommt aus start_pose, nicht erraten


def test_fill_missing_joint_holds_raises_without_any_known_value():
    keyframes = [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}}]
    with pytest.raises(KinematicCompileError):
        fill_missing_joint_holds(keyframes, ["HeadYaw", "HipRoll"], start_pose={})


# ---- KinematicCompiler.compile() ----

def test_compile_rejects_v1_gesture():
    gesture = Gesture(
        {"name": "seq", "steps": [{"joint": "HeadYaw", "angle": 0.1, "duration": 1.0}]},
        source_path="test",
    )
    with pytest.raises(KinematicCompileError):
        KinematicCompiler().compile(gesture)


def test_compile_produces_identical_time_axis_for_every_joint():
    # LShoulderPitch nur in kf0/kf2, RShoulderPitch in allen drei -- vorher
    # bekamen beide Gelenke UNTERSCHIEDLICHE Zeitachsen (Bug, siehe
    # kinematic_compiler.py-Moduldoku).
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.5, "RShoulderPitch": 0.5}},
        {"time_from_start_s": 0.5, "joints": {"RShoulderPitch": 0.3}},
        {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.0, "RShoulderPitch": 0.0}},
    ])
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0)
    assert plan.time_lists[0] == plan.time_lists[1]
    assert len(plan.time_lists[0]) == 3
    # LShoulderPitch haelt bei t=0.5 den Wert von t=0.0 (0.5)
    idx = plan.joint_names.index("LShoulderPitch")
    assert plan.angle_lists[idx][1] == pytest.approx(0.5)


def test_compile_falls_back_to_neutral_stand_pose_without_start_pose():
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2, "HipRoll": 0.1}},
    ])
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0)
    idx = plan.joint_names.index("HipRoll")
    assert plan.angle_lists[idx][0] == pytest.approx(NEUTRAL_STAND_POSE["HipRoll"])


def test_compile_uses_given_start_pose_instead_of_neutral():
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2, "HipRoll": 0.1}},
    ])
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0, start_pose={"HipRoll": 0.2})
    idx = plan.joint_names.index("HipRoll")
    assert plan.angle_lists[idx][0] == pytest.approx(0.2)


def test_compile_rejects_excessive_acceleration_after_speed_scaling():
    # Passiert die Geschwindigkeitspruefung beim Laden (Gesture._validate_v2,
    # jeweils 2.9 rad/s < 3.0 rad/s-Grenze), wird aber durch den hohen
    # speed_scale (Beschleunigung skaliert quadratisch mit dem Zeitfaktor)
    # beschleunigungsseitig unzulaessig -- genau der in AP12 behobene, zuvor
    # ungeprüfte Fall.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": -0.5}},
        {"time_from_start_s": 0.2, "joints": {"LShoulderPitch": 0.08}},
        {"time_from_start_s": 0.4, "joints": {"LShoulderPitch": -0.5}},
    ])
    with pytest.raises(KinematicCompileError):
        KinematicCompiler().compile(gesture, speed_scale=1.5)


def test_compile_carries_breathing_and_gesture_name_into_plan():
    gesture = _v2_gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}}],
        disable_breathing=["Arms"],
    )
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0)
    assert plan.disable_breathing_parts == ["Arms"]
    assert plan.source_gesture_name == "test_gesture"


def test_compile_rejects_non_positive_speed_scale():
    gesture = _v2_gesture([{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}}])
    with pytest.raises(KinematicCompileError):
        KinematicCompiler().compile(gesture, speed_scale=0.0)


def test_compile_rejects_synthetically_filled_value_outside_margin():
    # HeadYaw kommt erst im zweiten Keyframe vor -- der Haltewert fuer
    # Keyframe 0 wird komplett aus start_pose aufgefuellt und durchlief
    # NIE Gesture._validate_v2() (das prueft nur woertlich in Keyframes
    # stehende Werte). compile() muss auch diesen synthetischen Wert
    # gegenpruefen (Verteidigung in der Tiefe, siehe Moduldoku).
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HipRoll": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HipRoll": 0.1, "HeadYaw": 0.1}},
    ])
    with pytest.raises(KinematicCompileError):
        KinematicCompiler().compile(gesture, speed_scale=1.0, start_pose={"HipRoll": 0.1, "HeadYaw": 99.0})
