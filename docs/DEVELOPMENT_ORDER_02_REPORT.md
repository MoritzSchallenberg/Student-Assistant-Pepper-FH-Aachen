# Entwicklungsauftrag 2: RealSense-only Navigation, Mapping, sichere Personenannäherung

Laufender Bericht. Wird nach jedem Arbeitspaket ergänzt (Order-2-Vorgabe:
"nach jedem Arbeitspaket ... Ergebnis dokumentieren"). Keine geschönten
Statusangaben -- "konfiguriert"/"kompiliert"/"Node startet" wird nicht als
funktionierende autonome Navigation bezeichnet.

## AP1: Branch, Ausgangsstand

Verbindliche Startbedingung (Order 2, Abschnitt 2) geprüft und erfüllt:

- `ros-jazzy-behaviortree-cpp` installiert (Entwicklungsauftrag 1).
- `ihk_pepper_behavior_tree` kompiliert erfolgreich.
- Alle neun BT-Knoten funktional verifiziert (Ende-zu-Ende-Test, Auftrag 1 AP12).
- RealSense-Bringup und Startmodi aus Auftrag 1 fertig.
- Alle Tests grün, keine uncommitteten Änderungen (Stand vor Auftrag 2).

Abschluss-Commit Entwicklungsauftrag 1: **`abbaf15d5405398629a1ed1ebb956ca6e09489cd`**
(`Abschluss Entwicklungsauftrag 1: finaler Bericht ...`) auf Branch
`order-01-realsense-bt-gestures`.

Branch für diesen Auftrag:

```bash
git switch order-01-realsense-bt-gestures
git switch -c order-02-realsense-nav2-safe-approach
```

```
$ git status
Auf Branch order-02-realsense-nav2-safe-approach
nichts zu committen, Arbeitsverzeichnis unverändert

$ git rev-parse HEAD
abbaf15d5405398629a1ed1ebb956ca6e09489cd

$ git log -1 --oneline
abbaf15 Abschluss Entwicklungsauftrag 1: finaler Bericht (AP2/3/6/7/10-13, E2E-Bugfixes, 125/125 Tests)
```

### Baseline-Build + Test (vor jeder Änderung dieses Auftrags)

```
$ colcon build --symlink-install --packages-skip ihk_pepper_dialog
Summary: 12 packages finished [13.3s]  (nur Warnungen, keine Fehler)

$ python3 -m pytest ros2/autonomy_ws/src/ihk_pepper_tests/test/ -q
125 passed in 0.69s

$ colcon test --packages-select ihk_pepper_behavior_tree
Summary: 17 tests, 0 errors, 0 failures, 3 skipped
```

### Komponenten-Tabelle: vorhandener Stand, Änderung in diesem Auftrag

| Komponente | Status vorher (Ende Auftrag 1) | Änderung in Auftrag 2 |
|---|---|---|
| `ihk_pepper_navigation/person_approach_node.py::_drive_to_person()` | fährt strukturell auf die Personenposition selbst (bekannter, dokumentierter Mangel) | AP9: echte Gesprächs-Zielpose-Geometrie |
| Nav2-Konfiguration (`nav2_params.yaml`) | vorbereitet, NICHT installiert/getestet, keine Costmap-Sektion, 4 cmd_vel-Verdrahtungsfehler (siehe unten) | AP6/AP7: Costmap ergänzen, Verdrahtung reparieren, holonome Freigabe |
| `robot_localization.yaml` (EKF, Pepper-Odom+IMU) | vorbereitet, NICHT installiert/getestet | AP4: für RealSense-only-Modus NICHT mehr eingebunden (Datei bleibt für andere Modi) |
| `depthimage_to_laserscan` | konfiguriert, von keinem Launch inkludiert | AP6: bleibt optionale Ergänzung, nicht alleinige Hinderniserkennung |
| `slam_toolbox`-Mapping (2D-Laser) | vorbereitet, NICHT installiert/getestet | bleibt unangetastet als Alternativpfad; neuer Pfad ist RTAB-Map (AP4/AP5) |
| RTAB-Map (Odometrie/SLAM) | nicht referenziert | AP4/AP5: neue RGB-D-Odometrie/Mapping/Lokalisierung |
| RealSense-Bringup/-TF (Auftrag 1) | vorhanden, nicht live an Hardware getestet | AP2/AP3: Diagnoseknoten + TF-Kettenerweiterung |
| Motion Guard | nicht vorhanden | AP8: neuer zentraler Node |
| Behavior Tree (9 Knoten, `GreetAndApproachSubtree`) | funktional verifiziert (Mock-Nav2) | AP10: Fahrtüberwachung während echtem Approach |
| Startmodi (`offline_test`, `realsense_test`, `pepper_gesture_test`, `dialog_only`, `full_system`) | vorhanden, funktional | AP11: 6 neue Modi |
| Tests | 125 Python + 17 BT.CPP | AP12: neue Unit-/Integrationstests |

### Verfügbare/fehlende Pakete (per `dpkg -l`, ohne sudo geprüft)

**Bereits installiert** (kann real gebaut/getestet werden):
`ros-jazzy-realsense2-camera` 4.58.1, `ros-jazzy-librealsense2` 2.58.1,
kompletter RTAB-Map-Stack (`ros-jazzy-rtabmap-odom`, `-slam`, `-sync`,
`-conversions`, `-launch`, `-util`, `-msgs`, `-viz`, `-rviz-plugins`,
`-python`, `-examples`, `-demos`, 0.22.1).

**NICHT installiert** (kein passwortloses sudo -- `sudo -n true`
verlangt ein Passwort; Order 2 erlaubt ausdrücklich, dass das den
Auftrag nicht blockiert): voller Nav2-Stack (nur `nav2-msgs` als
transitive Abhängigkeit vorhanden), `robot-localization`,
`depthimage-to-laserscan`, `collision-monitor`, `velocity-smoother`,
`twist-mux`, `slam-toolbox` als eigenständige Pakete.

**Hardware**: keine RealSense angeschlossen (nur Bluetooth in `lsusb`),
kein echter Pepper erreichbar.

### Wichtiger Fund: naoqi_driver2-Quellcode zur Holonomie-Frage

`large_files/ros2_ws/src/naoqi_driver2/src/subscribers/teleop.cpp:51-60`
(`TeleopSubscriber::cmd_vel_callback`) liest `linear.x`, `linear.y`,
`angular.z` aus dem `/cmd_vel`-Twist und ruft direkt
`p_motion_.async<void>("move", vel_x, vel_y, vel_th)` auf NAOqis
`ALMotion` auf -- **`linear.y` wird unverändert durchgereicht**, keine
Filterung. Per Quellcode-Review bestätigt (Order 2 AP7 verlangt genau
diese Prüfung), **nicht live an Hardware getestet**. Pepper ist damit
technisch holonom ansteuerbar; `vy` muss nicht strukturell auf 0
erzwungen werden -- die bisherige `nav2_params.yaml`-Annahme
(`holonomic: false`) war eine reine Software-Policy-Entscheidung, keine
Hardware-Notwendigkeit (das Pepper-URDF zeigt 3 Rad-Gelenke, konsistent
mit der realen omnidirektionalen Basis).

### Vier gefundene cmd_vel-Verdrahtungsfehler in `nav2_params.yaml`/`nav2_bringup.launch.py` (Auftrag 1, bisher nie live getestet)

1. `controller_server` bleibt unremapped -> publiziert direkt auf
   `/cmd_vel`, demselben Topic, auf das `twist_mux` seinen `cmd_vel_out`
   remapt -- zwei potenzielle Publisher auf `/cmd_vel`.
2. `velocity_smoother` abonniert `cmd_vel_raw`, aber niemand publiziert
   dorthin (`controller_server` bleibt bei `cmd_vel`).
3. `collision_monitor` liest per YAML-Param ebenfalls von `cmd_vel_raw`
   und schreibt nach `cmd_vel_smoothed` -- dieselben Topics wie
   `velocity_smoother`, statt beide hintereinanderzuhängen.
4. `twist_mux`s Not-Halt-Lock erwartet `/safety_state_emergency_stop_bool`
   (`std_msgs/Bool`) -- kein Node publiziert das (im YAML selbst bereits
   als fehlender Brückenknoten kommentiert).

Diese vier Punkte werden in AP7 behoben.

## AP9: Sichere Annäherungszielpose (vorgezogen, keine Paketabhängigkeit)

Neues reines Modul `ihk_pepper_navigation/approach_pose.py` (kein ROS,
gleiches Muster wie `zone_config.py`/`head_pose_gate.py`):
`compute_approach_pose()` berechnet die Zielpose `target_distance_m`
VOR der Person (normierter Richtungsvektor Roboter→Person, Zielpose auf
dieser Geraden), Blickrichtung zur Person (`atan2`). Lehnt ab bei:
Zielpose in Keepout-Zone (`zone_config.py` wiederverwendet), Person
identisch mit Roboterposition, Person jenseits
`maximum_approach_distance_m`, `target_distance_m` unter
`minimum_person_distance_m` oder ≤0. Sonderfall "Person bereits näher
als der Gesprächsabstand" -> `already_within_distance=True`, Zielpose =
aktuelle Roboterpose (keine Fahrt nötig, niemals über die Person hinaus
oder direkt auf sie zu). Optionaler `costmap_free_fn`-Rückruf als
Schnittstelle für AP6 (Nav2-Costmap, noch nicht vorhanden -- Prüfung
wird ohne Costmap übersprungen, nicht stillschweigend als "frei"
angenommen). Zusätzlich `should_replan()` (Schwellenvergleich gegen
Tracking-Jitter), `is_track_fresh()`, `RepeatedPlanningFailureGuard`
(Zähler für "wiederholte Planungsfehler führen zum sicheren Abbruch")
als wiederverwendbare Bausteine -- deren volle Verdrahtung in eine
laufende Fahrt-Überwachungsschleife ist bewusst AP10 zugeordnet
(Behavior-Tree-Fahrtüberwachung), nicht Teil dieses Node-Fixes.

`person_approach_node.py::_drive_to_person()` umgebaut: nutzt jetzt
`compute_approach_pose()` statt `track.position_3d` direkt als Nav2-Ziel
zu setzen -- behebt den in Auftrag 1 bestätigten Mangel direkt.
Roboterpose wird per TF bestimmt (`_get_robot_position_in_frame()`):
liegt der Track bereits im `robot_base_frame` vor (aktueller Stand ohne
Lokalisierung -- `perception_node.py` transformiert bewusst noch nicht
nach `map`, siehe dessen eigener Kommentar), ist die Roboterpose per
Definition der Ursprung, keine TF-Lookup nötig. Sobald AP4/AP5 eine
echte `map`-Lokalisierung liefern, greift stattdessen ein echter
TF-Lookup -- fehlende/veraltete TF führt IMMER zu einem Abbruch
(`keine_tf_fuer_roboterpose`), NIE zu einer geschätzten Position
(gleiches Prinzip wie `perception_node.py::_transform_to_base_frame`).

**Getestet**: 19 neue Unit-Tests (`test_approach_pose.py`) -- Zielpose-
Geometrie (achsenparallel + diagonal), Grenzfälle (Person näher als
Zielabstand, identische Position, zu weit entfernt, Keepout-Zone,
Costmap-Callback), Replanning-Schwelle, Track-Timeout,
Fehler-Zähler. Live-Smoke-Test: `ros2 run ihk_pepper_navigation
person_approach_node` startet fehlerfrei mit dem neuen TF-Buffer/
Listener und den neuen Parametern (`minimum_person_distance_m`,
`maximum_approach_distance_m`, `robot_base_frame`,
`tf_lookup_timeout_s`). **Nicht getestet**: der eigentliche Nav2-
Fahrpfad selbst (Nav2 nicht installiert, siehe AP1) -- nur die
Zielgeometrie und der TF-Abbruchpfad.

Gesamttestzahl nach AP9: **144/144** (125 Baseline + 19 neu). Commit
`de12343`.

## AP2: RealSense-Hardwareprofil und Diagnose

Neues reines Modul `ihk_pepper_navigation/realsense_diagnostics.py`
(kein ROS): `check_realsense_diagnostics()` sammelt -- anders als
`head_pose_gate.check_head_pose()` (ein einzelner Gate-Wert) --
**alle** gleichzeitig zutreffenden Probleme in einer Liste (ein
Diagnoseknoten soll zeigen, WAS konkret fehlt). Erkennt: fehlende
RGB-/Depth-/CameraInfo-Topics (und unterscheidet "eine fehlt" von
"Kamera komplett nicht vorhanden"), veraltete Daten je Topic,
Zeitstempel-Desynchronisation zwischen Farb- und Tiefenbild, zu
niedrige Bildrate, zu hohen Anteil ungültiger Tiefenpixel, fehlende TF
zur Roboterbasis, ungeeignete USB-Verbindung (nur geprüft, wenn der
USB-Typ tatsächlich bekannt ist -- unbekannt wird nicht bestraft).
`compute_invalid_depth_fraction()` nutzt dieselben Ungültig-Kriterien
wie `ihk_pepper_perception/deprojection.py::estimate_patch_depth()`
(0/NaN/Inf/außerhalb des gültigen Bereichs), hier aber als
Gesamtbild-Statistik statt Patch-Median.

Neuer dünner ROS-Wrapper `realsense_diagnostics_node.py` (gleiches
Muster wie `camera_pose_gate_node.py`): abonniert Color-/Depth-/
CameraInfo-Topics, schätzt die Bildrate über ein 5s-Zeitfenster,
dekodiert das Tiefenbild per `cv_bridge` (wie `perception_node.py`),
prüft die TF zur Roboterbasis per `tf2_ros`, publiziert
`realsense_diagnostics_valid` (Bool) + `realsense_diagnostics/diagnostics`
(String) mit 2 Hz. Neues `config/realsense_profile.yaml` (konservative
Defaults, kein Kameramodell vorausgesetzt). In
`ihk_pepper_bringup/launch/realsense_test.launch.py` ergänzt.

**Getestet**: 20 neue Unit-Tests (`test_realsense_diagnostics.py`).
**Live-Smoke-Test** (kein echter Kamera-Stream, aber echter ROS2-Node-
Start): `ros2 run ihk_pepper_navigation realsense_diagnostics_node`
gestartet, `/realsense_diagnostics/diagnostics` und
`/realsense_diagnostics_valid` per `ros2 topic echo` gelesen --
korrektes Ergebnis: `valid=False reasons=rgb_topic_fehlt,depth_topic_fehlt,
camera_info_topic_fehlt,kamera_nicht_vorhanden,tf_zur_roboterbasis_fehlt`.
Verhält sich also exakt wie erwartet: sicherer ungültiger Zustand ohne
angeschlossene Kamera, keine optimistische Annahme.
`realsense_test.launch.py --show-args` erfolgreich verifiziert (Launch-
Struktur, keine Syntaxfehler). **Nicht getestet**: echte Kamera-Daten
(FPS-Messung, Tiefenbild-Dekodierung, Sync-Differenz) -- keine
RealSense-Hardware in dieser Session angeschlossen.

Gesamttestzahl nach AP2: **164/164** (144 + 20 neu).

### Reihenfolge der Umsetzung in diesem Auftrag

Abweichend von der Auftragsnummerierung wird in dieser praktischen
Reihenfolge gearbeitet (kein Abhängigkeitszwang, früh testbare
Zwischenstände): AP1 (dieser Abschnitt) -> AP9 (Zielpose-Geometrie,
behebt den bekannten Bug sofort, keine Paketabhängigkeit) -> AP2
(RealSense-Diagnose) -> AP3 (TF-Kette) -> AP4 (RTAB-Map-Odometrie) ->
AP5 (Mapping/Lokalisierung) -> AP8 (Motion Guard) -> AP6 (Costmap) ->
AP7 (Nav2-Verdrahtung) -> AP10 (BT) -> AP11 (Startmodi) -> AP12 (Tests,
laufend) -> AP13 (Ansible/rosdep) -> AP14 (Abschluss).
