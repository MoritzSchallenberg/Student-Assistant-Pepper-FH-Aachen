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

**Echt getestet**: alle 8 Nodes starten fehlerfrei, `bt_executor` tickt
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
RealSense-Topics umgebogenen Parametern, `camera_pose_gate_node`. KEINE
Bewegung, kein `bridge_node`, kein Nav2/Mock-Nav2.

**Nicht live getestet** -- keine RealSense-Hardware in dieser Session
angeschlossen. Nur Launch-Struktur verifiziert (`--show-args`,
korrekte Parameterweitergabe an `rs_launch.py`).

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

## Zusätzlich: manueller Offline-E2E-Test

```bash
python3 src/ihk_pepper_tests/test/manual_e2e_offline_check.py
```

Kein eigener Launch-Modus, sondern ein Python-Skript, das dieselben
Nodes wie `offline_test.launch.py` per Subprozess startet, synthetische
Daten einspielt (Person + bestätigtes Rückwinken) und automatisch prüft,
ob `CONVERSATION_READY` erreicht wird -- **ohne** `/cmd_vel` zu sehen.
Siehe Moduldocstring für die genaue Begründung, warum das kein
`pytest`-Test ist. 3/3 Läufe erfolgreich, ~5s bis `CONVERSATION_READY`.

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
