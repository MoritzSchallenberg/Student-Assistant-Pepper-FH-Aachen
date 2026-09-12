"""
Tests fuer gesture_capture.py (Entwicklungsauftrag 04-B, AP8.7,
Commit 12/14): Gelenkargument-Haertung, rein lesende Mehrpunkt-Aufnahme,
Kandidatendateiformat, atomares Schreiben.
"""
import os

import pytest

from ihk_pepper_bridge.gesture_capture import (
    CAPTURE_MAX_DURATION_MARGIN_S,
    CAPTURE_SPEED_SCALE_DEFAULT,
    GestureCaptureError,
    MAX_CAPTURE_SAMPLE_COUNT,
    atomic_create_exclusive,
    build_candidate_gesture_data,
    capture_sequence,
    derive_name_from_output_path,
    parse_and_validate_joint_list,
    validate_safe_gesture_name,
)
from ihk_pepper_bridge.gesture_catalog import Gesture
from ihk_pepper_bridge.joint_state_source import JointStateReading
from ihk_pepper_bridge.kinematic_compiler import KinematicCompiler


# ---- Gelenkargument-Haertung (Abschnitt 4.2/16.1) ----

def test_parse_valid_single_joint():
    assert parse_and_validate_joint_list("HeadYaw") == ["HeadYaw"]


def test_parse_valid_multi_joint_is_sorted_deterministically():
    assert parse_and_validate_joint_list("HeadPitch,HeadYaw") == ["HeadPitch", "HeadYaw"]
    assert parse_and_validate_joint_list("HeadYaw,HeadPitch") == ["HeadPitch", "HeadYaw"]


def test_parse_strips_whitespace_around_joint_names():
    assert parse_and_validate_joint_list(" HeadYaw , HeadPitch ") == ["HeadPitch", "HeadYaw"]


def test_parse_rejects_unknown_joint():
    with pytest.raises(GestureCaptureError, match="nicht freigegeben"):
        parse_and_validate_joint_list("NotAJoint")


def test_parse_rejects_duplicate_joint():
    with pytest.raises(GestureCaptureError, match="doppelt"):
        parse_and_validate_joint_list("HeadYaw,HeadYaw")


def test_parse_rejects_empty_element():
    with pytest.raises(GestureCaptureError, match="leeres Element"):
        parse_and_validate_joint_list("HeadYaw,,HeadPitch")


def test_parse_rejects_whitespace_only_input():
    with pytest.raises(GestureCaptureError):
        parse_and_validate_joint_list("   ")


def test_parse_rejects_none_input():
    with pytest.raises(GestureCaptureError):
        parse_and_validate_joint_list(None)


def test_parse_rejects_shell_special_characters():
    for injected in ("HeadYaw; rm -rf /", "HeadYaw`whoami`", "HeadYaw && echo hi", "$(reboot)"):
        with pytest.raises(GestureCaptureError):
            parse_and_validate_joint_list(injected)


def test_parse_rejects_a_chain_name_instead_of_a_joint():
    for chain_name in ("Body", "Head", "Arms", "LArm", "RArm"):
        with pytest.raises(GestureCaptureError):
            parse_and_validate_joint_list(chain_name)


# ---- sicherer Gestenname ----

def test_derive_name_from_output_path_strips_yaml_suffix():
    assert derive_name_from_output_path("/tmp/my_capture.yaml") == "my_capture"


def test_validate_safe_gesture_name_rejects_uppercase():
    with pytest.raises(GestureCaptureError):
        validate_safe_gesture_name("MyCapture")


def test_validate_safe_gesture_name_rejects_special_characters():
    with pytest.raises(GestureCaptureError):
        validate_safe_gesture_name("my-capture; rm -rf /")


def test_validate_safe_gesture_name_accepts_a_conventional_name():
    assert validate_safe_gesture_name("my_capture_2") == "my_capture_2"


# ---- capture_sequence() Kernschleife ----

class _MockJointStateSource:
    """Test-Double (Abschnitt 1: 'ausschliesslich mit Test-Doubles
    geprueft') -- liefert eine vorgegebene Folge von Messwerten mit
    einer INJIZIERTEN, deterministischen Fake-Uhr statt echter Zeit."""

    def __init__(self, values_sequence, step_s=0.5, acquisition_mode="sequential_per_joint",
                acquisition_span_s=0.001):
        self._seq = iter(values_sequence)
        self.t = 0.0
        self._step_s = step_s
        self._mode = acquisition_mode
        self._span_s = acquisition_span_s
        self.read_calls = 0

    def read(self, joints):
        self.read_calls += 1
        values = next(self._seq)
        started = self.t
        self.t += self._step_s
        return JointStateReading(
            values=dict(values), acquisition_started_monotonic_s=started,
            acquisition_finished_monotonic_s=started + self._span_s,
            source_backend="test_double_mock", acquisition_mode=self._mode,
        )


def _two_joint_samples(n, joint_a="HeadPitch", joint_b="HeadYaw"):
    return [{joint_a: 0.05 * i, joint_b: 0.0} for i in range(n)]


def test_capture_sequence_produces_a_monotone_relative_time_axis():
    source = _MockJointStateSource(_two_joint_samples(3), step_s=0.5)
    result = capture_sequence(
        source, ["HeadPitch", "HeadYaw"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)
    times = [kf["time_from_start_s"] for kf in result.keyframes]
    assert times == [0.0, 0.5, 1.0]
    assert times == sorted(times)
    assert len(set(times)) == len(times)


def test_capture_sequence_reports_requested_vs_achieved_sample_rate_separately():
    source = _MockJointStateSource(_two_joint_samples(3), step_s=0.5)
    result = capture_sequence(
        source, ["HeadPitch", "HeadYaw"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)
    assert result.requested_sample_rate_hz == 2.0
    assert result.achieved_sample_rate_hz == pytest.approx(2.0)


def test_capture_sequence_documents_actual_duration_and_sample_span():
    source = _MockJointStateSource(_two_joint_samples(3), step_s=0.5, acquisition_span_s=0.02)
    result = capture_sequence(
        source, ["HeadPitch", "HeadYaw"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)
    assert result.actual_duration_s == pytest.approx(1.0)
    assert result.maximum_sample_span_s == pytest.approx(0.02)


def test_capture_sequence_labels_sequential_source_honestly():
    source = _MockJointStateSource(_two_joint_samples(3), step_s=0.5)
    result = capture_sequence(
        source, ["HeadPitch", "HeadYaw"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)
    assert result.acquisition_mode == "sequential_per_joint"
    assert result.source_backend == "test_double_mock"


def test_capture_sequence_requires_at_least_two_samples():
    # duration_s ist so kurz, dass nach dem ERSTEN Sample bereits
    # elapsed >= duration_s waere -- die Schleife MUSS trotzdem ein
    # zweites Sample verlangen.
    source = _MockJointStateSource(_two_joint_samples(2), step_s=0.5)
    result = capture_sequence(
        source, ["HeadPitch", "HeadYaw"], duration_s=0.01, sample_rate_hz=100.0, sleep_fn=lambda s: None)
    assert result.sample_count >= 2


def test_capture_sequence_fails_closed_on_missing_joint():
    source = _MockJointStateSource([{"HeadPitch": 0.0}, {"HeadPitch": 0.0}], step_s=0.5)
    with pytest.raises(GestureCaptureError, match="fehlt in der Messung"):
        capture_sequence(source, ["HeadPitch", "HeadYaw"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_fails_closed_on_none_value():
    source = _MockJointStateSource(
        [{"HeadPitch": 0.0}, {"HeadPitch": None}], step_s=0.5)
    with pytest.raises(GestureCaptureError, match="None"):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_fails_closed_on_nan_value():
    source = _MockJointStateSource(
        [{"HeadPitch": 0.0}, {"HeadPitch": float("nan")}], step_s=0.5)
    with pytest.raises(GestureCaptureError, match="NaN/inf"):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_fails_closed_on_inf_value():
    source = _MockJointStateSource(
        [{"HeadPitch": 0.0}, {"HeadPitch": float("inf")}], step_s=0.5)
    with pytest.raises(GestureCaptureError, match="NaN/inf"):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_fails_closed_on_non_numeric_value():
    source = _MockJointStateSource(
        [{"HeadPitch": 0.0}, {"HeadPitch": "not_a_number"}], step_s=0.5)
    with pytest.raises(GestureCaptureError, match="nicht-numerischen"):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_fails_closed_on_out_of_bounds_angle():
    # HeadPitch-Grenze ist (-0.7068, 0.4451) mit 0.05 Marge -- 10.0 ist
    # weit ausserhalb.
    source = _MockJointStateSource([{"HeadPitch": 0.0}, {"HeadPitch": 10.0}], step_s=0.5)
    with pytest.raises(GestureCaptureError):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_fails_closed_on_a_connection_error():
    class _BrokenSource:
        def read(self, joints):
            raise ConnectionError("SSH-Verbindung verloren (simuliert)")

    with pytest.raises(ConnectionError):
        capture_sequence(_BrokenSource(), ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_propagates_keyboard_interrupt():
    class _InterruptedSource:
        def read(self, joints):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        capture_sequence(_InterruptedSource(), ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_capture_sequence_rejects_non_positive_duration():
    source = _MockJointStateSource(_two_joint_samples(3))
    with pytest.raises(GestureCaptureError, match="duration_s"):
        capture_sequence(source, ["HeadPitch"], duration_s=0.0, sample_rate_hz=2.0)
    with pytest.raises(GestureCaptureError, match="duration_s"):
        capture_sequence(source, ["HeadPitch"], duration_s=float("nan"), sample_rate_hz=2.0)


def test_capture_sequence_rejects_non_positive_sample_rate():
    source = _MockJointStateSource(_two_joint_samples(3))
    with pytest.raises(GestureCaptureError, match="sample_rate_hz"):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=0.0)
    with pytest.raises(GestureCaptureError, match="sample_rate_hz"):
        capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=float("inf"))


def test_capture_sequence_rejects_an_excessive_sample_count():
    source = _MockJointStateSource(_two_joint_samples(3))
    with pytest.raises(GestureCaptureError, match="Obergrenze"):
        capture_sequence(source, ["HeadPitch"], duration_s=100.0, sample_rate_hz=1000.0)


def test_capture_sequence_never_smooths_interpolates_or_invents_samples():
    # Die zurueckgegebenen Keyframe-Winkel sind EXAKT die vom Test-Double
    # gelieferten Werte -- keine Glaettung/Interpolation dazwischen.
    samples = [{"HeadPitch": 0.0}, {"HeadPitch": 0.37}, {"HeadPitch": 0.12}]
    source = _MockJointStateSource(samples, step_s=0.5)
    result = capture_sequence(source, ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)
    recorded = [kf["joints"]["HeadPitch"] for kf in result.keyframes]
    assert recorded == [0.0, 0.37, 0.12]


def test_capture_sequence_rejects_non_strictly_monotone_time():
    class _TiedTimeSource:
        def __init__(self):
            self.calls = 0

        def read(self, joints):
            self.calls += 1
            # Liefert bei jedem Aufruf dieselbe Startzeit -- simuliert
            # einen Uhr-/Rundungsfehler, der Zeitgleichheit erzeugen
            # wuerde.
            return JointStateReading(
                values={"HeadPitch": 0.01 * self.calls},
                acquisition_started_monotonic_s=5.0,
                acquisition_finished_monotonic_s=5.001,
                source_backend="test_double_mock", acquisition_mode="sequential_per_joint",
            )

    with pytest.raises(GestureCaptureError, match="streng monoton"):
        capture_sequence(
            _TiedTimeSource(), ["HeadPitch"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


# ---- Kandidatendateiformat (Abschnitt 8/16.4) ----

def _capture_result_fixture():
    source = _MockJointStateSource(_two_joint_samples(3), step_s=0.5)
    return capture_sequence(
        source, ["HeadPitch", "HeadYaw"], duration_s=1.0, sample_rate_hz=2.0, sleep_fn=lambda s: None)


def test_candidate_has_safe_defaults():
    result = _capture_result_fixture()
    data = build_candidate_gesture_data("my_capture", result)
    assert data["schema_version"] == 2
    assert data["name"] == "my_capture"
    assert data["tested_status"] == "draft"
    assert data["tested_date"] is None
    assert data["selectable_by_llm"] is False
    assert data["system_only"] is False
    assert data["requires_stationary"] is True
    assert data["allowed_interaction_states"] == ["IDLE"]
    assert data["on_cancel"] == "hold"
    assert data["disable_breathing"] == []
    assert data["speed_scale_default"] == CAPTURE_SPEED_SCALE_DEFAULT


def test_candidate_max_duration_s_derived_from_scaled_time_axis_not_raw():
    result = _capture_result_fixture()
    data = build_candidate_gesture_data("my_capture", result)
    raw_last_time = result.keyframes[-1]["time_from_start_s"]
    expected = round(raw_last_time / CAPTURE_SPEED_SCALE_DEFAULT + CAPTURE_MAX_DURATION_MARGIN_S, 3)
    assert data["max_duration_s"] == expected
    # nicht einfach die unskalierte Zeitachse selbst:
    assert data["max_duration_s"] != raw_last_time


def test_candidate_contains_full_capture_metadata_without_personal_data():
    result = _capture_result_fixture()
    data = build_candidate_gesture_data("my_capture", result)
    capture_meta = data["metadata"]["capture"]
    for key in (
        "schema_version", "source_backend", "acquisition_mode", "captured_at_utc", "time_base",
        "requested_sample_rate_hz", "achieved_sample_rate_hz", "requested_duration_s",
        "actual_duration_s", "sample_count", "joints", "maximum_sample_span_s",
        "hardware_validation", "start_pose", "start_pose_fingerprint",
    ):
        assert key in capture_meta
    assert capture_meta["hardware_validation"] == "hwverificationrequired"
    assert capture_meta["time_base"] == "monotonic"
    # Keine personenbezogenen Felder:
    dumped = str(data)
    for forbidden in ("operator", "user", "password", "token", "ssh_user", "hostname"):
        assert forbidden not in dumped.lower()


def test_candidate_reloads_via_gesture_catalog_and_compiles_with_capture_start_pose():
    result = _capture_result_fixture()
    data = build_candidate_gesture_data("my_capture", result)
    gesture = Gesture(dict(data), "my_capture.yaml")
    plan = KinematicCompiler().compile(
        gesture, speed_scale=gesture.speed_scale_default, start_pose=result.start_pose)
    assert plan.max_duration_s <= gesture.max_duration_s


def test_build_candidate_gesture_data_rejects_an_unsafe_name():
    result = _capture_result_fixture()
    with pytest.raises(GestureCaptureError):
        build_candidate_gesture_data("Not Safe!", result)


# ---- atomares Schreiben (Abschnitt 7.4/16.2) ----

def test_atomic_create_exclusive_writes_the_content(tmp_path):
    target = str(tmp_path / "candidate.yaml")
    atomic_create_exclusive(target, "hello: world\n")
    with open(target) as f:
        assert f.read() == "hello: world\n"


def test_atomic_create_exclusive_never_overwrites_an_existing_file(tmp_path):
    target = str(tmp_path / "candidate.yaml")
    with open(target, "w") as f:
        f.write("original\n")
    with pytest.raises(GestureCaptureError, match="existiert bereits"):
        atomic_create_exclusive(target, "new content\n")
    with open(target) as f:
        assert f.read() == "original\n"


def test_atomic_create_exclusive_leaves_no_temp_file_behind_on_conflict(tmp_path):
    target = str(tmp_path / "candidate.yaml")
    with open(target, "w") as f:
        f.write("original\n")
    with pytest.raises(GestureCaptureError):
        atomic_create_exclusive(target, "new content\n")
    remaining = os.listdir(str(tmp_path))
    assert remaining == ["candidate.yaml"]
