# Gesture Kinematic Validation

Entwicklungsauftrag 04-B, AP8.4 (Grenzen/Timing) + AP8.5/AP8-R1.8
(Sicherheits-Report/Kollisions-Backend). Module:
`ihk_pepper_bridge/ihk_pepper_bridge/{kinematic_compiler,trajectory_safety}.py`.

## Was `KinematicCompiler.compile()` prüft (AP8.4, unverändert seit Commit 6/11)

Auf der **skalierten** (tatsächlich ausgeführten) Zeitachse:
Geschwindigkeit und Beschleunigung zwischen jedem Punktepaar, der
Übergang von der tatsächlichen Startpose zum ersten Keyframe (kein
impliziter t=0-Sprung), NaN/inf in Winkel/Zeit/`speed_scale`,
`max_duration_s` gegen die effektive Dauer, und ein fail-closed-Pfad für
einen teilweise fehlgeschlagenen Startpose-Snapshot (kein stilles
Ersetzen fehlender Werte durch `NEUTRAL_STAND_POSE`).

## `TrajectorySafetyValidator`: austauschbare Backends (AP8.5)

`TrajectorySafetyReport` fasst das Ergebnis eines oder mehrerer
`TrajectorySafetyBackend`-Läufe zusammen (`pass`/`fail`/`inconclusive`).
`JointAndTimingValidator` (Pflicht-Backend) übersetzt das
Compiler-Ergebnis in diesen Report und ergänzt dokumentierende (nicht
geometrisch berechnete) Hinweisflaggen für besonders sorgfältig zu
behandelnde Kategorien: Hüfte/Knie, gleichzeitige Torso+Arm-Bewegung,
bilaterale Armbewegung, kombinierte Kopf+Arm-Bewegung, und einen festen
Hinweis für `self_hug_symbolic` ("bleibt kontaktlos").

## Ohne echtes Kollisions-Backend ist der Standardreport `inconclusive` (AP8-R1.8)

**Bestätigter Fund (AP8-R1, Abschnitt 3.7):** der Standardpfad nutzte
bisher nur `JointAndTimingValidator` -- ein Report konnte damit
gleichzeitig `verdict=pass` und `collision_checked=false` melden, was
wie ein (nicht vorhandener) Kollisionsnachweis wirkt.
`TrajectorySafetyValidator()` konstruiert seit AP8-R1 standardmäßig
**beide** Backends: `JointAndTimingValidator` + `DisabledCollisionBackend`.
`DisabledCollisionBackend` macht ausdrücklich **keine** Kollisionsaussage
(in dieser Umgebung ist kein `trimesh`/`fcl`/`pinocchio` installiert,
obwohl unter `ros2/robot_model/src/pepper_description/urdf/pepper.urdf`
ein echtes URDF existiert) -- der Gesamtreport ist deshalb ohne ein
echtes Kollisions-Backend strukturell `inconclusive`, niemals `pass`.

`GestureCatalog._play_v2()` nutzt `TrajectorySafetyValidator` jetzt
direkt (statt den Compiler roh aufzurufen) und erzwingt bei
`require_collision_proof=True` (von `bridge_node.py` gesetzt, wenn
`execution_profile == production`), dass **auch** ein `inconclusive`
die Ausführung verweigert -- nicht nur `fail`. `offline_mock`/
`offline_preview`/`supervised_hardware_test` dürfen `inconclusive`
ausdrücklich ausführen/anzeigen (mit sichtbarem Hinweis, siehe
`gesturectl preview-trajectory`).

Ein austauschbarer Injektionspunkt (`PepperBridgeNode.gesture_safety_validator`,
`GestureCatalog.play(..., safety_validator=...)`) erlaubt, ein
zukünftiges echtes Kollisions-Backend einzusetzen, ohne
`gesture_catalog.py`/`bridge_node.py` sonst zu ändern.

## Vertrauensgrenze bei vorkompilierten Plänen (AP8-R1.8)

`TrajectorySafetyValidator.validate(..., plan=plan)` behandelt einen von
außen übergebenen `TrajectoryPlan` **nicht** blind als gültig für die
gegebene Geste. `_plan_matches_gesture()` prüft Gestenname, Gelenkmenge
und (bei bekanntem `speed_scale`) die aus Geste+`speed_scale` erwartete
effektive Dauer gegen den übergebenen Plan -- eine Abweichung wird wie
ein Kompilierfehler behandelt (`verdict=fail`), nicht stillschweigend
durchgereicht. Innerhalb von `gesture_catalog.py::_play_v2()` ist das
unkritisch (derselbe Plan wird im selben Aufruf kompiliert und sofort
weitergereicht), schützt aber jeden anderen Aufrufer, der einen
Fremd-Plan einspeisen könnte.
