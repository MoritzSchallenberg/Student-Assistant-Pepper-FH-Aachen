# Rein lesende Bewegungsaufnahme (`gesturectl capture-sequence`)

Stand: 2026-09-12. Entwicklungsauftrag 04-B, AP8.7, Commit 12/14.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_bridge/ihk_pepper_bridge/joint_state_source.py`,
`gesture_capture.py`, `gesturectl.py` (Unterbefehle `capture-pose`,
`capture-sequence`).

## `capture-pose` vs. `capture-sequence`

| | `capture-pose` | `capture-sequence` |
|---|---|---|
| Zweck | EIN aktueller Gelenkwinkel-Snapshot, nur zur Anzeige | Mehrere Zeitpunkte -> eine sichere v2-Gestenkandidatin |
| Ausgabe | Text auf stdout | YAML-Datei (Kandidat, `tested_status: draft`) |
| Schreibt eine Datei | Nein | Ja, nur die ausdrücklich angeforderte `--output`-Datei |

Beide sind **strukturell rein lesend**: keine Bewegung, keine
Steifigkeitsänderung, keine ROS-Action, kein Aktuator-Lease, keine
automatische Ausführung. Beide nutzen dieselbe gehärtete
Gelenkargument-Validierung (`gesture_capture.py::
parse_and_validate_joint_list()`) und dieselbe read-only
`PepperJointStateSource`-Abstraktion (`joint_state_source.py`) -- EIN
Prüfpfad statt zwei unabhängiger Implementierungen.

## Der echte Lese-Pfad ist `hwverificationrequired`

`capture-sequence` **darf technisch** später gegen einen echten Pepper
laufen (`PepperJointStateSource` ruft ausschließlich
`ThreadSafePepperClient.get_angle()` auf), wurde in diesem Auftrag aber
**ausschließlich mit Test-Doubles geprüft** (siehe
`test_joint_state_source.py`, `test_gesture_capture.py`,
`test_gesturectl.py`). Kein echter SSH-/qicli-Zugriff fand statt. Jede
erzeugte Kandidatendatei trägt deshalb
`metadata.capture.hardware_validation: hwverificationrequired`.

## Read-only-Abstraktion (`joint_state_source.py`)

```python
class JointStateReading:
    values: dict                          # {gelenk: winkel_oder_None}
    acquisition_started_monotonic_s: float
    acquisition_finished_monotonic_s: float
    source_backend: str
    acquisition_mode: str                 # "sequential_per_joint" | "batch"
```

`PepperJointStateSource` hält **ausschließlich** die gebundene
`get_angle`-Funktion des Pepper-Clients, nicht den Client selbst -- ein
struktureller (nicht nur verhaltensbasierter) Beweis, dass `set_angle`,
`play_trajectory`, `restore_joints`, `set_breathing`, `set_stiffness`,
`stop_motion` von diesem Objekt aus **nicht erreichbar** sind (siehe
`test_read_never_reaches_a_movement_method`).

## Sequenziell, nicht zeitgleich (bestätigter Fund 4.3)

`apps/web/pepper/qicli.py::get_angles()` liest aktuell **nacheinander**
ein `get_angle()`-SSH-Kommando je Gelenk (kein Batch-`ALMemory`-Aufruf).
`acquisition_mode = "sequential_per_joint"` dokumentiert das ehrlich --
eine echte Batchmessung darf erst nach technischer Implementierung UND
Hardwareverifikation als solche bezeichnet werden. `maximum_sample_span_s`
zeigt die tatsächliche Zeitspanne innerhalb eines Mehrgelenk-Samples.

## Gelenk-Allowlist und Härtung gegen Befehlsinjektion

`--joints` wird **vor jedem Netzwerk-/Client-Zugriff** geprüft:
Kommagetrennt, getrimmt, jeder Name muss exakt in
`joint_limits.ALLOWED_GESTURE_JOINTS` stehen (keine Chain-Namen wie
`Body`/`Head`/`Arms`, keine freien qicli-Fragmente), keine Duplikate,
keine leeren Elemente. Da `ALLOWED_GESTURE_JOINTS` ausschließlich
einfache alphanumerische Bezeichner enthält, schließt diese
Mengenzugehörigkeitsprüfung eine Befehlsinjektion über `--joints`
strukturell aus, bevor der Name je in eine SSH-/qicli-Zeichenkette
eingesetzt werden könnte. Die Ausgabereihenfolge ist alphabetisch
sortiert (deterministisch, unabhängig von der Eingabereihenfolge).

## Zeitachse: tatsächlich, nicht ideal

Jede Zeitangabe basiert auf `time.monotonic()` -- niemals auf einer
idealen Sollzeit. Der erste gültige Messpunkt wird zu
`time_from_start_s: 0.0`, alle folgenden Zeiten sind relativ dazu und
müssen **streng monoton** steigen; ein Rundungsfehler, der
Zeitgleichheit erzeugen würde, bricht die Aufnahme fail-closed ab.
Angeforderte (`requested_sample_rate_hz`) und tatsächlich erreichte
(`achieved_sample_rate_hz`) Samplingrate werden getrennt dokumentiert.

## Fail-closed bei jeder ungültigen Messung

Jede der folgenden Bedingungen bricht die Aufnahme sofort ab, OHNE eine
Datei zu schreiben: fehlendes Gelenk in einem Sample, `None`, NaN, inf,
ein nicht-numerischer Wert, ein Wert außerhalb der Gelenkgrenze (mit
Sicherheitsmarge), eine nicht streng monotone Zeitachse, ein
Verbindungsabbruch, `Ctrl+C`. Es wird **niemals** geglättet,
interpoliert, geklemmt oder ein fehlendes Sample erfunden.

## Sicheres, atomares Schreiben

Die Zieldatei wird erst nach vollständiger Aufnahme, erfolgreichem
Testladen (`GestureCatalog`/`Gesture`) UND erfolgreichem Testkompilieren
(`KinematicCompiler`, mit der erfassten Startpose) geschrieben.
`gesture_capture.py::atomic_create_exclusive()` nutzt `os.link()`
(POSIX-atomar) statt `os.rename()` -- eine bestehende Zieldatei wird
**niemals** ersetzt, auch nicht bei einem Race zwischen zwei
gleichzeitigen Aufrufen. Zusätzlich geprüft, bevor überhaupt ein
Pepper-Client erzeugt wird: Dauer/Samplingrate endlich und positiv,
resultierende Samplezahl begrenzt (`MAX_CAPTURE_SAMPLE_COUNT = 1000`),
`--output` endet auf `.yaml`, liegt nicht im aktiven Produktionskatalog,
existiert noch nicht.

## Kandidatenformat

```yaml
schema_version: 2
name: <sicher, aus --output abgeleitet oder --name>
description: "Read-only erfasste Gestenkandidatin; noch nicht validiert."
system_only: false
selectable_by_llm: false
semantic_tags: []
tested_status: draft
tested_date:
test_note: "Rein lesend erfasst; kein Dry-Run und kein Hardwaretest."
requires_stationary: true
allowed_interaction_states: [IDLE]
speed_scale_default: 0.4
max_duration_s: <deterministisch aus Zeitachse/speed_scale abgeleitet>
on_cancel: hold
restore_after: true
disable_breathing: []
metadata:
  capture:
    schema_version: 1
    source_backend: qicli_ssh
    acquisition_mode: sequential_per_joint
    captured_at_utc: "<ISO-8601>"
    time_base: monotonic
    requested_sample_rate_hz: <wert>
    achieved_sample_rate_hz: <wert>
    requested_duration_s: <wert>
    actual_duration_s: <wert>
    sample_count: <wert>
    joints: [...]
    maximum_sample_span_s: <wert>
    hardware_validation: hwverificationrequired
    start_pose: {<gelenk>: <winkel>, ...}
    start_pose_fingerprint: <hash>
keyframes: [...]
```

`speed_scale_default: 0.4` ist die bereits dokumentierte Obergrenze für
den ersten beaufsichtigten v2-Test (siehe
`docs/GESTURE_LIVE_TEST_CHECKLIST.md`) -- **keine neue
Hardwarefreigabe**. `max_duration_s` wird deterministisch aus der
erfassten (unskalierten) Zeitachse UND `speed_scale_default` abgeleitet
(`effektive Dauer = raw_zeit / speed_scale`, plus eine kleine, feste
Marge) -- **nicht** aus der unskalierten Achse selbst übernommen (das
war ein an mehreren echten Kataloggesten bereits korrigierter Fehler,
siehe AP8.4/`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`).

## Startposebindung

Die erste vollständige Messung bildet die dokumentierte
Capture-Startpose (`metadata.capture.start_pose` -- die tatsächlichen
Winkelwerte -- plus `start_pose_fingerprint`, ein Hash zur
Integritätsprüfung). Diese Startpose:

- wird von `gesturectl verify-offline` als Startposequelle
  `captured_metadata` verwendet (siehe
  `docs/GESTURE_OFFLINE_EVIDENCE.md`),
- ist **kein Ersatz** für den frischen Hardware-Snapshot vor einer
  späteren Ausführung,
- garantiert **nicht**, dass Pepper bei einem späteren Test wieder in
  derselben Pose steht.

Eine spätere Hardwareausführung muss weiterhin den vollen
AP8-R1-/AP8-R2-Startposecheck bestehen (`_validate_full_snapshot()` in
`gesture_catalog.py`).

## Datenschutz und Artefakthygiene

Eine Kandidatendatei enthält ausschließlich Gelenk-, Zeit- und
Werkzeugdaten -- keinen Bedienernamen, keine Personendaten, kein Audio/
Bild/Video, keine Zugangsdaten, keinen vollständigen lokalen Dateipfad.
Reale Capture-Dateien werden **nicht automatisch versioniert** --
eingecheckte Testfixtures (in `test_gesture_capture.py`/
`test_gesturectl.py`) sind ausschließlich synthetisch.

## Was `capture-sequence` NICHT tut

- keine Bewegung, keine Steifigkeitsänderung,
- keine automatische Ausführung der Aufnahme,
- keine automatische Aufnahme in den Produktionskatalog,
- keine automatische Reindexierung des Gesture-Memory-Index,
- keine automatische Statusänderung (`tested_status` bleibt immer
  `draft`, bis ein Mensch es nach einer beaufsichtigten Prüfung bewusst
  ändert).

## Nächster Schritt nach einer Aufnahme

```bash
gesturectl --gesture-dir <candidate-dir> validate <name>
gesturectl --gesture-dir <candidate-dir> dry-run <name>
gesturectl --gesture-dir <candidate-dir> verify-offline <name> --report /tmp/<name>.json
```

Siehe `docs/GESTURE_OFFLINE_EVIDENCE.md` für den vollständigen
Evidenzreport.
