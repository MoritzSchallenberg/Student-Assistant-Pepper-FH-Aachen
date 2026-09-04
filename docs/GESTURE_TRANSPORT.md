# Gesten-Transport-Architektur

Stand: 2026-09-04. Entwicklungsauftrag 3, AP12.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_bridge/ihk_pepper_bridge/
kinematic_compiler.py`, `motion_transport.py`. Siehe auch
`docs/GESTURE_AUTHORING.md` für das Katalog-YAML-Format.

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
poll()/wait() -> restore()`, `cancel()` jederzeit dazwischen aufrufbar.

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
  weiterhin von v1-Gesten verwendet). **`cancel()`** hat KEIN natives
  Abbruch-Primitiv für eine bereits an NAOqi gesendete synchrone Anfrage
  -- wartet auf deren Ende und sendet danach sofort eine
  Halte-Trajektorie (aktuelle Ist-Position, kurze Dauer). Ehrlich als
  Näherung dokumentiert, kein echtes Mid-Flight-Abbrechen.
- **`LocalPepperQiHelperTransport`**: dokumentierter, NICHT
  implementierter Platzhalter für eine künftige direkte NAOqi-SDK-
  Anbindung (statt SSH+`qicli`). Jede Methode wirft `NotImplementedError`.

## Status

`QicliTrajectoryTransport`/`KinematicCompiler` sind **dry_run_validated,
NICHT live_validated** -- kein Pepper-Zugriff in dieser Session möglich.
20 unit-getestete Fälle in `test_kinematic_compiler.py`/
`test_motion_transport.py` (siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md`, AP12).
