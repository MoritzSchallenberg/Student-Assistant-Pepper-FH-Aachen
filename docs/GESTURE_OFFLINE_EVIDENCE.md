# Vollständig offline reproduzierbare Gestenevidenz

Stand: 2026-09-12. Entwicklungsauftrag 04-B, AP8.7, Commit 12/14.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_bridge/ihk_pepper_bridge/gesture_offline_evidence.py`,
`gesturectl.py` (Unterbefehle `verify-offline`, `validate-all`).

## Zweck

`gesturectl verify-offline <name> --report <datei.json>` erzeugt einen
strukturierten, reproduzierbaren JSON-Evidenzreport für **genau eine**
Geste. `gesturectl validate-all` prüft **jede** Kataloggeste mit
demselben Kern und fasst das Ergebnis zusammen. Beide sind vollständig
offline: kein Pepper-Client, kein Netzwerk, kein SSH/qicli, keine
ROS-Action. `validate-all` schreibt ohne `--report` keine Datei;
`verify-offline` schreibt **ausschließlich** die ausdrücklich
angeforderte Reportdatei -- niemals `tested_status`/`tested_date`/
`test_note`, niemals die YAML-Datei selbst, niemals den
Gesture-Memory-Index.

## Kanonischer Prüfpfad -- keine zweite Sicherheitslogik

```
GestureCatalog
  -> kanonische Speed-Scale-Auflösung (gesture_catalog.py::validate_speed_scale)
  -> KinematicCompiler.compile()
  -> TrajectorySafetyValidator.validate()
  -> ihk_pepper_interaction.resource_derivation.resources_for_gesture()
  -> strukturierter Evidenzreport
```

`gesture_offline_evidence.py` implementiert **keine** eigene
Gelenkgrenzen-, Speed-Scale-, Geschwindigkeits-/Beschleunigungs-,
Startpose- oder Ressourcenlogik -- alle Werte kommen aus den
bestehenden, bereits an anderer Stelle validierten Modulen. Der Plan
wird genau **einmal** kompiliert (für den `plan_fingerprint`) und
danach `TrajectorySafetyValidator.validate(..., plan=plan)` übergeben,
damit dieselbe Instanz nicht ein zweites Mal kompiliert.

## Startposequelle (Priorität)

1. explizit übergeben (`--start-pose <datei.yaml-oder-json>`),
2. aus gültigen Capture-Metadaten (`metadata.capture.start_pose`, siehe
   `docs/GESTURE_CAPTURE_WORKFLOW.md`),
3. klar gekennzeichnete `NEUTRAL_STAND_POSE`.

Der Report nennt die tatsächlich verwendete Quelle
(`inputs.start_pose_source`: `"explicit"` | `"captured_metadata"` |
`"neutral_stand_pose"` | `"not_applicable_v1"`). Eine explizite oder
erfasste Startpose muss **jedes** von der Geste benötigte Gelenk mit
einem endlichen Wert enthalten -- kein Teil-Fallback auf Neutralwerte;
eine unvollständige Startpose führt zu `overall_verdict: fail`.

## Report-Schema (Auszug)

```json
{
  "report_schema_version": 1,
  "generated_at_utc": "2026-09-12T21:42:17+00:00",
  "overall_verdict": "inconclusive",
  "gesture": {
    "name": "wave_right", "source_file": "wave_right.yaml",
    "source_sha256": "<sha256 ueber die Quelldatei-Bytes>",
    "schema_version": 2, "tested_status": "dry_run_validated"
  },
  "toolchain": {
    "compiler_version": "ap8.4",
    "repository_commit": "<git-hash oder 'unavailable'>",
    "working_tree_dirty": true
  },
  "inputs": {
    "requested_speed_scale": null, "effective_speed_scale": 1.0,
    "start_pose_source": "neutral_stand_pose",
    "start_pose_fingerprint": "<hash>"
  },
  "trajectory": {
    "plan_fingerprint": "<hash>", "raw_duration_s": 2.8,
    "effective_duration_s": 2.8, "max_duration_s": 3.5,
    "affected_joints": ["RElbowRoll", "RElbowYaw", "RShoulderPitch"],
    "affected_resources": ["RIGHT_ARM"]
  },
  "checks": {
    "joint_and_timing": "pass", "collision_checked": false,
    "collision_backend": "disabled_collision", "collision_backend_note": "..."
  },
  "warnings": [], "requires_manual_review": [...], "errors": []
}
```

`source_file` ist bewusst nur der Dateiname (keine absoluten
Entwicklerpfade in einer deterministischen Ausgabe, gleiche Konvention
wie `gesturectl audit`). `repository_commit`/`working_tree_dirty` sind
ehrlich `"unavailable"` (plus eine Eintragung in `warnings`), wenn kein
Git-Kontext gefunden wird -- **niemals** eine erfundene Commit-ID. Die
JSON-Ausgabe hat sortierte Schlüssel, ist UTF-8, und enthält niemals
`NaN`-/`Infinity`-Werte (`json.dumps(..., allow_nan=False)` -- lässt die
Serialisierung lieber scheitern, als ungültiges JSON zu erzeugen).

**Wichtig**: ein Report ist ein reproduzierbarer Prüfdatensatz, **keine**
kryptografisch signierte Bescheinigung. Dateihash und Commitbindung
beweisen nicht allein die physische Sicherheit einer Bewegung -- sie
beweisen nur, WELCHER Code gegen WELCHE Datei gelaufen ist.

## Die drei Verdicts

```
Compiler-/Joint-/Timingfehler                      -> fail
mindestens ein Safety-Backend meldet fail           -> fail
Joint/Timing bestanden, aber kein echtes
  Kollisions-Backend (collision_checked=false)       -> inconclusive
alle Pflichtprüfungen inkl. echter Kollision bestanden -> pass
```

Mit dem aktuellen Standardvalidator
(`JointAndTimingValidator` + `DisabledCollisionBackend`, siehe
`trajectory_safety.py`) ist für **jede** fehlerfreie v2-Kataloggeste
`overall_verdict: inconclusive` mit `collision_checked: false` zu
erwarten -- das ist **kein Implementierungsfehler**, sondern der
ehrliche Sicherheitsstatus: es existiert kein echtes,
reproduzierbares Kollisions-/Abstandsbackend. Ein Test-Double mit
`collision_checked=True` (siehe
`test_gesture_offline_evidence.py::_TestDoubleFakeCollisionProofBackend`)
zeigt, dass der Mechanismus selbst korrekt funktioniert -- ein solches
Test-Double wird **niemals** als echtes Backend dokumentiert oder im
Standardpfad verwendet.

## Schema v1 (`t_pose`)

`verify-offline t_pose` lädt die Datei, prüft Metadaten und bekannte
Gelenkgrenzen, erzeugt einen Report -- täuscht aber **keine**
synchronisierte v2-Trajektorie vor und migriert v1 nicht automatisch.
Erwartetes Gesamturteil: `inconclusive`, mit
`requires_manual_review: ["legacy_v1_not_safely_interruptible"]`
(`LEGACY_V1_REASON`).

## Exitcodes

```
0 = pass
1 = fail, Schemafehler, ungültige Eingabe oder I/O-Fehler
2 = inconclusive
```

`validate-all`: mindestens ein `fail` (oder ein Ladefehler) → 1; kein
`fail`, aber mindestens ein `inconclusive` → 2; alle `pass` → 0. Der
aktuelle Katalog liefert wegen des fehlenden Kollisions-Backends
erwartbar Exitcode `2` -- bestätigt durch einen echten Lauf:

```text
$ ros2 run ihk_pepper_bridge gesturectl validate-all
...
Zusammenfassung: 24 geprueft, 0 pass, 24 inconclusive, 0 fail (0 Ladefehler uebersprungen).
$ echo $?
2
```

## Sicheres Schreiben des Reports

`--report` ist bei `verify-offline` verpflichtend. Eine bestehende
Reportdatei wird **nicht** still überschrieben (`write_report_atomically()`
nutzt dieselbe `os.link()`-basierte, race-sichere Exklusiv-Erzeugung wie
`capture-sequence`, siehe `docs/GESTURE_CAPTURE_WORKFLOW.md`) -- auch
`fail` und `inconclusive` werden als vollständiger Report festgehalten.

## Warum `inconclusive` weder ein Fehler noch eine Freigabe ist

`inconclusive` bedeutet: "kein bekannter Fehler gefunden, aber auch kein
vollständiger Sicherheitsnachweis erbracht" -- es erhöht **niemals**
automatisch `tested_status`. Auch ein späteres echtes `pass` bedeutet
nicht automatisch `dry_run_validated` oder `live_validated`: das bleibt
ein bewusster, manueller Schritt (siehe
`docs/GESTURE_LIVE_TEST_CHECKLIST.md`).

## Offene `hwverificationrequired`-Punkte

- Kein echtes, reproduzierbares Kollisions-/Abstands-Backend vorhanden
  (`DisabledCollisionBackend` bleibt Standard).
- `t_pose` bleibt historischer v1-Sonderfall, `production` strukturell
  gesperrt.
- `capture-sequence`s echter Lese-Pfad (`PepperJointStateSource`) wurde
  nur mit Test-Doubles geprüft, nicht gegen echte Hardware.
