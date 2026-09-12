"""
Rein lesende Bewegungsaufnahme (Entwicklungsauftrag 04-B, AP8.7,
Commit 12/14). Nutzt AUSSCHLIESSLICH die read()-Schnittstelle aus
joint_state_source.py -- keine Bewegungsmethode ist von hier aus
erreichbar. Erzeugt eine sichere, NICHT freigegebene v2-Gestenkandidatin
(tested_status=draft, selectable_by_llm=false); schreibt NIE in den
aktiven Produktionskatalog, nie automatisch in den Gesture-Memory-Index.

Gemeinsame Gelenkargument-Haertung (_parse_and_validate_joint_list) wird
sowohl von `gesturectl capture-sequence` als auch von der geharteten
`gesturectl capture-pose` genutzt (Abschnitt 4.2/14) -- EIN Pruefpfad,
keine zweite Implementierung.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .joint_limits import ALLOWED_GESTURE_JOINTS, JointLimitError, validate_angle_with_margin
from .motion_transport import _fingerprint_start_pose

# Entwicklungsauftrag 04-B, AP8.7, Abschnitt 8: "0.4 ist die bereits
# dokumentierte Obergrenze fuer den ersten beaufsichtigten v2-Test und
# keine neue Hardwarefreigabe" (siehe docs/GESTURE_LIVE_TEST_CHECKLIST.md).
CAPTURE_SPEED_SCALE_DEFAULT = 0.4
# Kleine, deterministische Marge auf die aus der Zeitachse abgeleitete
# effektive Dauer -- gleiches Muster wie bei den bestehenden
# AP8.4-Korrekturen in den echten Kataloggesten (z.B. celebrate_small.yaml:
# 2.67s effektive Dauer -> max_duration_s=2.8).
CAPTURE_MAX_DURATION_MARGIN_S = 0.1

# Obergrenze fuer eine einzelne Aufnahme -- verhindert eine ausufernde
# Samplezahl (Speicher/Datei) durch eine versehentlich sehr lange
# Dauer * sehr hohe Samplingrate. Kein aus der Luft gegriffener Wert
# noetig: 1000 Samples je Sequenz sind fuer jede realistische
# Gestenkandidatin (wenige Sekunden bei <=20Hz) weit ausreichend.
MAX_CAPTURE_SAMPLE_COUNT = 1000

# Sichere Namenskonvention -- identisch zur bereits etablierten
# Namensgebung aller 24 Kataloggesten (klein geschrieben, Ziffern/
# Unterstriche, beginnt mit einem Buchstaben).
_SAFE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class GestureCaptureError(ValueError):
    """Deckt sowohl Argument-/Schemafehler als auch fail-closed
    abgebrochene Aufnahmen ab -- der Aufrufer (gesturectl.py) meldet in
    beiden Faellen einen Fehler und schreibt KEINE Datei."""


def _is_finite(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def parse_and_validate_joint_list(raw: str) -> list:
    """Gemeinsame Haertung fuer --joints (Abschnitt 4.2/6/14): trennt an
    Kommas, entfernt Leerzeichen, lehnt leere Elemente, unbekannte
    Gelenke (alles ausser ALLOWED_GESTURE_JOINTS -- KEINE Chain-Namen
    wie 'Body'/'Head'/'Arms', keine freien qicli-Fragmente) und
    Duplikate ab. Gibt eine ALPHABETISCH SORTIERTE (also deterministische)
    Liste zurueck -- unabhaengig von der Eingabereihenfolge.

    Die Ablehnung unbekannter Gelenke ist zugleich die Injektions-
    Absicherung: jeder Name, der die exakte Mengenzugehoerigkeit zu
    ALLOWED_GESTURE_JOINTS nicht besteht (das sind ausschliesslich
    einfache alphanumerische Bezeichner ohne Sonderzeichen), wird
    abgelehnt, BEVOR er jemals in eine SSH-/qicli-Zeichenkette
    eingesetzt werden koennte."""
    if raw is None or not raw.strip():
        raise GestureCaptureError("--joints ist leer oder fehlt -- mindestens ein Gelenk erforderlich.")
    raw_parts = raw.split(",")
    seen = set()
    joints = []
    for part in raw_parts:
        joint = part.strip()
        if not joint:
            raise GestureCaptureError(
                f"--joints enthaelt ein leeres Element (aus '{raw}') -- nicht zulaessig."
            )
        if joint not in ALLOWED_GESTURE_JOINTS:
            raise GestureCaptureError(
                f"Gelenk '{joint}' ist nicht freigegeben (erlaubt: "
                f"{sorted(ALLOWED_GESTURE_JOINTS)})."
            )
        if joint in seen:
            raise GestureCaptureError(f"Gelenk '{joint}' ist doppelt angegeben.")
        seen.add(joint)
        joints.append(joint)
    return sorted(joints)


def validate_safe_gesture_name(name: str) -> str:
    if not name or not _SAFE_NAME_PATTERN.match(name):
        raise GestureCaptureError(
            f"Gestenname '{name}' ist ungueltig (erlaubt: klein geschrieben, beginnt mit einem "
            "Buchstaben, danach nur a-z/0-9/_)."
        )
    return name


def derive_name_from_output_path(output_path: str) -> str:
    base = os.path.basename(output_path)
    if base.endswith(".yaml"):
        base = base[: -len(".yaml")]
    return validate_safe_gesture_name(base)


@dataclass
class SequenceCaptureResult:
    """Ergebnis einer vollstaendigen capture_sequence()-Aufnahme --
    reiner Datentraeger, noch KEINE YAML-Kandidatin (siehe
    build_candidate_gesture_data())."""

    keyframes: list
    joints: list
    requested_sample_rate_hz: float
    achieved_sample_rate_hz: float
    requested_duration_s: float
    actual_duration_s: float
    sample_count: int
    maximum_sample_span_s: float
    acquisition_mode: str
    source_backend: str
    captured_at_utc: str
    start_pose: dict = field(default_factory=dict)


def capture_sequence(
    source, joints: list, duration_s: float, sample_rate_hz: float,
    monotonic_fn=time.monotonic, sleep_fn=time.sleep,
    utc_now_fn=lambda: datetime.now(timezone.utc),
) -> SequenceCaptureResult:
    """Kernschleife -- REIN lesend (source.read() ist die einzige
    Interaktion). Wirft GestureCaptureError fail-closed bei JEDER
    ungueltigen/unvollstaendigen Messung, OHNE jemals eine
    Kandidatendatei zu schreiben (das macht ausschliesslich der Aufrufer,
    siehe gesturectl.py::cmd_capture_sequence, und NUR nach dieser
    Funktion erfolgreich zurueckgekehrt ist).

    Zeiten sind IMMER die tatsaechlichen (monotonic_fn-basierten)
    Erfassungszeitpunkte -- niemals ideale Sollzeitpunkte. Der erste
    gueltige Messpunkt wird zu time_from_start_s=0.0, alle folgenden
    Zeiten sind relativ dazu und werden auf strenge Monotonie geprueft
    (kein Runden, das Zeitgleichheit erzeugen wuerde -- ein solcher Fall
    bricht die Aufnahme fail-closed ab, statt ihn zu verschleiern)."""
    if not _is_finite(duration_s) or duration_s <= 0:
        raise GestureCaptureError(f"duration_s muss endlich und positiv sein (erhalten: {duration_s!r}).")
    if not _is_finite(sample_rate_hz) or sample_rate_hz <= 0:
        raise GestureCaptureError(f"sample_rate_hz muss endlich und positiv sein (erhalten: {sample_rate_hz!r}).")
    if duration_s * sample_rate_hz > MAX_CAPTURE_SAMPLE_COUNT:
        raise GestureCaptureError(
            f"duration_s * sample_rate_hz ({duration_s * sample_rate_hz:.1f}) ueberschreitet die "
            f"Obergrenze von {MAX_CAPTURE_SAMPLE_COUNT} Samples."
        )
    if not joints:
        raise GestureCaptureError("mindestens ein Gelenk erforderlich.")

    sample_interval_s = 1.0 / sample_rate_hz
    captured_at_utc = utc_now_fn().isoformat()

    readings = []
    relative_times = []
    base_time = None
    sample_index = 0
    while True:
        reading = source.read(joints)
        if base_time is None:
            base_time = reading.acquisition_started_monotonic_s

        for joint in joints:
            if joint not in reading.values:
                raise GestureCaptureError(f"Sample {sample_index}: Gelenk '{joint}' fehlt in der Messung.")
            value = reading.values[joint]
            if value is None:
                raise GestureCaptureError(
                    f"Sample {sample_index}: Gelenk '{joint}' lieferte None -- Aufnahme abgebrochen."
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise GestureCaptureError(
                    f"Sample {sample_index}: Gelenk '{joint}' lieferte einen nicht-numerischen Wert "
                    f"({value!r})."
                )
            fvalue = float(value)
            if not _is_finite(fvalue):
                raise GestureCaptureError(f"Sample {sample_index}: Gelenk '{joint}' lieferte NaN/inf.")
            try:
                validate_angle_with_margin(joint, fvalue)
            except JointLimitError as e:
                raise GestureCaptureError(f"Sample {sample_index}: {e}") from e

        relative_time = reading.acquisition_started_monotonic_s - base_time
        if relative_times and relative_time <= relative_times[-1]:
            raise GestureCaptureError(
                f"Sample {sample_index}: Zeitachse nicht streng monoton "
                f"(t={relative_time} <= vorheriges t={relative_times[-1]})."
            )
        readings.append(reading)
        relative_times.append(relative_time)
        sample_index += 1

        elapsed_s = reading.acquisition_finished_monotonic_s - base_time
        if elapsed_s >= duration_s and len(readings) >= 2:
            break
        if len(readings) >= MAX_CAPTURE_SAMPLE_COUNT:
            raise GestureCaptureError(
                f"maximale Samplezahl ({MAX_CAPTURE_SAMPLE_COUNT}) erreicht, ohne die angeforderte "
                "Dauer zu erreichen -- Aufnahme abgebrochen."
            )
        sleep_fn(sample_interval_s)

    if len(readings) < 2:
        raise GestureCaptureError("mindestens zwei vollstaendige Samples sind fuer eine Sequenz erforderlich.")

    actual_duration_s = relative_times[-1]
    achieved_sample_rate_hz = (
        (len(readings) - 1) / actual_duration_s if actual_duration_s > 0 else 0.0
    )
    maximum_sample_span_s = max(r.acquisition_span_s for r in readings)
    acquisition_mode = readings[0].acquisition_mode
    source_backend = readings[0].source_backend

    keyframes = [
        {"time_from_start_s": t, "joints": dict(r.values)}
        for t, r in zip(relative_times, readings)
    ]

    return SequenceCaptureResult(
        keyframes=keyframes, joints=list(joints),
        requested_sample_rate_hz=sample_rate_hz, achieved_sample_rate_hz=achieved_sample_rate_hz,
        requested_duration_s=duration_s, actual_duration_s=actual_duration_s,
        sample_count=len(readings), maximum_sample_span_s=maximum_sample_span_s,
        acquisition_mode=acquisition_mode, source_backend=source_backend,
        captured_at_utc=captured_at_utc, start_pose=dict(readings[0].values),
    )


def build_candidate_gesture_data(name: str, result: SequenceCaptureResult) -> dict:
    """Baut die vollstaendige, SICHERE v2-Kandidatendatei (Abschnitt 8) --
    tested_status=draft, selectable_by_llm=false, ausschliesslich IDLE
    erlaubt, on_cancel=hold, keine Breathing-Deaktivierung. max_duration_s
    wird deterministisch aus der ERFASSTEN (unskalierten) Zeitachse UND
    CAPTURE_SPEED_SCALE_DEFAULT abgeleitet (identische Semantik wie
    kinematic_compiler.py: effektive Dauer = raw / speed_scale) -- NICHT
    aus der unskalierten Achse selbst uebernommen (bestaetigter Fund,
    frueher an mehreren Kataloggesten korrigiert, siehe AP8.4)."""
    validate_safe_gesture_name(name)
    raw_last_time_s = result.keyframes[-1]["time_from_start_s"]
    max_duration_s = round(
        raw_last_time_s / CAPTURE_SPEED_SCALE_DEFAULT + CAPTURE_MAX_DURATION_MARGIN_S, 3)

    return {
        "schema_version": 2,
        "name": name,
        "description": "Read-only erfasste Gestenkandidatin; noch nicht validiert.",
        "system_only": False,
        "selectable_by_llm": False,
        "semantic_tags": [],
        "tested_status": "draft",
        "tested_date": None,
        "test_note": "Rein lesend erfasst; kein Dry-Run und kein Hardwaretest.",
        "requires_stationary": True,
        "allowed_interaction_states": ["IDLE"],
        "speed_scale_default": CAPTURE_SPEED_SCALE_DEFAULT,
        "max_duration_s": max_duration_s,
        "on_cancel": "hold",
        "restore_after": True,
        "disable_breathing": [],
        "metadata": {
            "capture": {
                "schema_version": 1,
                "source_backend": result.source_backend,
                "acquisition_mode": result.acquisition_mode,
                "captured_at_utc": result.captured_at_utc,
                "time_base": "monotonic",
                "requested_sample_rate_hz": result.requested_sample_rate_hz,
                "achieved_sample_rate_hz": result.achieved_sample_rate_hz,
                "requested_duration_s": result.requested_duration_s,
                "actual_duration_s": result.actual_duration_s,
                "sample_count": result.sample_count,
                "joints": list(result.joints),
                "maximum_sample_span_s": result.maximum_sample_span_s,
                "hardware_validation": "hwverificationrequired",
                "start_pose": dict(result.start_pose),
                "start_pose_fingerprint": _fingerprint_start_pose(result.start_pose),
            },
        },
        "keyframes": result.keyframes,
    }


def atomic_create_exclusive(final_path: str, content: str) -> None:
    """Schreibt `content` unter `final_path`, aber NUR wenn dort noch
    keine Datei existiert -- auch bei einem Race zwischen zwei
    gleichzeitigen Aufrufen (Abschnitt 7.4). os.link() ist auf POSIX
    atomar: schlaegt zuverlaessig fehl, wenn final_path in der Zwischen-
    zeit bereits von einem anderen Prozess angelegt wurde (anders als
    os.rename(), das eine bestehende Datei stillschweigend ersetzen
    wuerde)."""
    directory = os.path.dirname(os.path.abspath(final_path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".capture-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp_path, final_path)
        except FileExistsError:
            raise GestureCaptureError(
                f"Zieldatei '{final_path}' existiert bereits -- wird NICHT ueberschrieben."
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
