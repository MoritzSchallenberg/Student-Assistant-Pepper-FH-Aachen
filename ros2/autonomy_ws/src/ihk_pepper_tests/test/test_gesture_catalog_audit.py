"""
Tests fuer gesture_catalog_audit.py (Entwicklungsauftrag 04-B, AP8,
Commit 11/14): deterministische Katalogpruefung + Spiegelpaarpruefung.
"""
import os

import pytest
import yaml

from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_bridge.gesture_catalog_audit import (
    MANDATORY_SYSTEM_ONLY_GESTURES,
    audit_catalog,
    check_mirror_pair,
    render_audit_report,
    render_inventory_markdown,
)


def _write_yaml(directory, name, data):
    data.setdefault("name", name)
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


def _v2(keyframes, **overrides):
    data = {
        "schema_version": 2,
        "keyframes": keyframes,
        "tested_status": "draft",
        "max_duration_s": 5.0,
    }
    data.update(overrides)
    return data


# ---- Spiegelpaarpruefung ----

def test_check_mirror_pair_accepts_correctly_mirrored_gestures(tmp_path):
    _write_yaml(tmp_path, "wave_left", _v2([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": -1.0, "LElbowYaw": -0.6}},
        {"time_from_start_s": 0.4, "joints": {"LElbowYaw": -1.6}},
    ]))
    _write_yaml(tmp_path, "wave_right", _v2([
        {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": -1.0, "RElbowYaw": 0.6}},
        {"time_from_start_s": 0.4, "joints": {"RElbowYaw": 1.6}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    errors = check_mirror_pair(
        "wave_left", catalog.get("wave_left"), "wave_right", catalog.get("wave_right"))
    assert errors == []


def test_check_mirror_pair_rejects_a_mismatched_sign(tmp_path):
    _write_yaml(tmp_path, "wave_left", _v2([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": -1.0}},
    ]))
    _write_yaml(tmp_path, "wave_right", _v2([
        # RShoulderPitch sollte IDENTISCH sein (Pitch-Gelenk) -- hier
        # absichtlich falsch vorzeichenverkehrt.
        {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": 1.0}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    errors = check_mirror_pair(
        "wave_left", catalog.get("wave_left"), "wave_right", catalog.get("wave_right"))
    assert len(errors) == 1
    assert "identisch" in errors[0]


def test_check_mirror_pair_rejects_a_non_flipped_roll_value(tmp_path):
    # LShoulderRoll ist bei Pepper strukturell NUR positiv, RShoulderRoll
    # NUR negativ (siehe joint_limits.py) -- ein wirklich GLEICHES
    # Vorzeichen waere also gar nicht ladbar. Der Abweichungsfall wird
    # deshalb ueber eine falsche BETRAGS-Spiegelung geprueft (0.6 vs.
    # -0.3 statt der erwarteten -0.6) -- gleiches Prinzip, ladbare Werte.
    _write_yaml(tmp_path, "explain_left", _v2([
        {"time_from_start_s": 0.0, "joints": {"LShoulderRoll": 0.6}},
    ]))
    _write_yaml(tmp_path, "explain_right", _v2([
        {"time_from_start_s": 0.0, "joints": {"RShoulderRoll": -0.3}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    errors = check_mirror_pair(
        "explain_left", catalog.get("explain_left"), "explain_right", catalog.get("explain_right"))
    assert len(errors) == 1
    assert "vorzeichengespiegelt" in errors[0]


def test_check_mirror_pair_rejects_mismatched_joint_sets(tmp_path):
    _write_yaml(tmp_path, "wave_left", _v2([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": -1.0, "LElbowRoll": -0.5}},
    ]))
    _write_yaml(tmp_path, "wave_right", _v2([
        {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": -1.0}},  # RElbowRoll fehlt
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    errors = check_mirror_pair(
        "wave_left", catalog.get("wave_left"), "wave_right", catalog.get("wave_right"))
    assert len(errors) == 1
    assert "Gelenkmenge" in errors[0]


def test_check_mirror_pair_rejects_mismatched_time_axes(tmp_path):
    _write_yaml(tmp_path, "wave_left", _v2([
        {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": -1.0}},
        {"time_from_start_s": 0.5, "joints": {"LShoulderPitch": 0.0}},
    ]))
    _write_yaml(tmp_path, "wave_right", _v2([
        {"time_from_start_s": 0.0, "joints": {"RShoulderPitch": -1.0}},
        {"time_from_start_s": 0.6, "joints": {"RShoulderPitch": 0.0}},  # andere Zeit
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    errors = check_mirror_pair(
        "wave_left", catalog.get("wave_left"), "wave_right", catalog.get("wave_right"))
    assert len(errors) == 1
    assert "Zeitachsen" in errors[0]


def test_check_mirror_pair_requires_shared_joints_to_be_identical(tmp_path):
    _write_yaml(tmp_path, "explain_left", _v2([
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.1, "LShoulderRoll": 0.6}},
    ]))
    _write_yaml(tmp_path, "explain_right", _v2([
        # HeadPitch ist ein gemeinsames (nicht bilaterales) Gelenk --
        # muss identisch sein, nicht gespiegelt.
        {"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.2, "RShoulderRoll": -0.6}},
    ]))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    errors = check_mirror_pair(
        "explain_left", catalog.get("explain_left"), "explain_right", catalog.get("explain_right"))
    assert len(errors) == 1
    assert "gemeinsames Gelenk" in errors[0]


# ---- audit_catalog() ----

def _selectable_gesture(**overrides):
    data = _v2(
        [{"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.1}},
         {"time_from_start_s": 0.5, "joints": {"HeadPitch": 0.0}}],
        description="Ein Testgestentext.", semantic_tags=["testing"],
        selectable_by_llm=True,
    )
    data.update(overrides)
    return data


def test_audit_catalog_reports_zero_errors_for_a_clean_catalog(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _selectable_gesture())
    catalog = GestureCatalog(str(tmp_path))
    errors = catalog.reload()
    assert errors == []
    result = audit_catalog(catalog, load_errors=errors)
    assert result.error_count == 0
    assert len(result.entries) == 1


def test_audit_catalog_flags_a_missing_mandatory_system_only_gesture(tmp_path):
    for name in MANDATORY_SYSTEM_ONLY_GESTURES:
        _write_yaml(tmp_path, name, _v2(
            [{"time_from_start_s": 0.0, "joints": {"HeadPitch": 0.0}}],
            description=f"{name} Testbeschreibung.",
            system_only=False, selectable_by_llm=False,  # FALSCH -- muss system_only=true sein
        ))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    result = audit_catalog(catalog)
    assert result.error_count == len(MANDATORY_SYSTEM_ONLY_GESTURES)
    for entry in result.entries:
        assert any(level == "error" and "verbindlich eine Systemgeste" in msg
                   for level, msg in entry.messages)


def test_audit_catalog_flags_duplicate_descriptions_as_a_warning(tmp_path):
    _write_yaml(tmp_path, "gesture_a", _selectable_gesture(description="Dieselbe Beschreibung."))
    _write_yaml(tmp_path, "gesture_b", _selectable_gesture(description="Dieselbe Beschreibung."))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    result = audit_catalog(catalog)
    assert result.error_count == 0
    assert result.warning_count >= 1
    assert any("identisch zu" in msg for e in result.entries for _, msg in e.messages)


def test_audit_catalog_flags_a_suspicious_command_pattern_in_test_note(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _selectable_gesture(
        test_note="Getestet ueber `ssh pepper@10.0.0.1` und qicli run wave."))
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    result = audit_catalog(catalog)
    assert result.error_count == 0
    assert any("Hardware-/Shell-Befehl" in msg for e in result.entries for _, msg in e.messages)


def test_audit_catalog_flags_a_v1_gesture_with_a_warning(tmp_path):
    _write_yaml(tmp_path, "legacy_seq", {
        "steps": [{"joint": "HeadYaw", "angle": 0.1, "duration": 1.0}],
        "description": "Alte v1-Geste.",
    })
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    result = audit_catalog(catalog)
    assert result.error_count == 0
    assert any("v1-Gesteneintrag" in msg for e in result.entries for _, msg in e.messages)


def test_audit_catalog_flags_a_gesture_still_using_legacy_metadata_fallback(tmp_path):
    data = _selectable_gesture(selectable_by_llm=False)
    data["metadata"] = {"system_only": True, "selectable_by_llm": False}
    data["system_only"] = True
    _write_yaml(tmp_path, "some_gesture", data)
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    result = audit_catalog(catalog)
    assert any("Legacy-metadata-Fallback" in msg for e in result.entries for _, msg in e.messages)


def test_audit_catalog_counts_load_errors_and_reports_them_as_errors(tmp_path):
    # eine Datei, deren Name NICHT zum Gestennamen passt -- wird von
    # GestureCatalog.reload() als Ladefehler gemeldet.
    _write_yaml(tmp_path, "mismatched_file", _selectable_gesture())
    with open(os.path.join(str(tmp_path), "mismatched_file.yaml")) as f:
        data = yaml.safe_load(f)
    data["name"] = "different_name"
    with open(os.path.join(str(tmp_path), "mismatched_file.yaml"), "w") as f:
        yaml.safe_dump(data, f)

    catalog = GestureCatalog(str(tmp_path))
    errors = catalog.reload()
    assert len(errors) == 1
    result = audit_catalog(catalog, load_errors=errors)
    assert result.error_count == 1
    assert len(result.entries) == 0


# ---- Renderer: deterministisch, sortiert, keine absoluten Pfade ----

def test_render_audit_report_is_alphabetically_sorted_and_deterministic(tmp_path):
    _write_yaml(tmp_path, "zzz_last", _selectable_gesture())
    _write_yaml(tmp_path, "aaa_first", _selectable_gesture())
    catalog = GestureCatalog(str(tmp_path))
    errors = catalog.reload()
    result_1 = audit_catalog(catalog, load_errors=errors)
    result_2 = audit_catalog(catalog, load_errors=errors)
    report_1 = render_audit_report(result_1)
    report_2 = render_audit_report(result_2)
    assert report_1 == report_2  # deterministisch
    assert report_1.index("aaa_first") < report_1.index("zzz_last")
    assert str(tmp_path) not in report_1  # kein absoluter Entwicklerpfad


def test_render_inventory_markdown_has_no_hardcoded_count_and_marks_generated(tmp_path):
    _write_yaml(tmp_path, "some_gesture", _selectable_gesture())
    catalog = GestureCatalog(str(tmp_path))
    errors = catalog.reload()
    result = audit_catalog(catalog, load_errors=errors)
    markdown = render_inventory_markdown(result)
    assert "automatisch erzeugt" in markdown.lower()
    assert "some_gesture" in markdown
    assert str(tmp_path) not in markdown
