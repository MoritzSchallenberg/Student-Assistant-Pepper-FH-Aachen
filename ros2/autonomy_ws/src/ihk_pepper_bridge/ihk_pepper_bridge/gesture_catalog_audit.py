"""
Deterministische Katalogpruefung + Inventar-Renderer (Entwicklungsauftrag
04-B, AP8, Commit 11/14). Rein lesend -- instanziiert NIE einen
Pepper-Client, oeffnet KEINE Netzwerkverbindung, ruft NIE SSH/qicli/eine
ROS-Action auf und veraendert NIE eine YAML-Datei/einen Status. Nutzt
ausschliesslich die bereits validierte GestureCatalog/Gesture-Klasse
(gesture_catalog.py) -- kein zweiter YAML-Parser.

`gesturectl audit` (gesturectl.py::cmd_audit) und die generierte
docs/GESTURE_CATALOG_INVENTORY.md (siehe scripts/generate_gesture_
inventory.py) nutzen BEIDE denselben audit_catalog()/render_*()-Code
hier -- die Inventartabelle kann dadurch nicht von Hand aus der Reihe
laufen.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# Entwicklungsauftrag 04-B, AP8 (11/14), Abschnitt 6.1: diese drei
# Gesten MUESSEN Systemgesten bleiben (Auftrag-Vorgabe, nicht nur
# Empfehlung).
MANDATORY_SYSTEM_ONLY_GESTURES = frozenset({
    "acknowledge_nod_small", "thinking_loop_subtle", "look_at_person",
})

# Bekannte Links-/Rechts-Spiegelpaare (Abschnitt 7). Ein Paar, dessen
# BEIDE Namen im Katalog vorhanden sind, wird automatisch geprueft --
# fehlt eine Seite, wird das NICHT als Fehler gewertet (z.B. waehrend
# eines Zwischenzustands mit nur einer Seite im Katalog).
KNOWN_MIRROR_PAIRS = (
    ("wave_left", "wave_right"),
    ("explain_left", "explain_right"),
)

# Gelenk-Suffixe, deren Wert zwischen L- und R-Seite IDENTISCH bleiben
# muss (Pitch dreht um eine links-rechts-gemeinsame Achse). Alle anderen
# bekannten bilateralen Suffixe (Roll/Yaw) muessen VORZEICHENGESPIEGELT
# sein (bestaetigt gegen joint_limits.py: LShoulderRoll ist bei Pepper
# strukturell positiv, RShoulderRoll strukturell negativ, analog fuer
# ElbowRoll/ElbowYaw).
_SAME_VALUE_SUFFIXES = ("ShoulderPitch",)
_FLIPPED_VALUE_SUFFIXES = ("ShoulderRoll", "ElbowRoll", "ElbowYaw", "WristYaw")
_MIRROR_TOLERANCE = 1e-6

# Grobes Muster fuer versehentlich in Freitextfeldern (description/
# test_note/metadata-Werte) gelandete ausfuehrbare Hardwarebefehle --
# Abschnitt 9.1 ("keine ausfuehrbaren Hardwarekommandos in Metadaten").
# Ein Treffer ist ein WARNHINWEIS (ein Codebeispiel in der Doku ist
# nicht automatisch ein Angriff), kein automatischer harter Fehler.
_SUSPICIOUS_COMMAND_PATTERN = re.compile(
    r"\bssh\s+\S+@|\bqicli\s+(run|play|call)\b|\bsubprocess\.|\bos\.system\(|\beval\(|\bexec\(",
    re.IGNORECASE,
)


def _split_bilateral_joint(joint: str) -> Optional[tuple]:
    """Zerlegt z.B. 'LShoulderRoll' in ('L', 'ShoulderRoll'). Gibt None
    zurueck, wenn joint keinen bekannten bilateralen Suffix traegt (z.B.
    HeadYaw, HipRoll -- gemeinsame, nicht Seiten-gebundene Gelenke)."""
    if joint[0] not in ("L", "R"):
        return None
    suffix = joint[1:]
    if suffix in _SAME_VALUE_SUFFIXES or suffix in _FLIPPED_VALUE_SUFFIXES:
        return joint[0], suffix
    return None


def _mirror_joint_name(joint: str) -> Optional[str]:
    """'LShoulderRoll' -> 'RShoulderRoll' und umgekehrt; None fuer
    unbekannte/nicht-bilaterale Gelenke."""
    parsed = _split_bilateral_joint(joint)
    if parsed is None:
        return None
    side, suffix = parsed
    other_side = "R" if side == "L" else "L"
    return f"{other_side}{suffix}"


def check_mirror_pair(name_a: str, gesture_a, name_b: str, gesture_b) -> list:
    """Vergleicht zwei per Konvention gespiegelte Gesten (z.B. wave_left/
    wave_right). Gibt eine Liste von Fehlertexten zurueck (leer = keine
    Abweichung gefunden). Nur fuer schema_version 2 sinnvoll -- v1 wird
    mit einer eigenen Meldung uebersprungen (kein Fehler, nur ein
    Hinweis, dass diese Pruefung fuer v1 nicht gilt)."""
    if gesture_a.schema_version != 2 or gesture_b.schema_version != 2:
        return [
            f"Spiegelpruefung '{name_a}'/'{name_b}' uebersprungen (nur fuer schema_version 2 "
            "implementiert)."
        ]

    errors = []
    times_a = [kf["time_from_start_s"] for kf in gesture_a.keyframes]
    times_b = [kf["time_from_start_s"] for kf in gesture_b.keyframes]
    if times_a != times_b:
        errors.append(
            f"'{name_a}'/'{name_b}': Zeitachsen unterscheiden sich ({times_a} != {times_b})."
        )
        return errors  # ohne gleiche Zeitachse ist ein Keyframe-Vergleich nicht sinnvoll.

    for i, (kf_a, kf_b) in enumerate(zip(gesture_a.keyframes, gesture_b.keyframes)):
        joints_a = kf_a["joints"]
        joints_b = kf_b["joints"]
        # Erwartete Gelenkmenge in b: jedes Gelenk aus a, gespiegelt
        # (bilaterale Gelenke) oder unveraendert (gemeinsame Gelenke).
        expected_in_b = set()
        for joint in joints_a:
            mirrored = _mirror_joint_name(joint)
            expected_in_b.add(mirrored if mirrored is not None else joint)
        actual_in_b = set(joints_b.keys())
        if expected_in_b != actual_in_b:
            errors.append(
                f"'{name_a}'/'{name_b}', Keyframe {i}: Gelenkmenge passt nicht zusammen "
                f"(erwartet in '{name_b}': {sorted(expected_in_b)}, tatsaechlich: "
                f"{sorted(actual_in_b)})."
            )
            continue
        for joint, value_a in joints_a.items():
            parsed = _split_bilateral_joint(joint)
            if parsed is None:
                # Gemeinsames Gelenk (z.B. HeadYaw) -- muss identisch sein.
                value_b = joints_b.get(joint)
                if value_b is None or abs(float(value_b) - float(value_a)) > _MIRROR_TOLERANCE:
                    errors.append(
                        f"'{name_a}'/'{name_b}', Keyframe {i}: gemeinsames Gelenk '{joint}' "
                        f"unterscheidet sich ({value_a} != {value_b})."
                    )
                continue
            side, suffix = parsed
            mirrored_joint = _mirror_joint_name(joint)
            value_b = joints_b.get(mirrored_joint)
            if value_b is None:
                continue  # bereits oben als Gelenkmengen-Abweichung gemeldet.
            if suffix in _SAME_VALUE_SUFFIXES:
                if abs(float(value_b) - float(value_a)) > _MIRROR_TOLERANCE:
                    errors.append(
                        f"'{name_a}'/'{name_b}', Keyframe {i}: '{joint}'={value_a} sollte "
                        f"identisch zu '{mirrored_joint}'={value_b} sein (Pitch-Gelenk, keine "
                        "Vorzeichenspiegelung erwartet)."
                    )
            else:
                if abs(float(value_b) + float(value_a)) > _MIRROR_TOLERANCE:
                    errors.append(
                        f"'{name_a}'/'{name_b}', Keyframe {i}: '{joint}'={value_a} sollte "
                        f"vorzeichengespiegelt zu '{mirrored_joint}'={value_b} sein (erwartet "
                        f"{-float(value_a)}, Roll/Yaw-Gelenk)."
                    )
    return errors


@dataclass
class GestureAuditEntry:
    """Eine Zeile im Audit-/Inventarbericht -- ein Snapshot der
    kanonischen Felder EINER Geste, rein zur Anzeige (kein eigenes
    Verhalten)."""

    name: str
    schema_version: int
    tested_status: str
    tested_date: object
    system_only: bool
    selectable_by_llm: bool
    semantic_tags: list
    requires_stationary: bool
    allowed_interaction_states: list
    duration_s: float
    max_duration_s: object
    on_cancel: str
    affected_joints: list
    source_path: str
    messages: list = field(default_factory=list)  # (level, text) -- level in ("error", "warning")


@dataclass
class AuditResult:
    entries: list
    load_errors: list  # Dateien, die GestureCatalog.reload() bereits abgelehnt hat
    total_yaml_files_found: int

    @property
    def error_count(self) -> int:
        return len(self.load_errors) + sum(
            1 for e in self.entries for level, _ in e.messages if level == "error"
        )

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.entries for level, _ in e.messages if level == "warning")

    def counts_by_tested_status(self) -> dict:
        counts = {}
        for e in self.entries:
            counts[e.tested_status] = counts.get(e.tested_status, 0) + 1
        return counts

    def counts_by_schema_version(self) -> dict:
        counts = {}
        for e in self.entries:
            counts[e.schema_version] = counts.get(e.schema_version, 0) + 1
        return counts

    @property
    def system_only_count(self) -> int:
        return sum(1 for e in self.entries if e.system_only)

    @property
    def selectable_by_llm_count(self) -> int:
        return sum(1 for e in self.entries if e.selectable_by_llm)


def _scan_suspicious_text(gesture, entry: GestureAuditEntry) -> None:
    for field_name, text in (
        ("description", gesture.description),
        ("test_note", gesture.test_note),
    ):
        if _SUSPICIOUS_COMMAND_PATTERN.search(text or ""):
            entry.messages.append((
                "warning",
                f"Feld '{field_name}' enthaelt ein Muster, das wie ein ausfuehrbarer "
                "Hardware-/Shell-Befehl aussieht -- bitte manuell pruefen.",
            ))
    for key, value in (gesture.metadata or {}).items():
        if isinstance(value, str) and _SUSPICIOUS_COMMAND_PATTERN.search(value):
            entry.messages.append((
                "warning",
                f"metadata['{key}'] enthaelt ein Muster, das wie ein ausfuehrbarer "
                "Hardware-/Shell-Befehl aussieht -- bitte manuell pruefen.",
            ))


def audit_catalog(catalog, load_errors: Optional[list] = None,
                  total_yaml_files_found: Optional[int] = None) -> AuditResult:
    """Baut einen vollstaendigen AuditResult aus einem BEREITS geladenen
    (catalog.reload() wurde vom Aufrufer bereits ausgefuehrt und dessen
    Rueckgabe hier als load_errors uebergeben) GestureCatalog.
    total_yaml_files_found: Anzahl der *.yaml-Dateien im Katalogordner
    (geladen + uebersprungen zusammen) -- Aufrufer zaehlt das selbst
    (glob), damit dieses Modul keinen eigenen Dateisystemzugriff braucht
    und in Tests mit einem rein synthetischen Katalog nutzbar bleibt."""
    load_errors = list(load_errors) if load_errors is not None else []
    entries = []
    descriptions_seen = {}

    names = catalog.names()
    for name in names:
        gesture = catalog.get(name)
        entry = GestureAuditEntry(
            name=name, schema_version=gesture.schema_version, tested_status=gesture.tested_status,
            tested_date=gesture.tested_date, system_only=gesture.system_only,
            selectable_by_llm=gesture.selectable_by_llm, semantic_tags=list(gesture.semantic_tags),
            requires_stationary=gesture.requires_stationary,
            allowed_interaction_states=list(gesture.allowed_interaction_states),
            duration_s=gesture.duration_s(), max_duration_s=gesture.max_duration_s,
            on_cancel=gesture.on_cancel, affected_joints=gesture.affected_joints(),
            # Entwicklungsauftrag 04-B, AP8 (11/14), Abschnitt 9.2: 'keine
            # absoluten Entwicklerpfade in deterministischen Ausgaben' --
            # nur der Dateiname (relativ zum Katalogordner) ist zwischen
            # verschiedenen Umgebungen/Maschinen identisch.
            source_path=os.path.basename(gesture.source_path),
        )

        if not gesture.description.strip():
            entry.messages.append(("error", "description ist leer."))
        else:
            normalized = " ".join(gesture.description.split()).lower()
            if normalized in descriptions_seen:
                entry.messages.append((
                    "warning",
                    f"description ist (nach Normalisierung) identisch zu '{descriptions_seen[normalized]}'.",
                ))
            else:
                descriptions_seen[normalized] = name

        if name in MANDATORY_SYSTEM_ONLY_GESTURES and not gesture.system_only:
            entry.messages.append((
                "error",
                f"'{name}' ist laut Auftrag verbindlich eine Systemgeste (system_only=true "
                "erforderlich).",
            ))

        if gesture.schema_version == 1:
            entry.messages.append((
                "warning",
                "v1-Gesteneintrag (sequenzielles Format) -- bleibt strukturell aus 'production' "
                "gesperrt, siehe gesture_execution_policy.py.",
            ))

        legacy_keys = [
            k for k in ("system_only", "selectable_by_llm", "semantic_tags")
            if k in (gesture.metadata or {})
        ]
        if legacy_keys:
            entry.messages.append((
                "warning",
                f"verwendet weiterhin den Legacy-metadata-Fallback fuer {legacy_keys} statt "
                "kanonischer Top-Level-Felder.",
            ))

        _scan_suspicious_text(gesture, entry)
        entries.append(entry)

    entries_by_name = {e.name: e for e in entries}
    for name_a, name_b in KNOWN_MIRROR_PAIRS:
        if name_a not in entries_by_name or name_b not in entries_by_name:
            continue  # eine oder beide Seiten (noch) nicht im Katalog -- kein Fehler.
        gesture_a = catalog.get(name_a)
        gesture_b = catalog.get(name_b)
        mismatches = check_mirror_pair(name_a, gesture_a, name_b, gesture_b)
        for msg in mismatches:
            level = "warning" if msg.startswith("Spiegelpruefung") and "uebersprungen" in msg else "error"
            entries_by_name[name_a].messages.append((level, msg))

    if total_yaml_files_found is None:
        total_yaml_files_found = len(names) + len(load_errors)

    return AuditResult(
        entries=sorted(entries, key=lambda e: e.name),
        load_errors=list(load_errors),
        total_yaml_files_found=total_yaml_files_found,
    )


def render_audit_report(result: AuditResult) -> str:
    """Deterministischer, alphabetisch sortierter Textbericht fuer
    'gesturectl audit' (Abschnitt 9.2)."""
    lines = []
    for entry in result.entries:  # bereits alphabetisch sortiert
        lines.append(f"=== {entry.name} ===")
        lines.append(f"  Schema-Version: {entry.schema_version}")
        lines.append(f"  tested_status: {entry.tested_status}")
        lines.append(f"  tested_date: {entry.tested_date}")
        lines.append(f"  system_only: {entry.system_only}")
        lines.append(f"  selectable_by_llm: {entry.selectable_by_llm}")
        lines.append(f"  semantic_tags: {entry.semantic_tags}")
        lines.append(f"  requires_stationary: {entry.requires_stationary}")
        lines.append(f"  allowed_interaction_states: {entry.allowed_interaction_states}")
        lines.append(f"  effektive Katalogdauer: {entry.duration_s:.2f}s")
        lines.append(f"  max_duration_s: {entry.max_duration_s}")
        lines.append(f"  on_cancel: {entry.on_cancel}")
        lines.append(f"  betroffene Gelenke: {entry.affected_joints}")
        lines.append(f"  Quelldatei: {entry.source_path}")
        if entry.messages:
            for level, msg in entry.messages:
                lines.append(f"  [{level.upper()}] {msg}")
        else:
            lines.append("  keine Auffaelligkeiten")
        lines.append("")

    if result.load_errors:
        lines.append("=== Ladefehler (Datei uebersprungen) ===")
        for e in sorted(result.load_errors):
            lines.append(f"  [ERROR] {e}")
        lines.append("")

    lines.append("=== Zusammenfassung ===")
    lines.append(f"  Gefundene YAML-Dateien: {result.total_yaml_files_found}")
    lines.append(f"  Erfolgreich geladen: {len(result.entries)}")
    lines.append(f"  Uebersprungen (Ladefehler): {len(result.load_errors)}")
    for schema_version, count in sorted(result.counts_by_schema_version().items()):
        lines.append(f"  Schema-Version {schema_version}: {count}")
    for status, count in sorted(result.counts_by_tested_status().items()):
        lines.append(f"  tested_status={status}: {count}")
    lines.append(f"  Systemgesten (system_only=true): {result.system_only_count}")
    lines.append(f"  LLM-auswaehlbare Gesten (selectable_by_llm=true): {result.selectable_by_llm_count}")
    lines.append(f"  Fehler: {result.error_count}")
    lines.append(f"  Warnungen: {result.warning_count}")
    return "\n".join(lines) + "\n"


def render_inventory_markdown(result: AuditResult) -> str:
    """Erzeugt docs/GESTURE_CATALOG_INVENTORY.md (Abschnitt 10) --
    DETERMINISTISCH (keine Uhrzeit, keine absoluten Pfade, alphabetisch
    sortiert, keine fest codierte Anzahl -- alle Zahlen werden aus
    `result` abgeleitet)."""
    lines = []
    lines.append("# Gesten-Katalog-Inventar")
    lines.append("")
    lines.append(
        "**Automatisch erzeugt -- NICHT manuell bearbeiten.** Erzeugt aus dem echten "
        "YAML-Gestenkatalog ueber dieselbe validierte `GestureCatalog`/`Gesture`-Klasse und "
        "denselben Renderer wie `gesturectl audit` (siehe `gesture_catalog_audit.py`)."
    )
    lines.append("")
    lines.append("Reproduktionsbefehl:")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/generate_gesture_inventory.py")
    lines.append("```")
    lines.append("")
    lines.append(
        f"Gesamt: {len(result.entries)} Gesten "
        f"({result.system_only_count} Systemgesten, {result.selectable_by_llm_count} "
        "LLM-auswaehlbar)."
    )
    lines.append("")
    lines.append("## Statusverteilung")
    lines.append("")
    lines.append("| tested_status | Anzahl |")
    lines.append("| --- | --- |")
    for status, count in sorted(result.counts_by_tested_status().items()):
        lines.append(f"| {status} | {count} |")
    lines.append("")
    lines.append(
        "**Historischer Sonderfall `t_pose`**: `tested_status: live_validated` bezieht sich "
        "NUR auf den historischen v1-Hardwaretest der Bewegung selbst -- v1 bleibt strukturell "
        "aus `production` gesperrt (siehe `gesture_execution_policy.py`), dieser Status umgeht "
        "KEINES der AP8-R1-/AP8-R2-Sicherheitsgates. `t_pose` ist zusaetzlich `system_only`."
    )
    lines.append("")
    lines.append(
        "**Platzhalter `look_at_person`**: berechnet KEINE echte Blickrichtung zu einer "
        "konkreten Person -- eine feste, sichere Neutralstellung. `system_only`, nicht "
        "LLM-auswaehlbar."
    )
    lines.append("")
    lines.append("## Gesten")
    lines.append("")
    lines.append(
        "| Name | Schema | tested_status | system_only | selectable_by_llm | semantic_tags | "
        "max_duration_s |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for entry in result.entries:
        tags = ", ".join(entry.semantic_tags) if entry.semantic_tags else "--"
        lines.append(
            f"| {entry.name} | v{entry.schema_version} | {entry.tested_status} | "
            f"{entry.system_only} | {entry.selectable_by_llm} | {tags} | {entry.max_duration_s} |"
        )
    lines.append("")
    if result.warning_count or result.error_count:
        lines.append("## Audit-Hinweise")
        lines.append("")
        for entry in result.entries:
            for level, msg in entry.messages:
                lines.append(f"- **{entry.name}** [{level}]: {msg}")
        lines.append("")
    return "\n".join(lines) + "\n"
