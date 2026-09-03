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
        self._fail_on = fail_on  # z.B. "set_angle" oder "play_trajectory" -- simuliert Abbruch/Cancel

    def set_breathing(self, enabled, part=None):
        self.breathing_calls.append((enabled, part))

    def snapshot_joints(self, joints):
        self.snapshot_taken = list(joints)
        return {"snapshot": True}

    def restore_joints(self, snapshot, duration=1.5):
        self.restored = snapshot

    def set_angle(self, joint, angle, duration=1.0):
        if self._fail_on == "set_angle":
            raise RuntimeError("simulierter Abbruch")
        self.calls.append(("set_angle", joint, angle, duration))

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        if self._fail_on == "play_trajectory":
            raise RuntimeError("simulierter Abbruch")
        self.calls.append(("play_trajectory", joint_names, angle_lists, time_lists))


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
        "keyframes": keyframes or [
            {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.5, "RShoulderPitch": 0.5}},
            {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.0, "RShoulderPitch": 0.0}},
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
    assert client.restored == {"snapshot": True}
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
        assert client.restored == {"snapshot": True}
        assert (True, "Arms") in client.breathing_calls


# ---- Speed-Scale-Grenzen ----

def test_v2_speed_scale_is_clamped_more_conservatively_than_v1():
    catalog = _catalog_with(_v2_data())
    client = FakePepperClient()
    result = catalog.play(client, "test_gesture", speed_scale=100.0)
    # bei speed_scale=1.5 (Deckel) wird 1.0s Original-Zeit zu 1.0/1.5s
    assert result.plan[-1]["time_from_start_s"] == pytest.approx(1.0 / 1.5)
