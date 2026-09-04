# Gesten anlegen (Katalog v2)

Stand: 2026-09-04. Ursprünglich Entwicklungsauftrag 1, Abschnitt 7;
Compiler/Transport-Architektur und 12 neue Gesten aus Entwicklungsauftrag 3,
AP12+AP13 ergänzt (siehe docs/DEVELOPMENT_ORDER_03_REPORT.md).
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_bridge/ihk_pepper_bridge/gesture_catalog.py`,
`kinematic_compiler.py`, `motion_transport.py`, `joint_limits.py`,
`pepper_client.py`; Katalog-Dateien:
`ros2/autonomy_ws/src/ihk_pepper_bridge/config/gestures/*.yaml`.

## Zwei Schema-Versionen

**v1** (Feld `schema_version` fehlt = 1): sequenzielle Einzelgelenk-
Schritte, unverändert seit der ursprünglichen Implementierung. Bleibt
bewusst so -- eine automatische Umwandlung in "Keyframes" hätte die
bereits live getestete Timing-Semantik verändert, ohne echten Gewinn.

**v2** (`schema_version: 2`): zeitbasierte, **synchrone** Ganzkörper-
Keyframes -- der eigentliche Gegenstand dieses Auftrags.

```yaml
schema_version: 2
name: raise_both_arms
description: "..."
requires_stationary: true                 # sperrt Ausfuehrung waehrend Nav2-Bewegung
allowed_interaction_states: [IDLE, ATTRACT, CONVERSATION_READY]
speed_scale_default: 0.6
restore_after: true
tested_status: dry_run_validated           # draft | dry_run_validated | live_validated
tested_date: "2026-09-04"
test_note: "..."
max_duration_s: 3.0
on_cancel: restore                          # restore | hold
keyframes:
  - time_from_start_s: 2.0
    joints: {LShoulderPitch: -1.0, RShoulderPitch: -1.0}
```

Ein Keyframe braucht nicht alle Gelenke der Geste zu enthalten -- ein
Gelenk, das nur in EINEM Keyframe vorkommt, bekommt genau EIN
Zielwinkel/-zeitpunkt-Paar. NAOqis `ALMotionProxy.angleInterpolation`
unterstützt das nativ (pro Gelenk eine eigene, unterschiedlich lange
Zeit-/Winkel-Liste in einem einzigen synchronen Aufruf).

## Validierung beim Laden (`GestureCatalog.reload()`)

- `time_from_start_s` muss **streng monoton steigend** sein, über alle
  Keyframes hinweg.
- Jedes referenzierte Gelenk muss in `joint_limits.ALLOWED_GESTURE_JOINTS`
  stehen -- unbekannte Gelenke werden (anders als bei v1) **abgelehnt**,
  nicht durchgereicht.
- Jeder Winkel muss innerhalb der Gelenkgrenze **mit Sicherheitsmarge**
  liegen (`joint_limits.SAFETY_MARGIN_RAD = 0.05`,
  `validate_angle_with_margin()`).
- Geschwindigkeit zwischen zwei Keyframes desselben Gelenks darf
  `MAX_JOINT_VELOCITY_RAD_S = 3.0` nicht überschreiten -- diese Zahl ist
  **nicht** frei gewählt: die bereits live getestete `wave_*`-Oszillation
  braucht exakt 2.5 rad/s (1.0 rad in 0.4s), die Grenze liegt knapp
  darüber, damit dieser bewiesene Fall nicht fälschlich abgelehnt wird.
- `tested_status` muss einer von `draft`/`dry_run_validated`/
  `live_validated` sein.

## Sperren beim Abspielen (`GestureCatalog.play()`)

- `current_interaction_state` gesetzt und außerhalb von
  `allowed_interaction_states` → abgelehnt.
- `nav2_moving=True` und Geste ist v2 (oder `requires_stationary`) →
  abgelehnt ("Arm-/Kopfgesten während Nav2-Bewegung gesperrt").
- `mapping_active=True` und Geste bewegt `HeadYaw`/`HeadPitch` →
  abgelehnt.

**Live-Wiring-Stand**: diese drei Parameter sind in `play()` fertig
implementiert und getestet (`test_gesture_catalog_v2.py`), aber
`bridge_node.py`s bestehender `PlayGesture`-Action-Handler ruft `play()`
aktuell **ohne** diese Werte auf (immer `current_interaction_state=None,
nav2_moving=False, mapping_active=False`) -- die Live-Verdrahtung an
echte `/interaction_state`/`/safety_state`/Kopfpose-Topics ist ein
offener Punkt für einen späteren Auftrag.

## `dry_run`

`play(..., dry_run=True)` gibt die vollständig aufgelöste (Speed-
skalierte) Trajektorie zurück, **ohne** `pepper_client` anzufassen --
kein `snapshot_joints`/`set_breathing`/`play_trajectory`-Aufruf. Zusätzlich
kann `bridge_node` komplett mit `dry_run:=true` gestartet werden (neuer
Parameter, Entwicklungsauftrag 1 AP12) -- dann melden **auch** `Say`
sofort Erfolg, ohne jede SSH-Verbindung zu Pepper. Das macht den
vollautomatisierten Offline-E2E-Test möglich (siehe
`ihk_pepper_tests/test/manual_e2e_offline_check.py`).

## Synchroner Transport (`pepper_client.play_trajectory()` / `motion_transport.py`)

`apps/web/pepper/qicli.py::play_trajectory()` ruft NAOqis
`ALMotionProxy.angleInterpolation(names[], angleLists[][], timeLists[][],
isAbsolute)` über die `qicli`-CLI auf, mit JSON-kodierten Listen-
Argumenten statt N sequenzieller `set_angle()`-Aufrufe.

**Ehrlicher Status**: `qicli`s CLI-Argument-Parsing für verschachtelte
JSON-Listen konnte in dieser Session **nicht live gegen einen echten
Pepper geprüft werden** (kein Zugriff). Die Methode ist
**dry_run_validated, NICHT live_validated**. Vor produktivem Einsatz:
einmal einzeln, langsam, unter direkter Aufsicht mit einer einfachen
Zwei-Gelenk-Geste testen. Falls die JSON-Kodierung nicht funktioniert,
ist der sichere Fallback eine sequenzielle Ausführung über mehrere
`set_angle()`-Aufrufe -- das wäre **keine echte Synchronität** mehr und
muss dann auch so dokumentiert werden (nicht vortäuschen).

**Seit Entwicklungsauftrag 3, AP12** läuft `_play_v2()` nicht mehr direkt
über `pepper_client.play_trajectory()`, sondern über
`KinematicCompiler.compile()` (siehe `kinematic_compiler.py` für die
damit behobenen Schwächen: fehlende Gelenke pro Keyframe, undefinierter
Startzustand, inkonsistente Zeitachsen je Gelenk, fehlende
Beschleunigungsprüfung) und `motion_transport.QicliTrajectoryTransport`
(siehe `docs/GESTURE_TRANSPORT.md` für die Transport-Abstraktion:
`prepare/start/poll/cancel/restore`, Mock-/Dry-Run-/Qicli-
Implementierungen). Insbesondere **`restore()`** sendet seitdem EINEN
synchronen `play_trajectory()`-Aufruf für alle wiederherzustellenden
Gelenke -- nicht mehr Gelenk für Gelenk über
`qicli.py::restore_joints()` (dort weiterhin sequenziell, aber nur noch
von v1-Gesten genutzt).

## Die 20 Katalog-Einträge

| Name | Status | Herkunft der Winkelwerte |
|---|---|---|
| `wave_right` | dry_run_validated | identisch zur live getesteten v1-Sequenz, nur als v2-Keyframes |
| `wave_left` | dry_run_validated | dito |
| `raise_both_arms` | dry_run_validated | ShoulderPitch-Wert von der live getesteten wave-Sequenz übernommen |
| `open_arms` | dry_run_validated | ShoulderPitch von t_pose übernommen, ShoulderRoll konservativer als t_pose |
| `self_hug_symbolic` | **draft** | keine Live-Referenz vorhanden, bewusst konservative Winkel |
| `nod_once` | **draft** | keine Live-Referenz für Kopfgesten vorhanden |
| `look_at_person` | **draft** | reine Neutralstellung (0,0) -- PLATZHALTER, berechnet noch keine echte Blickrichtung |
| `neutral_stand` | dry_run_validated | identisch zur `NEUTRAL_STAND_POSE`-Konstante in `kinematic_compiler.py` |
| `greet_open` | dry_run_validated | konservativer Bruchteil von `open_arms` |
| `goodbye_wave` | dry_run_validated | identisch zur live getesteten `wave_right`-Sequenz, nur kürzer |
| `explain_small` | **draft** | neue kleine Bewegung, konservativer als `open_arms` |
| `explain_left` | **draft** | zwischen `greet_open`/`open_arms` interpoliert |
| `explain_right` | **draft** | Spiegelung von `explain_left` |
| `point_to_tablet` | **draft** | Kopf+Arm-Kombination, keine verifizierte Tablet-Ausschlusszone -- siehe Kommentar in der YAML |
| `agree_nod` | **draft** | Doppel-Nicken, Amplitude von `nod_once` übernommen |
| `disagree_head` | **draft** | HeadYaw-Oszillation, Geschwindigkeit unter der `wave_right`-Referenz |
| `celebrate_small` | **draft** | neue symmetrische Bewegung, keine Oszillation (kein Ruck) |
| `present_information` | **draft** | von `explain_right` abgeleitet, längere Haltezeit |
| `thinking_symbolic` | **draft** | Kopf+Arm, Hand bewusst auf Brusthöhe gehalten (siehe Movement-Regel "keine Hände im Gesichtsbereich") |

`self_hug_symbolic` ist kontaktlos/symbolisch -- Pepper darf keine
Person berühren, keine echte Umarmung ausführen (Auftrag, explizit
ausgeschlossen). `celebrate_small` ist ebenfalls bewusst NICHT als
Umarmungs-Andeutung gebaut (Arme bleiben seitlich, nicht zueinander
geführt).

**Behobener Bug (Entwicklungsauftrag 3, AP13)**: `look_at_person`,
`nod_once`, `open_arms`, `self_hug_symbolic` referenzierten in
`allowed_interaction_states` den Wert `SPEAKING` -- das ist **kein**
gültiger `InteractionState`-Wert (existierte nur in `DialogueState.msg`,
komplett getrennt von `interaction_state.py`) und verhinderte faktisch
jede Gestenfreigabe während eines echten Gesprächs. Entfernt (die
Gesten waren jeweils bereits zusätzlich für `CONVERSATION_READY`
freigegeben, das den beabsichtigten Zustand tatsächlich trifft).

## Neue Geste anlegen -- Checkliste

1. YAML-Datei unter `config/gestures/<name>.yaml`, `name:` muss zum
   Dateinamen passen.
2. `schema_version: 2`, Keyframes mit streng monotonen Zeiten.
3. Winkelwerte aus **vorhandenen getesteten Posen** ableiten, wo möglich
   -- keine erfundenen Werte. Wo keine Referenz existiert:
   `tested_status: draft`, kleine/konservative Auslenkung.
4. `allowed_interaction_states`, `requires_stationary`, `max_duration_s`,
   `on_cancel` setzen.
5. `colcon build --packages-select ihk_pepper_bridge` +
   `python3 -m pytest .../test_gesture_catalog_v2.py` -- Validierung
   greift beim Laden.
6. Vor `tested_status: live_validated`: einzeln, langsam, unter direkter
   Aufsicht am echten Pepper testen (nicht Teil dieses Auftrags).
