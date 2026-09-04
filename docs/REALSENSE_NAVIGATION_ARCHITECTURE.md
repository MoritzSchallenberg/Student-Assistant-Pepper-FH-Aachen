# Architektur: RealSense-only Navigation (Entwicklungsauftrag 2)

Stand: 2026-09-04. Lebendes Dokument -- wird nach jedem Arbeitspaket
ergänzt (siehe docs/DEVELOPMENT_ORDER_02_REPORT.md für den detaillierten
Fortschritt). Ergänzt docs/ARCHITECTURE_REALSense_BT.md (Entwicklungsauftrag 1)
um den Navigations-/Mapping-/Annäherungs-Teil.

## TF-Kette

Vollständige, beabsichtigte Kette für diesen Auftrag:

```
map -> odom -> base_link -> realsense_mount_link -> camera_link
                              (Entwicklungsauftrag 1, statisch)   (RTAB-Map, AP4/AP5)
```

- `base_link -> realsense_mount_link -> camera_link`: **statisch**
  (Entwicklungsauftrag 1, `realsense_static_tf.launch.py`), Werte aus
  `config/realsense_extrinsics.yaml` (Platzhalter, `is_calibrated: false`).
  Diese Teilkette modelliert bewusst NICHT Peppers echte Kopf-Kinematik
  (HeadYaw/HeadPitch) -- sie geht von einer FESTEN Kopfpose aus. Das ist
  nur deshalb sicher, weil `camera_pose_gate_node` (Entwicklungsauftrag 1)
  die Bewegungsfreigabe entzieht, sobald der Kopf von dieser Pose
  abweicht (`head_navigation_pose_valid`). Eine echte kinematische Kette
  wäre präziser, ist für den Umfang dieses Auftrags aber nicht
  erforderlich (AP3).
- `odom -> base_link`: aus RTAB-Map RGB-D Visual Odometry (AP4) --
  ausschließlich RealSense-Daten, KEINE Pepper-Odometrie/-IMU.
- `map -> odom`: aus RTAB-Map-Lokalisierung gegen eine gespeicherte Karte
  (AP5).

Fehlende/veraltete TF führt an jeder Stelle dieser Kette IMMER zu einem
sicheren ungültigen Zustand, NIE zu einer geschätzten Position -- siehe
`realsense_diagnostics_node` (AP2, `tf_zur_roboterbasis_fehlt`) und
`person_approach_node.py::_get_robot_position_in_frame()` (AP9,
`keine_tf_fuer_roboterpose`).

## Plausibilitätsprüfung der Kameramontage (AP3)

`extrinsics_plausibility.py` (rein, kein ROS) prüft die konfigurierten
Montagewerte auf grobe Plausibilität (Translation < 2m, Rotation im
gültigen Bereich) -- ergänzt die bereits vorhandene `is_calibrated`-
Warnung (Entwicklungsauftrag 1) um eine echte Wertepruefung. Ersetzt
KEINE echte Vermessung, siehe `docs/REALSENSE_CALIBRATION.md`.

## RGB-D Visual Odometry (AP4)

`realsense_odometry.launch.py` startet `rtabmap_odom/rgbd_odometry`
(RTAB-Map-Vollstack ist bereits per apt installiert, siehe
`docs/DEVELOPMENT_ORDER_02_REPORT.md`) gegen die RealSense-Topics --
**keine** Pepper-Odometrie, **keine** Pepper-/RealSense-IMU
(`wait_imu_to_init: false`, kein IMU-Topic konfiguriert -- kein
RealSense-Modell mit bestätigter IMU in dieser Session, siehe AP2).
Ausgabe: `/realsense/odom`, TF `odom -> base_link`. `odometry_health_node`
(`odometry_health.py`, rein) bewertet `rtabmap_msgs/OdomInfo` fortlaufend:
Tracking-Verlust (`lost`) hat immer Vorrang, dann Datenalter, dann
Kovarianz, dann optional Inlier-Anzahl -- jeder Fehlerfall führt zu
`odometry_valid=false`, NIE zu einer weiterverwendeten Fantasieposition.
Live gestartet (kein Kamera-Stream, aber ein echter laufender
RTAB-Map-Prozess) -- Details im Auftrag-2-Bericht.

## Mapping und Lokalisierung (AP5)

`realsense_mapping.launch.py`/`realsense_localization.launch.py`
bauen auf `realsense_odometry.launch.py` (AP4) auf und starten
`rtabmap_slam/rtabmap` im jeweiligen Modus (`Mem/IncrementalMemory`
true/false). `mode_lock.py` (dateibasierte Sperre unter
`/tmp/ihk_pepper_nav_mode_lock/`) verhindert, dass beide Modi
gleichzeitig laufen -- beide würden sonst widersprechende Annahmen über
`map -> odom` treffen. `database_path` zeigt für Mapping standardmäßig
auf einen neuen, zeitgestempelten Pfad unter `~/.ihk_pepper_maps/`
(bewusst außerhalb jedes Git-/Colcon-verwalteten Baums -- `.db`-Dateien
sind laut CI-Regel ohnehin nie erlaubt im Repo), für Lokalisierung ist
er PFLICHT und wird vor dem Start auf Existenz geprüft.
`localization_health_node` publiziert direkt auf `/localization_valid`
(derselbe Topic, den `supervisor_node` seit Auftrag 1 abonniert) --
liefert die echte Implementierung dieses seit Auftrag 1 offenen
Sicherheitseingangs.

## Zentraler Motion Guard (AP8)

Letztes Glied der Fahrbefehlskette: `Nav2 -> Velocity Smoother ->
Collision Monitor -> Motion Guard -> /cmd_vel -> naoqi_driver2`.
`motion_guard.py` (rein) prüft sequenziell -- Bumper/Not-Halt zuerst,
dann Modus/Freigabe, dann Datenqualität (RealSense-Diagnose AP2,
Odometrie AP4, Lokalisierung AP5, Hindernisdaten, Kopfpose Auftrag 1),
zuletzt Gestenablauf und Befehlsalter. Bewusst redundant zu `SafetyGate`
(Auftrag 1) -- Bumper/Not-Halt werden hier noch einmal selbst geprüft,
kein blindes Vertrauen in eine einzelne vorgelagerte Aggregation. Bei
jedem Fehlerfall: fortlaufende Nullgeschwindigkeit statt eines einmaligen
Stopps, Kandidaten-Befehl wird komplett verworfen. `enable_live_motion`
(Default `false`) ist der explizite Livebewegungsmodus -- ohne ihn lässt
Motion Guard nie etwas durch, unabhängig von allen anderen Bedingungen.
Live getestet: Block- und Allow-Pfad beide verifiziert (siehe
`docs/DEVELOPMENT_ORDER_02_REPORT.md`).

## Costmap und Abdeckungsnachweis (AP6)

`nav2_params.yaml`s `local_costmap`/`global_costmap` (vorher komplett
gefehlt) nutzen `depthimage_to_laserscan` auf RealSense-Topics als
Hindernisquelle. `coverage_analysis.py` (rein, Lochkamera-Näherung)
weist mit Pepper-/RealSense-Referenzwerten **explizit nach, dass eine
einzelne kopfmontierte Kamera nicht ausreicht** (273° horizontal
komplett unabgedeckt) -- Livebewegung bleibt deshalb strukturell
gesperrt (Motion Guard, AP8), der unabhängige Collision-Monitor-
`BumperStop` und Peppers eigener Laser bleiben als zusätzliche,
RealSense-unabhängige Nahbereichs-Absicherung.

## Nav2 + holonome Fahrregelung (AP7)

**Architektur-Pivot**: `nav2_bringup.launch.py` startet seit Auftrag 2
kein `amcl`/`map_server`/`robot_localization` mit Peppers eigener
Odometrie mehr -- `map -> odom -> base_link` kommt ausschließlich aus
`realsense_localization.launch.py` (AP5), muss davor separat laufen.
Die vier in AP1 gefundenen cmd_vel-Verdrahtungsfehler sind behoben (siehe
`docs/DEVELOPMENT_ORDER_02_REPORT.md`); finale Kette:
`controller_server -> cmd_vel_raw -> velocity_smoother ->
cmd_vel_smoothed_raw -> collision_monitor -> cmd_vel_smoothed ->
Motion Guard -> /cmd_vel`. Twist Mux entfällt, Motion Guard übernimmt
dessen Rolle. Holonomie (`vy != 0`) freigegeben, basierend auf dem in
AP1 per Quellcode bestätigten `naoqi_driver2`-Fund -- explizit als
"quellcode-bestätigt, nicht hardwaregetestet" markiert.

## Weitere Abschnitte

Werden mit AP10 (BT-Integration) und AP11 (Startmodi) ergänzt.
