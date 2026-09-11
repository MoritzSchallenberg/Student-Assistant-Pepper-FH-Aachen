import os
import tempfile

import pytest
import yaml

from ihk_pepper_bridge.gesture_catalog import Gesture, GestureCatalog, GestureValidationError


def _write_yaml(directory, name, data):
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


class FakePepperClient:
    """Testdouble, das Aufrufe aufzeichnet statt echte SSH-Kommandos zu
    senden -- kein Test darf jemals eine echte Hardwareaktion ausloesen."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.breathing_calls = []
        self.snapshot_taken = None
        self.restored = None
        # "set_angle": simuliert Abbruch fuer v1. "play_trajectory": simuliert
        # Abbruch NUR beim ERSTEN Aufruf (der eigentlichen Gestenbewegung) --
        # der zweite Aufruf (die Wiederherstellung, siehe AP12: restore()
        # nutzt seitdem ebenfalls play_trajectory statt einer separaten
        # restore_joints()-Methode) simuliert damit den realistischen Fall,
        # dass eine komplexe Mehrgelenk-Trajektorie abgelehnt wird, eine
        # einfache Ein-Winkel-Wiederherstellung ueber dieselbe Verbindung
        # aber weiterhin funktioniert.
        self._fail_on = fail_on

    def set_breathing(self, enabled, part=None):
        self.breathing_calls.append((enabled, part))

    def snapshot_joints(self, joints):
        self.snapshot_taken = list(joints)
        # Entwicklungsauftrag 04-B, AP8.4: LShoulderPitch/RShoulderPitch
        # muessen mit dem ERSTEN Keyframe der Standard-v2-Testgeste
        # (_v2_data(), t=0.0, =0.0 == NEUTRAL_STAND_POSE) uebereinstimmen --
        # sonst lehnt der neue Start-zu-erstem-Keyframe-Uebergangscheck den
        # impliziten Sprung korrekt als unendliche Geschwindigkeit ab.
        # Andere Gelenke (z.B. HeadYaw in den v1-Tests dieser Datei) bleiben
        # bei 0.1, damit deren eigene, unabhaengige Erwartungen unveraendert
        # bleiben.
        return {j: (0.0 if j in ("LShoulderPitch", "RShoulderPitch") else 0.1) for j in joints}

    def get_angle(self, joint):
        return 0.1

    def restore_joints(self, snapshot, duration=1.5):
        # Nur noch von der v1-Wiedergabe genutzt (bewusst weiterhin
        # sequenziell, siehe gesture_catalog.py-Moduldoku) -- v2 nutzt seit
        # AP12 restore() ueber play_trajectory() (siehe oben).
        self.restored = snapshot

    def set_angle(self, joint, angle, duration=1.0):
        if self._fail_on == "set_angle":
            raise RuntimeError("simulierter Abbruch")
        self.calls.append(("set_angle", joint, angle, duration))

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        self.calls.append(("play_trajectory", joint_names, angle_lists, time_lists))
        is_restore_call = len([c for c in self.calls if c[0] == "play_trajectory"]) > 1
        if self._fail_on == "play_trajectory" and not is_restore_call:
            raise RuntimeError("simulierter Abbruch")
        if is_restore_call:
            self.restored = dict(zip(joint_names, (a[0] for a in angle_lists)))


# ---- Schema-Migration / Fehlermeldungen ----

def test_v1_gesture_still_loads_unchanged():
    with tempfile.TemporaryDirectory() as d:
        _write_yaml(d, "old_wave", {
            "name": "old_wave",
            "steps": [{"joint": "RShoulderPitch", "angle": -1.0, "duration": 1.0}],
        })
        catalog = GestureCatalog(d)
        assert catalog.reload() == []
        assert catalog.get("old_wave").schema_version == 1


def test_unknown_schema_version_gives_clear_error():
    with tempfile.TemporaryDirectory() as d:
        _write_yaml(d, "broken", {"name": "broken", "schema_version": 99, "keyframes": []})
        catalog = GestureCatalog(d)
        errors = catalog.reload()
        assert len(errors) == 1
        assert "schema_version" in errors[0]


# ---- v2-Validierung ----

def _v2_data(name="test_gesture", keyframes=None, **overrides):
    data = {
        "schema_version": 2,
        "name": name,
        # Entwicklungsauftrag 04-B, AP8.4: kf0 haelt NEUTRAL_STAND_POSE
        # (0.0) fuer beide Gelenke -- das eigentliche Bewegungsziel (0.5)
        # liegt bei t=1.0. So gibt es weder bei explizitem start_pose (aus
        # FakePepperClient.snapshot_joints, hardware-pfad) noch beim
        # Neutral-Fallback (dry_run, kein Snapshot) einen Sprung am Start.
        "keyframes": keyframes or [
            {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.0, "RShoulderPitch": 0.0}},
            {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.5, "RShoulderPitch": 0.5}},
        ],
    }
    data.update(overrides)
    return data


def test_v2_parallel_joints_within_one_keyframe_load_correctly():
    gesture = Gesture(_v2_data(), source_path="test")
    assert gesture.affected_joints() == ["LShoulderPitch", "RShoulderPitch"]
    assert gesture.duration_s() == 1.0


def test_v2_joint_outside_limit_rejected():
    kf = [{"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 99.0}}]
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_joint_within_limit_but_inside_safety_margin_rejected():
    # HeadYaw-Grenze ist 2.0857 -- innerhalb der 0.05-Marge, aber ausserhalb
    # der margenbereinigten Grenze.
    kf = [{"time_from_start_s": 0.0, "joints": {"HeadYaw": 2.06}}]
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_unknown_joint_rejected():
    kf = [{"time_from_start_s": 0.0, "joints": {"NotAJoint": 0.1}}]
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_non_monotonic_time_rejected():
    kf = [
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ]
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_decreasing_time_rejected():
    kf = [
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 0.5, "joints": {"HeadYaw": 0.2}},
    ]
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_nan_time_from_start_s_rejected():
    # Entwicklungsauftrag 04-B, AP8.4 (bestaetigter Fund): "t < 0" allein
    # faengt KEIN NaN ab (NaN < 0 ist in Python False) -- ein NaN time
    # wuerde sonst weder vom Vorzeichen- noch vom Monotonie-Check erkannt.
    kf = [
        {"time_from_start_s": float("nan"), "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": 1.0, "joints": {"HeadYaw": 0.2}},
    ]
    with pytest.raises(GestureValidationError, match="NaN/inf"):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_infinite_time_from_start_s_rejected():
    kf = [
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.1}},
        {"time_from_start_s": float("inf"), "joints": {"HeadYaw": 0.2}},
    ]
    with pytest.raises(GestureValidationError, match="NaN/inf"):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_too_fast_velocity_rejected():
    # HeadYaw 0.0 -> 2.0 in 0.1s = 20 rad/s, weit ueber MAX_JOINT_VELOCITY_RAD_S.
    kf = [
        {"time_from_start_s": 0.0, "joints": {"HeadYaw": 0.0}},
        {"time_from_start_s": 0.1, "joints": {"HeadYaw": 2.0}},
    ]
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(keyframes=kf), source_path="test")


def test_v2_previously_live_tested_wave_velocity_is_accepted():
    # Exakt die live getestete wave_right-Oszillationsgeschwindigkeit
    # (1.0 rad in 0.4s = 2.5 rad/s) darf NICHT durch die neue
    # Geschwindigkeitspruefung blockiert werden.
    kf = [
        {"time_from_start_s": 0.0, "joints": {"RElbowYaw": 0.6}},
        {"time_from_start_s": 0.4, "joints": {"RElbowYaw": 1.6}},
    ]
    gesture = Gesture(_v2_data(keyframes=kf), source_path="test")
    assert gesture.schema_version == 2


def test_v2_invalid_tested_status_rejected():
    with pytest.raises(GestureValidationError):
        Gesture(_v2_data(tested_status="works_on_my_machine"), source_path="test")


# ---- Zustandsfreigabe / Sperren beim Abspielen ----

def _catalog_with(data):
    d = tempfile.mkdtemp()
    _write_yaml(d, data["name"], data)
    catalog = GestureCatalog(d)
    assert catalog.reload() == []
    return catalog


def test_gesture_locked_outside_allowed_interaction_states():
    catalog = _catalog_with(_v2_data(allowed_interaction_states=["CONVERSATION_READY"]))
    client = FakePepperClient()
    with pytest.raises(GestureValidationError):
        catalog.play(client, "test_gesture", current_interaction_state="IDLE")
    assert client.calls == []


def test_gesture_locked_during_nav2_movement():
    catalog = _catalog_with(_v2_data())  # v2-Gesten sind implizit requires_stationary-artig gesperrt
    client = FakePepperClient()
    with pytest.raises(GestureValidationError):
        catalog.play(client, "test_gesture", nav2_moving=True)
    assert client.calls == []


def test_head_gesture_locked_during_mapping():
    kf = [{"time_from_start_s": 0.5, "joints": {"HeadYaw": 0.2}}]
    catalog = _catalog_with(_v2_data(keyframes=kf))
    client = FakePepperClient()
    with pytest.raises(GestureValidationError):
        catalog.play(client, "test_gesture", mapping_active=True)
    assert client.calls == []


def test_non_head_gesture_allowed_during_mapping():
    catalog = _catalog_with(_v2_data())  # bewegt nur Schultern, keine Kopfgelenke
    client = FakePepperClient()
    result = catalog.play(client, "test_gesture", mapping_active=True)
    assert result.dry_run is False
    assert client.calls  # tatsaechlich ausgefuehrt


# ---- Dry-Run ----

def test_dry_run_performs_no_hardware_action():
    catalog = _catalog_with(_v2_data())
    client = FakePepperClient()
    result = catalog.play(client, "test_gesture", dry_run=True)
    assert result.dry_run is True
    assert len(result.plan) == 2
    assert client.calls == []
    assert client.breathing_calls == []
    assert client.snapshot_taken is None


def test_dry_run_v1_performs_no_hardware_action():
    with tempfile.TemporaryDirectory() as d:
        _write_yaml(d, "seq", {
            "name": "seq",
            "steps": [{"joint": "HeadYaw", "angle": 0.1, "duration": 1.0}],
        })
        catalog = GestureCatalog(d)
        catalog.reload()
        client = FakePepperClient()
        result = catalog.play(client, "seq", dry_run=True)
        assert result.dry_run is True
        assert client.calls == []


# ---- Cancel / Fehler stellt sicheren Zustand her ----

def test_failure_mid_playback_still_restores_joints_v2():
    catalog = _catalog_with(_v2_data(disable_breathing=["Arms"]))
    client = FakePepperClient(fail_on="play_trajectory")
    with pytest.raises(RuntimeError):
        catalog.play(client, "test_gesture")
    # restore() sendet seit AP12 EINEN play_trajectory()-Aufruf mit den
    # Snapshot-Winkeln (statt der alten restore_joints()-Methode) --
    # genau die zwei betroffenen Gelenke, je Snapshot-Winkel 0.0 (AP8.4:
    # FakePepperClient.snapshot_joints() muss mit dem ersten Keyframe der
    # Standardgeste uebereinstimmen).
    assert client.restored == {"LShoulderPitch": 0.0, "RShoulderPitch": 0.0}
    assert client.breathing_calls  # Breathing wurde in jedem Fall wieder aktiviert


def test_failure_mid_playback_still_restores_joints_v1():
    with tempfile.TemporaryDirectory() as d:
        _write_yaml(d, "seq", {
            "name": "seq",
            "disable_breathing": ["Arms"],
            "steps": [{"joint": "HeadYaw", "angle": 0.1, "duration": 1.0}],
        })
        catalog = GestureCatalog(d)
        catalog.reload()
        client = FakePepperClient(fail_on="set_angle")
        with pytest.raises(RuntimeError):
            catalog.play(client, "seq")
        assert client.restored == {"HeadYaw": 0.1}
        assert (True, "Arms") in client.breathing_calls


# ---- Speed-Scale-Grenzen ----

def test_v2_speed_scale_is_clamped_more_conservatively_than_v1():
    catalog = _catalog_with(_v2_data())
    client = FakePepperClient()
    result = catalog.play(client, "test_gesture", speed_scale=100.0)
    # bei speed_scale=1.5 (Deckel) wird 1.0s Original-Zeit zu 1.0/1.5s
    assert result.plan[-1]["time_from_start_s"] == pytest.approx(1.0 / 1.5)
