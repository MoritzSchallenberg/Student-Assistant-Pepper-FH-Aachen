"""
Vollstaendig OFFLINE reproduzierbarer Evidenzreport fuer eine einzelne
Geste (Entwicklungsauftrag 04-B, AP8.7, Commit 12/14). Nutzt
AUSSCHLIESSLICH die bestehende kanonische Kette (GestureCatalog ->
kanonische Speed-Scale-Aufloesung -> KinematicCompiler ->
TrajectorySafetyValidator -> resources_for_gesture) -- KEINE zweite
Sicherheitslogik, kein Pepper-Client, kein Netzwerk, kein SSH/qicli,
keine ROS-Action, keine Dateiveraenderung ausser dem ausdruecklich
angeforderten JSON-Report.

Ein Report ist ein reproduzierbarer PRUEFDATENSATZ, KEINE kryptografisch
signierte Bescheinigung -- Dateihash und Commitbindung beweisen NICHT
allein die physische Sicherheit einer Bewegung (Abschnitt 10.3).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from typing import Optional

from ihk_pepper_interaction.resource_derivation import resources_for_gesture

from .gesture_catalog import GestureValidationError, validate_speed_scale
from .kinematic_compiler import (
    COMPILER_VERSION, KinematicCompileError, KinematicCompiler, NEUTRAL_STAND_POSE,
)
from .motion_transport import _fingerprint_start_pose
from .trajectory_safety import TrajectorySafetyValidator

REPORT_SCHEMA_VERSION = 1

# Entwicklungsauftrag 04-B, AP8.7, Abschnitt 10.5 (bestaetigter Fund):
# ein v1-Katalogeintrag hat weder einen synchronen Compiler-Pfad noch
# echte Mid-Flight-Cancel-Garantien -- verify-offline darf das NICHT als
# 'v2-validiert' vortaeuschen.
LEGACY_V1_REASON = "legacy_v1_not_safely_interruptible"


def _is_finite(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_git(args, repo_dir) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git"] + args, cwd=repo_dir, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_context(repo_dir: Optional[str], warnings: list) -> dict:
    """Ehrlich: 'unavailable' + Warnung statt einer erfundenen Commit-ID,
    wenn kein Git-Kontext gefunden wird (Abschnitt 10.3)."""
    commit = _run_git(["rev-parse", "HEAD"], repo_dir)
    if commit is None:
        warnings.append("Kein Git-Kontext gefunden -- repository_commit/working_tree_dirty sind 'unavailable'.")
        return {"repository_commit": "unavailable", "working_tree_dirty": "unavailable"}
    status = _run_git(["status", "--porcelain"], repo_dir)
    dirty = (status != "") if status is not None else "unavailable"
    return {"repository_commit": commit, "working_tree_dirty": dirty}


def _validate_full_start_pose(pose: dict, needed_joints, label: str) -> None:
    """Abschnitt 10.2: eine explizite/erfasste Startpose muss JEDES
    benoetigte Gelenk mit einem endlichen Wert enthalten -- KEIN
    Teil-Fallback auf Neutralwerte."""
    missing = [j for j in needed_joints if j not in pose or pose[j] is None]
    if missing:
        raise GestureValidationError(f"{label}: fehlende Gelenke {sorted(missing)}")
    for j in needed_joints:
        value = pose[j]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GestureValidationError(f"{label}: Gelenk '{j}' hat einen nicht-numerischen Wert ({value!r})")
        if not _is_finite(value):
            raise GestureValidationError(f"{label}: Gelenk '{j}' ist NaN/inf")


def _resolve_start_pose(gesture, explicit_start_pose, captured_start_pose):
    """Reihenfolge (Abschnitt 10.2): explizit uebergeben -> aus gueltigen
    Capture-Metadaten -> klar gekennzeichnete NEUTRAL_STAND_POSE. Gibt
    (start_pose_dict, start_pose_source) zurueck."""
    needed = gesture.affected_joints()
    if explicit_start_pose is not None:
        _validate_full_start_pose(explicit_start_pose, needed, "explizit uebergebene Startpose")
        return dict(explicit_start_pose), "explicit"
    if captured_start_pose is not None:
        _validate_full_start_pose(captured_start_pose, needed, "erfasste Capture-Startpose")
        return dict(captured_start_pose), "captured_metadata"
    return dict(NEUTRAL_STAND_POSE), "neutral_stand_pose"


def _resources_or_warn(gesture, warnings: list) -> list:
    try:
        return sorted(resources_for_gesture(gesture))
    except ValueError as e:
        warnings.append(f"Ressourcen konnten nicht abgeleitet werden: {e}")
        return []


def verify_gesture_offline(
    gesture, source_path: str, speed_scale: Optional[float] = None,
    explicit_start_pose: Optional[dict] = None, captured_start_pose: Optional[dict] = None,
    safety_validator=None, repo_dir: Optional[str] = None,
    now_fn=lambda: datetime.now(timezone.utc),
) -> dict:
    """Baut EINEN vollstaendigen Evidenzreport (Abschnitt 10.3) fuer
    genau eine Geste. Wirft nie -- jeder Fehlerfall (Compilerfehler,
    ungueltige Startpose, ...) endet in einem Report mit
    overall_verdict='fail' und einer Eintragung in errors[]."""
    warnings: list = []
    requires_manual_review: list = []
    errors: list = []

    source_sha256 = _sha256_of_file(source_path)
    git_ctx = _git_context(repo_dir, warnings)

    if gesture.schema_version == 1:
        return _build_report(
            gesture=gesture, source_sha256=source_sha256, git_ctx=git_ctx,
            overall_verdict="inconclusive",
            requested_speed_scale=speed_scale, effective_speed_scale=None,
            start_pose_source="not_applicable_v1", start_pose_fingerprint="",
            plan_fingerprint="", raw_duration_s=gesture.duration_s(), effective_duration_s=None,
            max_duration_s=gesture.max_duration_s, affected_joints=gesture.affected_joints(),
            affected_resources=_resources_or_warn(gesture, warnings),
            joint_and_timing="not_applicable_v1", collision_checked=False,
            collision_backend="not_applicable_v1", collision_backend_note="",
            warnings=warnings, requires_manual_review=[LEGACY_V1_REASON], errors=errors,
            now_fn=now_fn,
        )

    effective_speed_scale = speed_scale if speed_scale is not None else gesture.speed_scale_default
    try:
        validate_speed_scale(2, effective_speed_scale)
    except GestureValidationError as e:
        errors.append(str(e))
        return _build_report(
            gesture=gesture, source_sha256=source_sha256, git_ctx=git_ctx, overall_verdict="fail",
            requested_speed_scale=speed_scale, effective_speed_scale=effective_speed_scale,
            start_pose_source="rejected", start_pose_fingerprint="", plan_fingerprint="",
            raw_duration_s=gesture.duration_s(), effective_duration_s=None,
            max_duration_s=gesture.max_duration_s, affected_joints=gesture.affected_joints(),
            affected_resources=_resources_or_warn(gesture, warnings),
            joint_and_timing="fail", collision_checked=False, collision_backend="none",
            collision_backend_note="", warnings=warnings,
            requires_manual_review=requires_manual_review, errors=errors, now_fn=now_fn,
        )

    try:
        start_pose, start_pose_source = _resolve_start_pose(
            gesture, explicit_start_pose, captured_start_pose)
    except GestureValidationError as e:
        errors.append(str(e))
        return _build_report(
            gesture=gesture, source_sha256=source_sha256, git_ctx=git_ctx, overall_verdict="fail",
            requested_speed_scale=speed_scale, effective_speed_scale=effective_speed_scale,
            start_pose_source="rejected", start_pose_fingerprint="", plan_fingerprint="",
            raw_duration_s=gesture.duration_s(), effective_duration_s=None,
            max_duration_s=gesture.max_duration_s, affected_joints=gesture.affected_joints(),
            affected_resources=_resources_or_warn(gesture, warnings),
            joint_and_timing="fail", collision_checked=False, collision_backend="none",
            collision_backend_note="", warnings=warnings,
            requires_manual_review=requires_manual_review, errors=errors, now_fn=now_fn,
        )

    start_pose_fingerprint = _fingerprint_start_pose(start_pose)
    compiler = KinematicCompiler()
    plan = None
    plan_fingerprint = ""
    try:
        plan = compiler.compile(gesture, speed_scale=effective_speed_scale, start_pose=start_pose)
        plan_fingerprint = plan.fingerprint
    except KinematicCompileError:
        plan = None  # validate() unten kompiliert selbst neu und produziert denselben fail-Report.

    validator = safety_validator or TrajectorySafetyValidator(compiler=compiler)
    safety_report = validator.validate(
        gesture, start_pose=start_pose, speed_scale=effective_speed_scale, plan=plan)

    errors.extend(safety_report.joint_timing_errors)
    warnings.extend(safety_report.warnings)
    requires_manual_review.extend(safety_report.requires_manual_review)

    collision_backend = next(
        (n for n in safety_report.backend_names if "collision" in n.lower()), "none")

    return _build_report(
        gesture=gesture, source_sha256=source_sha256, git_ctx=git_ctx,
        overall_verdict=safety_report.verdict,
        requested_speed_scale=speed_scale, effective_speed_scale=effective_speed_scale,
        start_pose_source=start_pose_source, start_pose_fingerprint=start_pose_fingerprint,
        plan_fingerprint=plan_fingerprint, raw_duration_s=gesture.duration_s(),
        effective_duration_s=safety_report.effective_duration_s,
        max_duration_s=gesture.max_duration_s, affected_joints=gesture.affected_joints(),
        affected_resources=_resources_or_warn(gesture, warnings),
        joint_and_timing="fail" if safety_report.joint_timing_errors else "pass",
        collision_checked=safety_report.collision_checked, collision_backend=collision_backend,
        collision_backend_note=safety_report.collision_backend_note,
        warnings=warnings, requires_manual_review=requires_manual_review, errors=errors,
        now_fn=now_fn,
    )


def _build_report(
    gesture, source_sha256, git_ctx, overall_verdict, requested_speed_scale, effective_speed_scale,
    start_pose_source, start_pose_fingerprint, plan_fingerprint, raw_duration_s, effective_duration_s,
    max_duration_s, affected_joints, affected_resources, joint_and_timing, collision_checked,
    collision_backend, collision_backend_note, warnings, requires_manual_review, errors, now_fn,
) -> dict:
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at_utc": now_fn().isoformat(),
        "overall_verdict": overall_verdict,
        "gesture": {
            "name": gesture.name,
            # Entwicklungsauftrag 04-B, AP8 (11/14)-Konvention: nur der
            # Dateiname, kein absoluter Entwicklerpfad in einer
            # deterministischen Ausgabe.
            "source_file": f"{gesture.name}.yaml",
            "source_sha256": source_sha256,
            "schema_version": gesture.schema_version,
            "tested_status": gesture.tested_status,
        },
        "toolchain": {
            "compiler_version": COMPILER_VERSION,
            "repository_commit": git_ctx["repository_commit"],
            "working_tree_dirty": git_ctx["working_tree_dirty"],
        },
        "inputs": {
            "requested_speed_scale": requested_speed_scale,
            "effective_speed_scale": effective_speed_scale,
            "start_pose_source": start_pose_source,
            "start_pose_fingerprint": start_pose_fingerprint,
        },
        "trajectory": {
            "plan_fingerprint": plan_fingerprint,
            "raw_duration_s": raw_duration_s,
            "effective_duration_s": effective_duration_s,
            "max_duration_s": max_duration_s,
            "affected_joints": sorted(affected_joints),
            "affected_resources": affected_resources,
        },
        "checks": {
            "joint_and_timing": joint_and_timing,
            "collision_checked": collision_checked,
            "collision_backend": collision_backend,
            "collision_backend_note": collision_backend_note,
        },
        "warnings": warnings,
        "requires_manual_review": requires_manual_review,
        "errors": errors,
    }


def verdict_to_exitcode(verdict: str) -> int:
    """Abschnitt 12: 0=pass, 1=fail/Schemafehler/ungueltige Eingabe/
    I/O-Fehler, 2=inconclusive."""
    if verdict == "pass":
        return 0
    if verdict == "inconclusive":
        return 2
    return 1


def serialize_report(report: dict) -> str:
    """Sortierte Schluessel, UTF-8, KEINE NaN-/Infinity-JSON-Werte
    (allow_nan=False laesst json.dumps() lieber scheitern, als ein
    ungueltiges JSON-Token zu erzeugen)."""
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_report_atomically(path: str, report: dict) -> None:
    """Schreibt den Report ATOMAR -- eine bestehende Reportdatei wird
    NICHT still ueberschrieben (Abschnitt 11), auch nicht bei einem
    Race. Bei einem internen Serialisierungsfehler bleibt KEINE
    Teildatei zurueck."""
    from .gesture_capture import atomic_create_exclusive, GestureCaptureError
    content = serialize_report(report)
    try:
        atomic_create_exclusive(path, content)
    except GestureCaptureError as e:
        raise ValueError(str(e)) from e
