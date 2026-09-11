import os
import tempfile

import pytest
import yaml

from ihk_pepper_bridge import gesturectl


def _write_yaml(directory, name, data):
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


@pytest.fixture()
def gesture_dir():
    with tempfile.TemporaryDirectory() as d:
        _write_yaml(d, "seq", {
            "name": "seq",
            "steps": [{"joint": "HeadYaw", "angle": 0.1, "duration": 1.0}],
        })
        _write_yaml(d, "small_v2", {
            "schema_version": 2,
            "name": "small_v2",
            "keyframes": [{"time_from_start_s": 0.5, "joints": {"HeadPitch": 0.1}}],
        })
        yield d


def _run(gesture_dir, *argv):
    parser = gesturectl.build_parser()
    args = parser.parse_args(["--gesture-dir", gesture_dir, *argv])
    return args.func(args)


# ---- list/validate/show ----

def test_list_prints_both_gestures(gesture_dir, capsys):
    rc = _run(gesture_dir, "list")
    out = capsys.readouterr().out
    assert rc == 0
    assert "seq" in out
    assert "small_v2" in out


def test_validate_reports_compiler_ok_for_v2(gesture_dir, capsys):
    rc = _run(gesture_dir, "validate", "small_v2")
    out = capsys.readouterr().out
    assert rc == 0
    assert "Kinematik-Compiler OK" in out


def test_validate_unknown_gesture_returns_error(gesture_dir, capsys):
    rc = _run(gesture_dir, "validate", "does_not_exist")
    assert rc == 1


def test_show_prints_keyframes(gesture_dir, capsys):
    rc = _run(gesture_dir, "show", "small_v2")
    out = capsys.readouterr().out
    assert rc == 0
    assert "HeadPitch" in out


# ---- preview-trajectory (Entwicklungsauftrag 04-B, AP8.5/AP8.7) ----
# Braucht einen echten rclpy-Node (SimQicli) -- wie bei der bestehenden
# 'preview'-Unterkommando bewusst KEIN Funktionstest hier (kein
# rclpy.init() in der Unit-Test-Umgebung), nur die Parser-Registrierung.

def test_preview_trajectory_is_registered_with_speed_scale_option():
    parser = gesturectl.build_parser()
    args = parser.parse_args(["preview-trajectory", "small_v2", "--speed-scale", "0.5"])
    assert args.func is gesturectl.cmd_preview_trajectory
    assert args.name == "small_v2"
    assert args.speed_scale == 0.5


def test_preview_trajectory_rejects_v1_gesture_before_touching_sim_qicli(gesture_dir, capsys):
    # v1-Gesten haben keinen gemeinsamen TrajectoryPlan -- muss VOR jedem
    # sim_qicli-Import/rclpy-Zugriff ablehnen.
    rc = _run(gesture_dir, "preview-trajectory", "seq")
    assert rc == 1
    assert "schema_version 2" in capsys.readouterr().err


# ---- dry-run (darf NIE Hardware anfassen) ----

def test_dry_run_v1_never_touches_hardware(gesture_dir, capsys):
    rc = _run(gesture_dir, "dry-run", "seq")
    out = capsys.readouterr().out
    assert rc == 0
    assert "HeadYaw" in out


def test_dry_run_v2_uses_dry_run_transport(gesture_dir, capsys):
    # DryRunMotionTransport loggt zusaetzlich ueber logging (Ausgabestream
    # je nach Testumgebungs-Loggerkonfiguration nicht zuverlaessig von
    # capsys erfassbar, siehe test_motion_transport.py-Kommentar zum
    # gleichen Thema) -- hier reicht der Nachweis, dass der Befehl
    # erfolgreich durchlaeuft und NIE eine Hardwareaktion ausloest
    # (DryRunMotionTransport ruft ohnehin nie pepper_client an).
    rc = _run(gesture_dir, "dry-run", "small_v2")
    out = capsys.readouterr().out
    assert rc == 0
    assert "Status: done" in out


# ---- capture-pose / live-test: brechen ohne erreichbaren Pepper sofort ab ----

class _UnreachableClient:
    def is_reachable(self, timeout_s=2.0):
        return False


def test_capture_pose_aborts_without_reachable_pepper(gesture_dir, monkeypatch, capsys):
    monkeypatch.setattr("ihk_pepper_bridge.pepper_client.ThreadSafePepperClient", _UnreachableClient)
    rc = _run(gesture_dir, "capture-pose")
    err = capsys.readouterr().err
    assert rc == 1
    assert "nicht erreichbar" in err


def test_live_test_aborts_without_reachable_pepper(gesture_dir, monkeypatch, capsys):
    monkeypatch.setattr("ihk_pepper_bridge.pepper_client.ThreadSafePepperClient", _UnreachableClient)
    rc = _run(gesture_dir, "live-test", "small_v2")
    err = capsys.readouterr().err
    assert rc == 1
    assert "nicht erreichbar" in err


def test_live_test_rejects_v1_gesture(gesture_dir, monkeypatch, capsys):
    class _ReachableClient:
        def is_reachable(self, timeout_s=2.0):
            return True

    monkeypatch.setattr("ihk_pepper_bridge.pepper_client.ThreadSafePepperClient", _ReachableClient)
    rc = _run(gesture_dir, "live-test", "seq")
    err = capsys.readouterr().err
    assert rc == 1
    assert "nur fuer schema_version 2" in err


class _FakeActionClientNeverAvailable:
    """Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.11: live-test muss
    NACH der Checkliste die echte PlayGesture-Action ansprechen, statt
    KinematicCompiler/QicliTrajectoryTransport direkt aufzurufen -- diese
    Fake-ActionClient-Klasse simuliert eine (noch) nicht laufende Bridge,
    ohne echtes ROS2-Netzwerk-Warten (wait_for_server liefert sofort
    False statt den vollen Timeout auszureizen)."""

    def __init__(self, node, action_type, action_name):
        self.action_name = action_name

    def wait_for_server(self, timeout_sec=None):
        return False


def test_live_test_uses_the_playgesture_action_not_a_direct_transport_call(
    gesture_dir, monkeypatch, capsys
):
    class _ReachableClient:
        def is_reachable(self, timeout_s=2.0):
            return True

    monkeypatch.setattr("ihk_pepper_bridge.pepper_client.ThreadSafePepperClient", _ReachableClient)
    monkeypatch.setattr("builtins.input", lambda prompt="": "ja")
    import rclpy.action
    monkeypatch.setattr(rclpy.action, "ActionClient", _FakeActionClientNeverAvailable)

    # KinematicCompiler/QicliTrajectoryTransport duerfen von live-test NICHT
    # mehr direkt aufgerufen werden (Abschnitt 3.11) -- ein Fehlschlag hier
    # waere ein Rueckfall in den alten, umgangenen Codepfad.
    def _forbidden_compile(*a, **kw):
        raise AssertionError(
            "live-test darf KinematicCompiler NICHT mehr direkt aufrufen -- "
            "es muss die PlayGesture-Action der Bridge verwenden."
        )

    monkeypatch.setattr(
        "ihk_pepper_bridge.gesturectl.KinematicCompiler.compile", _forbidden_compile)

    rc = _run(gesture_dir, "live-test", "small_v2")
    err = capsys.readouterr().err
    assert rc == 1
    assert "play_gesture" in err
    assert "nicht erreichbar" in err


# ---- compare ----

def test_compare_two_gestures_prints_diff(gesture_dir, capsys):
    rc = _run(gesture_dir, "compare", "small_v2", "seq")
    out = capsys.readouterr().out
    assert rc == 0
    assert "HeadPitch" in out
    assert "HeadYaw" in out


def test_compare_without_second_gesture_needs_reachable_pepper(gesture_dir, monkeypatch, capsys):
    monkeypatch.setattr("ihk_pepper_bridge.pepper_client.ThreadSafePepperClient", _UnreachableClient)
    rc = _run(gesture_dir, "compare", "small_v2")
    err = capsys.readouterr().err
    assert rc == 1
    assert "nicht erreichbar" in err


# ---- Sicherheits-Grep: gesturectl.py selbst referenziert nie /cmd_vel ----

def test_gesturectl_module_never_references_cmd_vel():
    import inspect
    source = inspect.getsource(gesturectl)
    assert "cmd_vel" not in source
