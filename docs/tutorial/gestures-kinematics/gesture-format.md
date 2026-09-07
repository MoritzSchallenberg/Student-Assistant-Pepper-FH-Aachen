# Gestenformat

{{ documented }}

## Was diese Seite ist

Das reale v2-Gesten-Schema, seine Validierungsregeln beim Laden, und die
kinematische Pipeline, die aus einer YAML-Datei eine tatsächlich
gesendete Trajektorie macht.

## Die harte Grenze zuerst: Peppers Hand

{{ pepper }} Pepper hat **nur 1 Motor pro Hand** (auf/zu) — keine
einzelnen Finger, kein Fingerzeigen, keine Peace-Zeichen. Jede
"Zeige"-Geste in diesem Katalog ist deshalb eine Ganzarm-Bewegung
Richtung einer Seite/des eigenen Körpers, **nie** ein tatsächliches
Zeigen mit dem Finger — siehe
{ref}`Gestenkatalog <point_to_self>` für ein konkretes
Beispiel.

## Zwei Schema-Versionen

**v1** (Feld `schema_version` fehlt = 1): sequenzielle Einzelgelenk-
Schritte, unverändert seit der ursprünglichen Implementierung — bewusst
so belassen, eine automatische Umwandlung hätte die bereits live
getestete Timing-Semantik verändert.

**v2** (`schema_version: 2`): zeitbasierte, **synchrone**
Ganzkörper-Keyframes — der Gegenstand dieser Seite.

```yaml
schema_version: 2
name: raise_both_arms
description: "..."
requires_stationary: true       # sperrt Ausfuehrung waehrend Nav2-Bewegung
allowed_interaction_states: [IDLE, ATTRACT, CONVERSATION_READY]
speed_scale_default: 0.6
restore_after: true
tested_status: dry_run_validated  # draft | dry_run_validated | live_validated
tested_date: "2026-09-04"
test_note: "..."
max_duration_s: 3.0
on_cancel: restore               # restore | hold
keyframes:
  - time_from_start_s: 2.0
    joints: {LShoulderPitch: -1.0, RShoulderPitch: -1.0}
```

Ein Keyframe braucht nicht alle Gelenke der Geste zu enthalten — ein
Gelenk, das nur in einem Keyframe vorkommt, bekommt genau ein
Zielwinkel-/Zeitpunkt-Paar.

## Validierung beim Laden

- `time_from_start_s` muss **streng monoton steigend** sein.
- Jedes referenzierte Gelenk muss in `ALLOWED_GESTURE_JOINTS` stehen --
  unbekannte Gelenke werden (anders als bei v1) **abgelehnt**.
- Jeder Winkel muss innerhalb der Gelenkgrenze **mit Sicherheitsmarge**
  liegen (`SAFETY_MARGIN_RAD = 0.05`).
- Geschwindigkeit zwischen zwei Keyframes desselben Gelenks darf
  `MAX_JOINT_VELOCITY_RAD_S = 3.0` nicht überschreiten -- diese Zahl ist
  nicht frei gewählt: die live getestete `wave_*`-Oszillation braucht
  exakt 2,5 rad/s, die Grenze liegt knapp darüber.

## Reale Gelenkgrenzen (Pepper 1.8, `joint_limits.py`)

```{list-table}
:header-rows: 1
:widths: 22 20 20 38

* - Gelenk
  - Min (rad)
  - Max (rad)
  - live-geprüft?
* - `HeadYaw`
  - −2.0857
  - 2.0857
  - nein
* - `HeadPitch`
  - −0.7068
  - 0.4451
  - nein
* - `LShoulderPitch`
  - −2.0857
  - 2.0857
  - nein
* - `LShoulderRoll`
  - 0.0087
  - 1.5620
  - **ja**
* - `LElbowRoll`
  - −1.5620
  - 0.05
  - nein
* - `LWristYaw`
  - −1.8239
  - 1.8239
  - **ja**
* - `RShoulderRoll`
  - −1.5620
  - −0.0087
  - **ja**
* - `RElbowRoll`
  - −0.05
  - 1.5620
  - nein
* - `RWristYaw`
  - −1.8239
  - 1.8239
  - **ja**
* - `HipRoll`
  - −0.5149
  - 0.5149
  - nein
* - `HipPitch`
  - −1.0385
  - 1.0385
  - nein
* - `KneePitch`
  - −0.5149
  - 0.5149
  - nein
```

(Vollständige Liste inkl. `LHand`/`RHand`/`ElbowYaw`-Gelenke in
`ihk_pepper_bridge/joint_limits.py`.) **Live-geprüft** bedeutet: per
`qicli call ALMotion.getLimits <Gelenk>` während einer früheren Session
direkt am echten Roboter abgefragt. Alle anderen Werte stammen aus der
öffentlichen Aldebaran/SoftBank-NAOqi-Dokumentation und wurden **nicht**
live nachgemessen — vor sicherheitskritischer Nutzung gegenprüfen.

**Ein bereits gefundener und korrigierter Dokumentationsfehler**:
`LElbowRoll`/`RElbowRoll` widersprachen ursprünglich einer bereits live
mehrfach erfolgreich getesteten T-Pose-Sequenz (`LElbowRoll=0.0`) --
beim Gestenkatalog-Test aufgefallen und korrigiert. Ein konkretes
Beispiel dafür, warum "Dokumentationswert" und "live bestätigter Wert"
zwei verschiedene Dinge sind.

## Die kinematische Pipeline

```{figure} ../_static/images/gesture-validation-flow.svg
:alt: Gesture-YAML wird beim Laden gegen joint_limits validiert, dann vom KinematicCompiler zu einem TrajectoryPlan mit einheitlicher Zeitachse kompiliert, dann von einem MotionTransport (Mock, DryRun oder Qicli) ausgeführt.
:width: 100%

Jede Stufe kann unabhängig fehlschlagen -- ein Fehlschlag propagiert
immer, es gibt keinen Pfad, der einen fehlgeschlagenen Transport als
Erfolg vortäuscht.
```

```text
Gesture (YAML, validiert beim Laden)
  → KinematicCompiler.compile()
  → TrajectoryPlan (vollständig aufgelöst, EINE Zeitachse je Gelenk)
  → MotionTransport (prepare → start → poll/wait → restore)
  → Pepper (QicliTrajectoryTransport) oder Mock/Dry-Run
```

Der `KinematicCompiler` behebt drei Schwächen des ursprünglichen
direkten Mappings:

1. **Fehlende Gelenke pro Keyframe**: füllt jeden Keyframe auf --
   Haltewert = letzter bekannter Wert, oder `start_pose`/
   `NEUTRAL_STAND_POSE`-Fallback.
2. **Undefinierter Startzustand**: ohne `start_pose` fällt der Compiler
   auf `NEUTRAL_STAND_POSE` zurück -- niemals "aktuelle Ist-Position
   unbekannt".
3. **Inkonsistente Zeitachsen**: jedes Gelenk bekommt danach exakt
   dieselbe Zeitliste.

Zusätzlich, nach Anwendung des `speed_scale`: **Beschleunigungsprüfung**
(`MAX_JOINT_ACCEL_RAD_S2 = 25.0`) -- eine bei `speed_scale=1.0`
unauffällige Geste kann bei hohem `speed_scale` beschleunigungsseitig
unzulässig werden.

## Motion Transport: vier Implementierungen

```{list-table}
:header-rows: 1
:widths: 26 74

* - Transport
  - Verhalten
* - `MockMotionTransport`
  - Reine Buchführung für Tests, keine Hardwareaktion.
* - `DryRunMotionTransport`
  - Loggt den vollständigen Plan, ruft **nie** eine Hardware-Methode auf
    -- auch `restore()`/`cancel()` bleiben reine Protokollausgaben.
* - `QicliTrajectoryTransport`
  - Echter Transport über `ThreadSafePepperClient`. `restore()` sendet
    **einen** synchronen Aufruf für alle Gelenke (behebt den
    Gelenk-für-Gelenk-Fehler der alten Implementierung).
    `cancel()` hat **kein** natives Mid-Flight-Abbrechen -- wartet auf
    das Ende des laufenden Aufrufs und sendet danach sofort eine
    Halte-Trajektorie. Ehrlich als Näherung dokumentiert.
* - `LocalPepperQiHelperTransport`
  - Dokumentierter, **nicht implementierter** Platzhalter für eine
    künftige direkte NAOqi-SDK-Anbindung -- jede Methode wirft bewusst
    `NotImplementedError`.
```

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} `KinematicCompiler`/`QicliTrajectoryTransport` sind
**dry_run_validated, NICHT live_validated** — kein Pepper-Zugriff für
diese Prüfung verfügbar. 20+ Unit-Tests decken Compiler und Transport ab.

## Nächster Schritt

[Gestenkatalog](gesture-catalog.md).
