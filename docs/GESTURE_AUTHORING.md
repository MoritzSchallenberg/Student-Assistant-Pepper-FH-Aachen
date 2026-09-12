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

## Kanonische Auswahl-/Sicherheitsmetadaten (Entwicklungsauftrag 04-B, AP8, Commit 11/14)

Diese Felder sind seit Commit 11/14 **erstklassige, validierte
Top-Level-Attribute** von `Gesture` (vorher teils nur über das freie
`metadata`-Dict lesbar):

```yaml
system_only: false          # true = nur interne/Systemablaeufe, NIE vom LLM waehlbar
selectable_by_llm: true     # false = strukturell nie an LLM 2 als Option gegeben
semantic_tags: [greeting, welcoming, open_arms]   # Liste von Strings, fuer die semantische Suche
```

**Sichere Defaults (Abschnitt 4.2)**: fehlen beide Felder vollständig
(weder Top-Level noch im alten `metadata`-Dict), gilt `system_only:
false` UND `selectable_by_llm: false` -- eine alte/unvollständige Datei
wird also NIE automatisch LLM-auswählbar, nur weil ein Feld fehlt.

**Kohärenzregeln** (beim Laden hart geprüft, `GestureValidationError`
bei Verstoß, KEINE stille Korrektur):

- `system_only: true` UND `selectable_by_llm: true` gleichzeitig ist ein
  Schemafehler.
- `selectable_by_llm: true` verlangt eine nicht-leere `description` UND
  mindestens einen `semantic_tag`.
- `tested_status: dry_run_validated`/`live_validated` verlangt ein
  gesetztes `tested_date` UND eine nicht-leere `test_note` mit
  nachvollziehbarer Evidenz.
- `requires_stationary`/`system_only`/`selectable_by_llm` müssen echte
  YAML-Booleans sein -- ein String wie `"false"` wird NICHT über die
  allgemeine Python-Wahrheitswertkonvertierung akzeptiert.
- `allowed_interaction_states`-Einträge müssen echte
  `InteractionState`-Namen sein (`interaction_state.py`).
- `max_duration_s` muss, wenn gesetzt, endlich und positiv sein.

**Drei getrennte Dimensionen, keine ersetzt die andere**: `tested_status`
beschreibt den Bewegungsnachweis, `system_only` den vorgesehenen
Aufrufer, `selectable_by_llm` ausschließlich die semantische
LLM-Auswahl. Keines dieser Felder umgeht ein anderes Sicherheitsgate
(Kollisionsnachweis, Lease/Quarantäne, Watchdog etc. bleiben davon
unberührt).

**Rückwärtskompatibilität**: ein älterer/externer Eintrag darf diese
drei Felder weiterhin nur im alten `metadata`-Dict tragen -- das wird
gelesen, aber nur solange kein widersprechender Top-Level-Wert
existiert (sonst Ablehnung). `gesturectl audit` weist einen solchen
Legacy-Fallback sichtbar als Warnung aus. Die 24 mitgelieferten Dateien
sind vollständig auf die kanonischen Top-Level-Felder migriert.

**Verbindliche Systemgesten** (Auftrag-Vorgabe, von `gesturectl audit`
hart geprüft): `acknowledge_nod_small`, `thinking_loop_subtle`,
`look_at_person` müssen `system_only: true` bleiben. Zusätzlich sind
`neutral_stand` und `t_pose` (kein nachgewiesener nutzergerichteter
Aufrufpfad im Repository gefunden) ebenfalls `system_only`. Die
vollständige, aktuelle Liste steht im generierten Inventar (siehe
unten).

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

## Der Katalog-Bestand

Die vollständige, aktuelle Liste aller Kataloggesten (Name, Schema-
Version, `tested_status`, `system_only`/`selectable_by_llm`,
`semantic_tags`, `max_duration_s`) steht **nicht mehr hier von Hand
gepflegt** -- Entwicklungsauftrag 04-B, AP8, Commit 11/14 hat diese
Tabelle durch ein automatisch aus dem echten Katalog erzeugtes Inventar
ersetzt (eine von Hand gepflegte zweite Liste driftet sonst zuverlässig
vom tatsächlichen Katalogstand auseinander -- siehe die frühere, hier
vorher stehende "20 Katalog-Einträge"-Tabelle, die zuletzt u.a.
`greet_open` noch fälschlich als `dry_run_validated` auswies, obwohl es
seit einer Trajektorien-Migration `draft` ist):

**[docs/GESTURE_CATALOG_INVENTORY.md](GESTURE_CATALOG_INVENTORY.md)**

Reproduktionsbefehl (nach `colcon build`, mit gesourctem Workspace):

```bash
python3 scripts/generate_gesture_inventory.py
```

Ein Drift-Test (`test_gesture_inventory_drift.py`) prüft bei jeder
Regression, dass die eingecheckte Datei einer frischen Generierung aus
dem aktuellen Katalog entspricht -- `gesturectl audit` prüft zusätzlich
Metadatenkonsistenz, Systemgesten-/LLM-Regeln und Spiegelpaare (siehe
`gesture_catalog_audit.py`).

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
5. `system_only`/`selectable_by_llm`/`semantic_tags` explizit setzen
   (siehe Abschnitt oben) -- eine LLM-auswählbare Geste braucht eine
   nicht-leere `description` und mindestens einen Tag.
6. `colcon build --packages-select ihk_pepper_bridge` +
   `python3 -m pytest .../test_gesture_catalog_v2.py` -- Validierung
   greift beim Laden.
7. `ros2 run ihk_pepper_bridge gesturectl audit` ausführen (Exitcode 0 =
   keine Fehler) und `python3 scripts/generate_gesture_inventory.py`, um
   `docs/GESTURE_CATALOG_INVENTORY.md` zu aktualisieren.
8. Vor `tested_status: live_validated`: einzeln, langsam, unter direkter
   Aufsicht am echten Pepper testen (nicht Teil dieses Auftrags).
