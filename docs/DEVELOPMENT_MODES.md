# Startmodi

Stand: 2026-09-04. Entwicklungsauftrag 1, Abschnitt 11. Drei neue Modi
unter `ros2/autonomy_ws/src/ihk_pepper_bringup/launch/`, zusätzlich zu
den bestehenden `dialog_only.launch.py`/`full_system.launch.py`
(unverändert, weiterhin lauffähig).

## `offline_test.launch.py`

```bash
cd ros2/autonomy_ws && source install/setup.bash
ros2 launch ihk_pepper_bringup offline_test.launch.py
```

Kein Pepper, keine Kamera, kein echtes `/cmd_vel`. Startet den
kompletten Software-Stack: `bridge_node` (mit `dry_run:=true` --
`Say`/`PlayGesture` melden Erfolg ohne SSH-Verbindung),
`supervisor_node` (`motion_capable=false`), `compute_health_mock_node`,
`perception_node` (ohne echte Kamera -- bleibt idle, kein Crash),
`camera_pose_gate_node`, `mock_nav2_server`, `person_approach_node`,
`bt_executor_node`.

Seit Entwicklungsauftrag 2 (AP11) zusätzlich: `realsense_diagnostics_node`,
`odometry_health_node`, `motion_guard_node` (bleiben ohne echte Kamera/
RTAB-Map sicher im "ungültig"-Zustand).

**Echt getestet**: alle 11 Nodes starten fehlerfrei, `bt_executor` tickt
den Baum, kein `/cmd_vel` im Log. Generiert selbst **keine**
synthetischen RGB-D-/Personendaten -- für den vollen Ablauf bis
`CONVERSATION_READY` zusätzlich `manual_e2e_offline_check.py` (spielt
synthetische `PersonTrackArray`/`WaveGestureEvent` ein) oder eigene
Test-Publisher nötig.

## `realsense_test.launch.py`

```bash
ros2 launch ihk_pepper_bringup realsense_test.launch.py
```

Echte RealSense-Kamera (`realsense_bringup.launch.py` +
`realsense_static_tf.launch.py`), `perception_node` mit auf
RealSense-Topics umgebogenen Parametern, `camera_pose_gate_node`,
`realsense_diagnostics_node` (Entwicklungsauftrag 2, AP2 -- erkennt
fehlende Kamera/Topics, veraltete Daten, Zeitstempel-Desync, zu
niedrige Bildrate, zu hohen ungueltigen Tiefenanteil, fehlende TF).
KEINE Bewegung, kein `bridge_node`, kein Nav2/Mock-Nav2.

**Nicht live getestet** -- keine RealSense-Hardware in dieser Session
angeschlossen. Nur Launch-Struktur verifiziert (`--show-args`,
korrekte Parameterweitergabe an `rs_launch.py`).
`realsense_diagnostics_node` selbst wurde ohne Kamera gestartet und
meldet korrekt `valid=False` mit allen erwarteten Gruenden
(`rgb_topic_fehlt`, `depth_topic_fehlt`, `camera_info_topic_fehlt`,
`kamera_nicht_vorhanden`, `tf_zur_roboterbasis_fehlt`) -- siehe
docs/DEVELOPMENT_ORDER_02_REPORT.md.

## `pepper_gesture_test.launch.py`

```bash
set -a && source apps/web/.env && set +a
ros2 launch ihk_pepper_bringup pepper_gesture_test.launch.py
# in einem zweiten Terminal:
ros2 action send_goal /pepper_bridge/play_gesture \
  ihk_pepper_interfaces/action/PlayGesture "{gesture_name: wave_right, speed_scale: 1.0}"
```

Pepper per SSH/qicli verbunden, NUR einzeln über `ros2 action send_goal`
ausgelöste Gesten -- kein Perception/Interaction/Navigation, damit
nichts automatisch etwas auslöst. `motion_capable` bleibt in diesem
Modus immer `false` (kein Argument dafür, kein `supervisor_node`
gestartet).

## `mapping.launch.py` (Entwicklungsauftrag 2, AP11)

```bash
ros2 launch ihk_pepper_bringup realsense_mapping.launch.py
```

RealSense-Odometrie (AP4) + RTAB-Map-Mapping (AP5), standardmäßig
**keine** Ausgabe an Pepper. Dünner Wrapper um
`ihk_pepper_navigation/launch/realsense_mapping.launch.py` -- siehe
`docs/MAPPING_AND_LOCALIZATION.md` für `database_path`/Details.

**Echt getestet** (kein Kamera-Stream, aber ein echter laufender
RTAB-Map-Prozess -- siehe AP4/AP5-Berichtsabschnitte): Launch-Struktur
über die direkte `ihk_pepper_navigation`-Variante bereits live
verifiziert, dieser Bringup-Wrapper zusätzlich per `--show-args` geprüft.

## `localization_test.launch.py` (Entwicklungsauftrag 2, AP11)

```bash
ros2 launch ihk_pepper_bringup realsense_localization_test.launch.py \
  database_path:=/pfad/zur/karte.db
```

Gespeicherte Karte + Lokalisierung, **keine** Bewegung. `database_path`
ist PFLICHT (Existenzprüfung vor Start, kein stiller Fallback). Dünner
Wrapper um `realsense_localization.launch.py` (AP5).

## `navigation_dry_run.launch.py` (Entwicklungsauftrag 2, AP11)

```bash
ros2 launch ihk_pepper_bringup navigation_dry_run.launch.py \
  database_path:=/pfad/zur/karte.db
```

Vollständige Planung und Personenannäherung gegen den **echten**
Nav2-Stack (nicht `mock_nav2_server`) -- Motion Guards Ausgabetopic wird
auf `navigation_dry_run/cmd_vel_sink` umgebogen (`nav2_bringup.launch.py`,
neuer Parameter `cmd_vel_out_topic`), **kein Publisher zum echten
`/cmd_vel`**. `enable_live_motion:=true` wird gesetzt, damit Motion Guard
tatsächlich vollständig durchlaufen wird -- die Sicherheit kommt aus dem
Sink-Topic, nicht aus einer zusätzlichen Sperre. Startet realsense-
Perception, `camera_pose_gate_node`, `realsense_diagnostics_node`, den
vollen `nav2_bringup.launch.py`-Graphen, `bridge_node` (`dry_run:=true`),
`supervisor_node`, `bt_executor_node`.

**Nicht live getestet** -- kein Nav2-Vollstack installiert (siehe AP1),
keine RealSense-Hardware. Nur Launch-Struktur per `--show-args` verifiziert.

## `navigation_live.launch.py` (Entwicklungsauftrag 2, AP11) -- GESPERRT

Technisch vorbereitet, **niemals in dieser Entwicklungssitzung
ausgeführt**. Struktur identisch zu `navigation_dry_run.launch.py`,
aber mit dem echten `/cmd_vel` (kein Sink) und einem zusätzlichen
Pflicht-Argument `i_understand_this_moves_pepper:=true` (reine
Software-Hürde, ersetzt keine echte Sicherheitsabnahme). Benötigt eine
spätere, bewusste, beaufsichtigte Freigabe durch den Nutzer -- siehe
`docs/NAVIGATION_SAFETY_ACCEPTANCE.md` für die davor einzeln
nachzuweisenden Voraussetzungen. Nur per `--show-args` auf korrekte
Launch-Struktur geprüft (bewusst NICHT per `ros2 launch` ausgeführt).

## Zusätzlich: manuelle Testskripte

```bash
python3 src/ihk_pepper_tests/test/manual_e2e_offline_check.py
```

Startet dieselben Nodes wie `offline_test.launch.py` per Subprozess,
spielt synthetische Daten ein (Person + bestätigtes Rückwinken) und
prüft automatisch, ob `CONVERSATION_READY` erreicht wird -- **ohne**
`/cmd_vel` zu sehen. 3/3 Läufe erfolgreich, ~5s bis `CONVERSATION_READY`.

```bash
python3 src/ihk_pepper_tests/test/manual_approach_monitor_check.py
```

Entwicklungsauftrag 2, AP10: startet `mock_nav2_server` +
`person_approach_node`, prüft, dass eine laufende Annäherung bei
Personenverlust **während der Fahrt** sofort aktiv abgebrochen wird
(nicht erst nach einem 60s-Timeout). 2/2 Läufe erfolgreich.

Beide Skripte tragen bewusst `manual_` statt `test_` im Dateinamen --
siehe jeweiligen Moduldocstring für die Begründung (echte Subprozesse,
nicht Teil der schnellen, hermetischen `pytest`-Suite).

## Bereits vorhandene Modi (unverändert)

- `dialog_only.launch.py`: Minimal-Start (Bridge+Audio+Dialog), kein
  Perception/Interaction/Presentation/Navigation.
- `full_system.launch.py`: alle Kern-Pakete, `motion_capable`/
  `enable_navigation`/`enable_perception` als Argumente, Navigation
  weiterhin standardmäßig aus.

## `production`

Kein eigener Modus in diesem Auftrag -- bewusst nicht freigegeben (siehe
Entwicklungsauftrag 1, "Nicht Bestandteil dieses Auftrags"). Erst nach
dokumentierter Hardware-/Sicherheitsabnahme in einem späteren Auftrag.
