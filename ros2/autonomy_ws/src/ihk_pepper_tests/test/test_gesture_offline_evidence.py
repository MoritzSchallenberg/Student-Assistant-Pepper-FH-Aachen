"""
Tests fuer gesture_offline_evidence.py (Entwicklungsauftrag 04-B,
AP8.7, Commit 12/14): vollstaendig offline reproduzierbarer
Evidenzreport.
"""
import json
import os

import pytest
import yaml

from ihk_pepper_bridge.gesture_catalog import Gesture, GestureCatalog
from ihk_pepper_bridge.gesture_offline_evidence import (
    LEGACY_V1_REASON,
    REPORT_SCHEMA_VERSION,
    serialize_report,
    verdict_to_exitcode,
    verify_gesture_offline,
    write_report_atomically,
)
from ihk_pepper_bridge.kinematic_compiler import NEUTRAL_STAND_POSE
from ihk_pepper_bridge.trajectory_safety import JointAndTimingValidator, TrajectorySafetyValidator


class _TestDoubleFakeCollisionProofBackend:
    """AUSDRUECKLICH ein TEST-DOUBLE, KEIN echtes Kollisions-Backend
    (gleiches Muster wie test_bridge_node_actuator_arbiter.py) -- nutzt
    dieselbe Klasse NICHT importiert, um dieses Testmodul unabhaengig zu
    halten."""

    name = "test_double_collision_proof"

    def check(self, gesture, plan, start_pose, compile_error):
        from ihk_pepper_bridge.trajectory_safety import TrajectorySafetyReport
        if compile_error:
            return TrajectorySafetyReport(gesture_name=gesture.name, verdict="fail",
                                          backend_names=[self.name])
        return TrajectorySafetyReport(
            gesture_name=gesture.name, verdict="pass", backend_names=[self.name],
            collision_checked=True, collision_backend_note="TEST-DOUBLE, kein echtes Backend.",
        )


def _write_yaml(directory, name, data):
    data.setdefault("name", name)
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


def _v2_data(**overrides):
    data = {
        "schema_version": 2,
        "description": "Testgeste.",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.0}},
            {"time_from_start_s": 0.5, "joints": {"HeadPitch": 0.1}},
        ],
        "tested_status": "draft",
        "max_duration_s": 5.0,
    }
    data.update(overrides)
    return data


def test_verify_offline_a_clean_v2_gesture_is_inconclusive_with_disabled_backend(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report = verify_gesture_offline(gesture, gesture.source_path)
    assert report["overall_verdict"] == "inconclusive"
    assert report["checks"]["collision_checked"] is False
    assert report["checks"]["joint_and_timing"] == "pass"
    assert report["errors"] == []


def test_verify_offline_with_a_real_collision_proof_test_double_yields_pass(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    validator = TrajectorySafetyValidator(
        backends=[JointAndTimingValidator(), _TestDoubleFakeCollisionProofBackend()])
    report = verify_gesture_offline(gesture, gesture.source_path, safety_validator=validator)
    assert report["overall_verdict"] == "pass"
    assert report["checks"]["collision_checked"] is True
    assert report["checks"]["collision_backend"] == "test_double_collision_proof"


def test_verify_offline_a_broken_trajectory_yields_fail(tmp_path):
    # Zeitachse nicht monoton -> Compilerfehler.
    _write_yaml(tmp_path, "broken_gesture", _v2_data(keyframes=[
        {"time_from_start_s": 0.5, "joints": {"HeadPitch": 0.0}},
        {"time_from_start_s": 0.5, "joints": {"HeadPitch": 0.1}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    # Diese Datei ist bereits beim Laden ungueltig (GestureCatalog validiert
    # Zeitachsen schon in Gesture._validate_v2()) -- die Gegenprobe fuer
    # einen erst beim KOMPILIEREN scheiternden Fall folgt separat unten.
    errors = catalog.reload()
    assert errors != []


def test_verify_offline_a_gesture_that_fails_only_at_compile_time_yields_fail(tmp_path):
    # Ein Plan, der zur Laufzeit (Startpose-Uebergang) scheitert, aber
    # beim reinen YAML-Laden noch nicht abgelehnt wird: eine Startpose,
    # die (bei t=0.0, also dt=0) einen unendlichen Sprung zum ersten
    # Keyframe erzwingt -- beide Einzelwerte (0.3 und -0.6) liegen fuer
    # sich genommen innerhalb der HeadPitch-Grenzen, nur der UEBERGANG
    # bei dt=0 ist ungueltig.
    _write_yaml(tmp_path, "jumpy_gesture", _v2_data(keyframes=[
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.3}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("jumpy_gesture")
    bad_start_pose = dict(NEUTRAL_STAND_POSE)
    bad_start_pose["HeadPitch"] = -0.6  # weit entfernt vom ersten Keyframe (0.3) bei t=0.0
    report = verify_gesture_offline(gesture, gesture.source_path, explicit_start_pose=bad_start_pose)
    assert report["overall_verdict"] == "fail"
    assert report["errors"] != []


def test_verify_offline_t_pose_style_v1_gesture_is_inconclusive_with_legacy_reason(tmp_path):
    _write_yaml(tmp_path, "legacy_seq", {
        "description": "Alte v1-Geste.",
        "steps": [{"joint": "HeadYaw", "angle": 0.1, "duration": 1.0}],
        "tested_status": "live_validated", "tested_date": "2026-01-01",
        "test_note": "Live getestet (Test-Fixture).",
        "max_duration_s": 5.0,
    })
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("legacy_seq")
    report = verify_gesture_offline(gesture, gesture.source_path)
    assert report["overall_verdict"] == "inconclusive"
    assert LEGACY_V1_REASON in report["requires_manual_review"]
    assert report["gesture"]["schema_version"] == 1
    # Keine vorgetaeuschte v2-Kompilierung:
    assert report["trajectory"]["plan_fingerprint"] == ""
    assert report["inputs"]["start_pose_source"] == "not_applicable_v1"


def test_verify_offline_never_changes_the_yaml_file_or_tested_status(tmp_path):
    path = _write_yaml(tmp_path, "some_gesture", _v2_data())
    with open(path) as f:
        original_content = f.read()
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    verify_gesture_offline(gesture, gesture.source_path)
    with open(path) as f:
        assert f.read() == original_content
    assert gesture.tested_status == "draft"  # unveraendert im Speicher


def test_verify_offline_source_sha256_changes_when_file_content_changes(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report_1 = verify_gesture_offline(gesture, gesture.source_path)

    _write_yaml(tmp_path, "some_gesture", _v2_data(description="Andere Beschreibung."))
    catalog.reload()
    gesture_2 = catalog.get("some_gesture")
    report_2 = verify_gesture_offline(gesture_2, gesture_2.source_path)

    assert report_1["gesture"]["source_sha256"] != report_2["gesture"]["source_sha256"]


def test_verify_offline_compiler_version_and_git_context_are_present(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report = verify_gesture_offline(gesture, gesture.source_path)
    assert report["toolchain"]["compiler_version"]
    assert report["toolchain"]["repository_commit"]  # entweder ein echter Hash oder 'unavailable'


def test_verify_offline_reports_unavailable_git_context_honestly_outside_a_repo(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report = verify_gesture_offline(gesture, gesture.source_path, repo_dir=str(tmp_path))
    assert report["toolchain"]["repository_commit"] == "unavailable"
    assert report["toolchain"]["working_tree_dirty"] == "unavailable"
    assert any("Kein Git-Kontext" in w for w in report["warnings"])


def test_verify_offline_start_pose_source_is_explicit_when_provided(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    start_pose = {"HeadPitch": 0.0}
    report = verify_gesture_offline(gesture, gesture.source_path, explicit_start_pose=start_pose)
    assert report["inputs"]["start_pose_source"] == "explicit"


def test_verify_offline_start_pose_source_is_captured_metadata_when_available(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    captured_start_pose = {"HeadPitch": 0.0}
    report = verify_gesture_offline(gesture, gesture.source_path, captured_start_pose=captured_start_pose)
    assert report["inputs"]["start_pose_source"] == "captured_metadata"


def test_verify_offline_start_pose_source_falls_back_to_neutral_stand_pose(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report = verify_gesture_offline(gesture, gesture.source_path)
    assert report["inputs"]["start_pose_source"] == "neutral_stand_pose"


def test_verify_offline_rejects_an_incomplete_explicit_start_pose(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data(keyframes=[
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.0, "HeadYaw": 0.0}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    incomplete_start_pose = {"HeadPitch": 0.0}  # HeadYaw fehlt
    report = verify_gesture_offline(gesture, gesture.source_path, explicit_start_pose=incomplete_start_pose)
    assert report["overall_verdict"] == "fail"
    assert any("fehlende Gelenke" in e for e in report["errors"])


def test_verify_offline_affected_resources_are_derived_canonically(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data(keyframes=[
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.0}},
        {"time_from_start_s": 0.5, "joints": {"LShoulderPitch": 0.1}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report = verify_gesture_offline(gesture, gesture.source_path)
    assert report["trajectory"]["affected_resources"] == ["LEFT_ARM"]


def test_verdict_to_exitcode_matches_the_documented_three_way_scheme():
    assert verdict_to_exitcode("pass") == 0
    assert verdict_to_exitcode("fail") == 1
    assert verdict_to_exitcode("inconclusive") == 2


def test_serialize_report_has_sorted_keys_and_rejects_nan(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _v2_data())
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    gesture = catalog.get("some_gesture")
    report = verify_gesture_offline(gesture, gesture.source_path)
    text = serialize_report(report)
    parsed = json.loads(text)  # muss gueltiges JSON sein
    assert parsed["report_schema_version"] == REPORT_SCHEMA_VERSION
    assert "NaN" not in text
    assert "Infinity" not in text
    # json.loads() erhaelt die Reihenfolge der Schluessel EXAKT wie im
    # Text -- bei sort_keys=True beim Schreiben also die sortierte
    # Reihenfolge, auf jeder Verschachtelungsebene.
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert list(parsed["gesture"].keys()) == sorted(parsed["gesture"].keys())
    assert list(parsed["checks"].keys()) == sorted(parsed["checks"].keys())


def test_serialize_report_raises_instead_of_emitting_invalid_json_for_nan():
    report = {"broken": float("nan")}
    with pytest.raises(ValueError):
        serialize_report(report)


def test_write_report_atomically_never_overwrites_an_existing_report(tmp_path):
    target = str(tmp_path / "report.json")
    write_report_atomically(target, {"a": 1})
    with pytest.raises(ValueError, match="existiert bereits"):
        write_report_atomically(target, {"a": 2})
    with open(target) as f:
        assert json.load(f) == {"a": 1}
