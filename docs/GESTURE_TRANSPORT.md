# Gesten-Transport-Architektur

Stand: 2026-09-09. Entwicklungsauftrag 3, AP12; Cancel-Architektur
aktualisiert in Entwicklungsauftrag 04-B, AP5B (siehe
`docs/ACTION_CANCELLATION.md` für die vollstaendige Abbruch-Kette
ueber alle Schichten hinweg -- dieses Dokument beschreibt nur die
Transport-Ebene).
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_bridge/ihk_pepper_bridge/
kinematic_compiler.py`, `motion_transport.py`, `pepper_client.py`
(`PepperInterruptChannel`). Siehe auch `docs/GESTURE_AUTHORING.md` für
das Katalog-YAML-Format.

## Pipeline

```
Gesture (YAML, validiert beim Laden)
    -> KinematicCompiler.compile()
    -> TrajectoryPlan (vollstaendig aufgeloest, EINE Zeitachse je Gelenk)
    -> MotionTransport (prepare -> start -> poll/wait -> restore)
    -> Pepper (QicliTrajectoryTransport) ODER Mock/Dry-Run
```

Betrifft ausschließlich `schema_version: 2`-Gesten. v1-Gesten (sequenzielle
Einzelgelenk-Schritte) laufen weiterhin unveraendert über
`GestureCatalog._play_v1()` -- bewusste, seit Auftrag 1 bestehende
Design-Entscheidung, siehe `gesture_catalog.py`-Moduldoku.

## KinematicCompiler

Nimmt eine geladene `Gesture` (bereits gegen `joint_limits.py` validiert)
sowie optional einen `start_pose` (typischerweise ein
`pepper_client.snapshot_joints()`-Ergebnis) entgegen und gibt einen
`TrajectoryPlan` zurück. Behebt drei Schwächen des ursprünglichen direkten
Keyframe→`play_trajectory()`-Mappings:

1. **Fehlende Gelenke pro Keyframe**: `fill_missing_joint_holds()` (reine
   Funktion) füllt jeden Keyframe so auf, dass JEDES betroffene Gelenk
   einen Wert hat -- Haltewert = letzter bekannter Wert, oder `start_pose`/
   `NEUTRAL_STAND_POSE`-Fallback, falls das Gelenk noch nie vorkam.
2. **Undefinierter Startzustand**: ohne `start_pose` fällt der Compiler
   auf `NEUTRAL_STAND_POSE` zurück (dieselben Werte wie die Geste
   `neutral_stand.yaml`) -- niemals "aktuelle Ist-Position unbekannt".
3. **Inkonsistente Zeitachsen**: JEDES Gelenk bekommt danach exakt
   dieselbe Zeitliste (vorher konnte ein Gelenk, das nicht in jedem
   Keyframe vorkam, faktisch eine andere Zeitachse als ein anderes
   Gelenk im selben `play_trajectory()`-Aufruf bekommen).

Zusätzlich geprüft, NACH Anwendung des `speed_scale`:
- **Beschleunigung** (`MAX_JOINT_ACCEL_RAD_S2 = 25.0`, finite Differenzen
  zweiter Ordnung) -- ein hoher `speed_scale` kann eine an sich
  unauffällige Geste beschleunigungsseitig unzulässig machen.
- **Verteidigung in der Tiefe**: auch synthetisch aufgefüllte Haltewerte
  (aus `start_pose`/`NEUTRAL_STAND_POSE`) werden nochmal mit
  `validate_angle_with_margin()` geprüft, nicht nur die wörtlich in der
  YAML stehenden Werte.

`compile()` lehnt v1-Gesten mit `KinematicCompileError` ab.

## MotionTransport

Abstrakte Schnittstelle: `prepare(plan, restore_snapshot) -> start() ->
poll()/wait() -> restore()`, `cancel(timeout_s=DEFAULT_CANCEL_TIMEOUT_S)
-> CancelResult` jederzeit dazwischen aufrufbar.

Seit AP5B liefert `cancel()` ein strukturiertes `CancelResult`
(`cancel_requested`, `cancel_confirmed`, `final_transport_state`,
`elapsed_s`, `error_message`) statt eines bloßen `None` -- ersetzt das
vorherige, potenziell UNBEGRENZTE Warten auf das Ende einer laufenden
synchronen Trajektorie (bestätigter Fund: `cancel()` konnte bei einer
laufenden Anfrage beliebig lange blockieren, bevor überhaupt eine
Halte-Trajektorie gesendet wurde). `cancel_confirmed=True` bedeutet NUR,
dass der Transport-Zustand als beendet beobachtet wurde -- keine Aussage
darüber, ob Pepper sich tatsächlich bewegt hat (siehe
`docs/ACTION_CANCELLATION.md`).

- **`MockMotionTransport`**: reine Buchführung für Tests, keine
  Hardwareaktion.
- **`DryRunMotionTransport`**: loggt den vollständigen Plan, ruft
  NIEMALS eine Hardware-Methode auf -- auch `restore()`/`cancel()`
  bleiben reine Protokollausgaben. Genutzt von `GestureCatalog.play(...,
  dry_run=True)` und (AP14) `gesturectl dry-run`.
- **`QicliTrajectoryTransport`**: echter Transport über
  `ThreadSafePepperClient`. `start()` sendet die Trajektorie in einem
  Hintergrund-Thread; `poll()`/`wait()` lesen den Fortschritt, ohne den
  Aufrufer zu blockieren. **`restore()`** sendet EINEN synchronen
  `play_trajectory()`-Aufruf für ALLE wiederherzustellenden Gelenke --
  behebt den ursprünglichen Fehler in `apps/web/pepper/qicli.py::
  restore_joints()` (dort weiterhin Gelenk für Gelenk in einer Schleife,
  bewusst NICHT verändert, da von `apps/web`/Flask-Server mitgenutzt;
  weiterhin von v1-Gesten verwendet).

  **`cancel()` (AP5B)**: nimmt optional einen `interrupt_channel`
  entgegen (`pepper_client.py::PepperInterruptChannel` -- eine ZWEITE,
  vom Hauptkanal unabhängige SSH-Verbindung + eigenes `threading.RLock`,
  ausschließlich für `stop_motion()`/`stop_speech()`/
  `send_hold_position()`). Ohne `interrupt_channel` (ältere
  Aufrufer/Tests) bleibt es ein reines Best-Effort-Warten auf das
  natürliche Ende der laufenden Anfrage, jetzt aber BEGRENZT
  (`timeout_s`, Standard 2.0s) statt unbegrenzt. MIT
  `interrupt_channel` wird zusätzlich sofort ein `stop_motion()` über den
  zweiten Kanal gesendet -- der Hauptkanal kann dabei weiterhin hinter
  der ursprünglichen synchronen Anfrage blockiert sein, der Abbruchbefehl
  selbst wird davon nie blockiert. `qicli` selbst bietet weiterhin KEIN
  natives Mid-Flight-Abbruch-Primitiv (kein async Task/Cancel, siehe
  `docs/ACTION_CANCELLATION.md`, Abschnitt "Fähigkeitstest") -- der
  zweite Kanal verkürzt die Reaktionszeit, verwandelt es aber nicht in
  einen echten Hardware-Abbruch. Ehrlich als Best-Effort dokumentiert,
  Hardwarepfad als `hwverificationrequired` markiert.
- **`LocalPepperQiHelperTransport`**: dokumentierter, NICHT
  implementierter Platzhalter für eine künftige direkte NAOqi-SDK-
  Anbindung (statt SSH+`qicli`). Jede Methode wirft `NotImplementedError`.

## GestureCatalog.play() (AP5B)

`play()`/`_play_v1()`/`_play_v2()` nehmen jetzt optional
`cancel_event: threading.Event` und `interrupt_channel` entgegen --
beide Parameter sind rückwärtskompatibel (Standard `None` erhält das
Verhalten vor AP5B exakt). `bridge_node.py::_execute_gesture()` reicht
seinen eigenen Cancel-Event/Interrupt-Kanal durch, sodass eine im
Hintergrundthread laufende Geste aktiv abgebrochen werden kann, statt
nur bis zum natürlichen Ende zu laufen.

## Startpose unabhängig von restore_after (Entwicklungsauftrag 04-B, AP8-R1.2)

**Bestätigter Fund (AP8-R1, Abschnitt 3.2):** die Startpose wurde bisher
nur gelesen, wenn `gesture.restore_after == true`. Bei `restore_after:
false` (z.B. `neutral_stand.yaml`, `look_at_person.yaml`) kompilierte
`GestureCatalog._play_v2()` deshalb gegen `NEUTRAL_STAND_POSE`, obwohl
Pepper real in einer anderen Haltung stehen konnte -- gerade
`neutral_stand` soll Pepper aus einer möglicherweise NICHT neutralen
Haltung heraus in die Neutralpose bringen, was ohne echte Startpose
weder hinsichtlich Geschwindigkeit noch Gelenkbewegung korrekt geprüft
werden kann.

`_play_v2()` erfasst die Startpose jetzt **immer** vor jeder realen
v2-Hardwareausführung (unabhängig von `restore_after`), validiert sie
über denselben `KinematicCompiler`-Pfad (fail-closed bei fehlendem/
`None`/NaN/inf-Wert für ein benötigtes Gelenk, siehe
`docs/GESTURE_KINEMATIC_VALIDATION.md`), und übergibt **denselben**
geprüften Snapshot sowohl an den Compiler als auch (nur wenn
`restore_after=true`) als `restore_snapshot` an den Transport.
`restore_after` entscheidet damit ausschließlich, ob die erfasste Pose
**später** als Restore-Ziel verwendet wird -- nicht mehr, ob sie
überhaupt gelesen wird. `NEUTRAL_STAND_POSE` bleibt nur noch als
injizierte Simulationsannahme in Offline-Modi/Tests zulässig, wenn gar
kein `start_pose` übergeben wird.

## Status

`QicliTrajectoryTransport`/`KinematicCompiler` sind **dry_run_validated,
NICHT live_validated** -- kein Pepper-Zugriff in dieser Session möglich.
Der `PepperInterruptChannel`/die begrenzte `cancel()`-Bestätigung sind
ebenfalls nur gegen Mocks getestet (`hwverificationrequired`) -- ob ein
echter zweiter SSH-Kanal auf echter Hardware tatsächlich schneller
reagiert als der Hauptkanal, ist NICHT verifiziert. 20+ unit-getestete
Fälle in `test_kinematic_compiler.py`/`test_motion_transport.py` (siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md`, AP12), erweitert um die
Cancel-/`interrupt_channel`-Tests aus AP5B (siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`).
