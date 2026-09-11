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
    # Entwicklungsauftrag 04-B, AP8.4: start_pose muss dem ersten Keyframe
    # entsprechen, sonst lehnt der neue Start-zu-erstem-Keyframe-
    # Uebergangscheck den sonst impliziten t=0-Sprung korrekt ab -- fuer
    # diesen Test irrelevant, es geht ausschliesslich um die gemeinsame
    # Zeitachse ueber mehrere Gelenke hinweg.
    plan = KinematicCompiler().compile(
        gesture, speed_scale=1.0,
        start_pose={"LShoulderPitch": 0.5, "RShoulderPitch": 0.5},
    )
    assert plan.time_lists[0] == plan.time_lists[1]
    assert len(plan.time_lists[0]) == 3
    # LShoulderPitch haelt bei t=0.5 den Wert von t=0.0 (0.5)
    idx = plan.joint_names.index("LShoulderPitch")
    assert plan.angle_lists[idx][1] == pytest.approx(0.5)


def test_compile_falls_back_to_neutral_stand_pose_without_start_pose():
    # HeadYaw beginnt bei 0.0 (== NEUTRAL_STAND_POSE["HeadYaw"]) -- dieser
    # Test prueft ausschliesslich das Fallback-Verhalten fuer HipRoll (das
    # erst in Keyframe 1 vorkommt), nicht die Start-Uebergangspruefung.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2, "HipRoll": 0.1}},
    ])
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0)
    idx = plan.joint_names.index("HipRoll")
    assert plan.angle_lists[idx][0] == pytest.approx(NEUTRAL_STAND_POSE["HipRoll"])


def test_compile_uses_given_start_pose_instead_of_neutral():
    # HeadYaw beginnt bei 0.0 (== NEUTRAL_STAND_POSE["HeadYaw"], da fuer
    # HeadYaw kein expliziter start_pose-Wert uebergeben wird) -- dieser
    # Test prueft ausschliesslich, dass ein explizit uebergebener
    # start_pose-Wert fuer HipRoll den Neutral-Fallback ersetzt.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
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
    # HeadYaw beginnt bei 0.0 (== NEUTRAL_STAND_POSE["HeadYaw"]) -- der
    # konkrete Winkel ist fuer diesen Test irrelevant, es geht nur um
    # disable_breathing_parts/source_gesture_name im Plan.
    gesture = _v2_gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}}],
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


# ---- Entwicklungsauftrag 04-B, AP8.4: NaN/inf-Haertung ----

def test_compile_rejects_nan_speed_scale():
    # NaN <= 0 ist in Python False -- "scale <= 0" allein wuerde das NICHT
    # abfangen, siehe _is_finite()-Kommentar in kinematic_compiler.py.
    gesture = _v2_gesture([{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}}])
    with pytest.raises(KinematicCompileError):
        KinematicCompiler().compile(gesture, speed_scale=float("nan"))


def test_compile_rejects_infinite_speed_scale():
    gesture = _v2_gesture([{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}}])
    with pytest.raises(KinematicCompileError):
        KinematicCompiler().compile(gesture, speed_scale=float("inf"))


def test_compile_rejects_nan_in_synthetically_filled_angle():
    # HipRoll erscheint nur ueber start_pose (NaN) im ersten Keyframe --
    # analog zu test_compile_rejects_synthetically_filled_value_outside_margin,
    # hier aber mit einem NaN statt einem nur ausserhalb-der-Grenze-Wert.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2, "HipRoll": 0.05}},
    ])
    with pytest.raises(KinematicCompileError, match="NaN/inf"):
        KinematicCompiler().compile(
            gesture, speed_scale=1.0,
            start_pose={"HeadYaw": 0.1, "HipRoll": float("nan")},
        )


# ---- Entwicklungsauftrag 04-B, AP8.4: Geschwindigkeit NACH Skalierung ----

def test_compile_rejects_velocity_that_only_exceeds_the_limit_after_scaling():
    # Auf der UNSKALIERTEN Achse (0.4 rad in 0.4s = 1.0 rad/s) unauffaellig,
    # aber bei speed_scale=10.0 (Zeiten werden durch scale GETEILT, also
    # zehnmal SCHNELLER ausgefuehrt) ergibt sich 0.4/0.04 = 10 rad/s >
    # MAX_JOINT_VELOCITY_RAD_S. Genau der in AP8.4 geforderte Fall:
    # Geschwindigkeit muss auf der AUSGEFUEHRTEN (skalierten) Zeitachse
    # geprueft werden, nicht nur beim YAML-Laden (das nur die unskalierte
    # Achse kennt). KinematicCompiler.compile() selbst deckelt speed_scale
    # NICHT -- das uebernimmt die aufrufende Ausfuehrungsrichtlinie
    # (gesture_execution_policy.py) bzw. gesture_catalog.py::
    # _effective_speed_scale() vor dem Compiler-Aufruf.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 0.4, "joints": {"HeadYaw": 0.4}},
    ])
    with pytest.raises(KinematicCompileError, match="Geschwindigkeit"):
        KinematicCompiler().compile(gesture, speed_scale=10.0)


def test_compile_accepts_velocity_within_limit_after_scaling():
    # Gegenprobe: derselbe Fall bei speed_scale=1.0 bleibt zulaessig.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 0.4, "joints": {"HeadYaw": 0.4}},
    ])
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0)
    assert plan.source_gesture_name == "test_gesture"


# ---- Entwicklungsauftrag 04-B, AP8.4: Start-zu-erstem-Keyframe-Uebergang ----

def test_compile_rejects_instantaneous_jump_from_start_pose_to_first_keyframe():
    # Erster Keyframe liegt bei t=0.0 und weicht vom uebergebenen
    # start_pose ab -> dt=0 bei d_angle!=0 -> unendliche Geschwindigkeit.
    # Genau der in Fund 3.4 beschriebene "t=0-Sprung"-Fall (z.B.
    # greet_open.yaml vor der AP8.4-Migration).
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": -0.05}},
        {"time_from_start_s": 1.2, "joints": {"HeadPitch": 0.0}},
    ])
    with pytest.raises(KinematicCompileError, match="Geschwindigkeit"):
        KinematicCompiler().compile(gesture, speed_scale=1.0, start_pose={"HeadPitch": 0.0})


def test_compile_accepts_small_hold_segment_before_first_real_keyframe():
    # Gegenprobe (die tatsaechlich angewandte Migration): ein zusaetzlicher
    # Haltepunkt bei t=0.0 mit dem Startpose-Wert macht denselben Uebergang
    # zulaessig, ohne die nachfolgende Choreografie zu veraendern.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.0}},
        {"time_from_start_s": 0.2, "joints": {"HeadPitch": -0.05}},
        {"time_from_start_s": 1.2, "joints": {"HeadPitch": 0.0}},
    ])
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0, start_pose={"HeadPitch": 0.0})
    assert plan.source_gesture_name == "test_gesture"


# ---- Entwicklungsauftrag 04-B, AP8.4: max_duration_s im Compiler ----

def test_compile_rejects_effective_duration_exceeding_max_duration_s():
    gesture = _v2_gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}}],
        max_duration_s=0.5,
    )
    # speed_scale=1.0 -> effektive Dauer 1.0s > max_duration_s=0.5s.
    with pytest.raises(KinematicCompileError, match="max_duration_s"):
        KinematicCompiler().compile(gesture, speed_scale=1.0)


def test_compile_rejects_duration_that_only_exceeds_max_duration_s_after_scaling():
    # Auf der unskalierten Achse (1.0s) innerhalb von max_duration_s=1.5s,
    # aber bei speed_scale=0.5 (Zeiten werden GETEILT, doppelt so lang)
    # effektiv 2.0s > 1.5s -- genau der in Fund 3.4 beschriebene Fall
    # (max_duration_s galt bislang faelschlich fuer die unskalierte Achse).
    gesture = _v2_gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}}],
        max_duration_s=1.5,
    )
    with pytest.raises(KinematicCompileError, match="max_duration_s"):
        KinematicCompiler().compile(gesture, speed_scale=0.5)


def test_compile_accepts_duration_within_max_duration_s():
    gesture = _v2_gesture(
        [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
         {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}}],
        max_duration_s=1.5,
    )
    plan = KinematicCompiler().compile(gesture, speed_scale=1.0)
    assert plan.max_duration_s == pytest.approx(1.0)


# ---- Entwicklungsauftrag 04-B, AP8.4: teilweise fehlgeschlagener Snapshot ----

def test_compile_fails_closed_on_explicit_none_in_start_pose_for_a_needed_joint():
    # Ein get_angle()-Ausfall fuer EIN Gelenk (siehe pepper_client.py::
    # restore_joints()' bestehende "if angle is not None"-Behandlung
    # desselben Falls) darf NICHT stillschweigend durch
    # NEUTRAL_STAND_POSE ersetzt werden -- fail-closed statt einer
    # geschaetzten, nicht abgesicherten Neutralpose.
    gesture = _v2_gesture([
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2, "HipRoll": 0.05}},
    ])
    with pytest.raises(KinematicCompileError, match="nicht lesbar"):
        KinematicCompiler().compile(
            gesture, speed_scale=1.0,
            start_pose={"HeadYaw": 0.0, "HipRoll": None},
        )


def test_compile_ignores_none_in_start_pose_for_an_unneeded_joint():
    # Ein None-Eintrag fuer ein Gelenk, das diese Geste GAR NICHT
    # verwendet, darf die Kompilierung nicht faelschlich blockieren.
    gesture = _v2_gesture([{"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}}])
    plan = KinematicCompiler().compile(
        gesture, speed_scale=1.0,
        start_pose={"HeadYaw": 0.0, "HipRoll": None},
    )
    assert plan.source_gesture_name == "test_gesture"
