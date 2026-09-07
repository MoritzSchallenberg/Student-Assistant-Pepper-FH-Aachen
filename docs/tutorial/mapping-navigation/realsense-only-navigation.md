# RealSense-only-Navigationspfad

{{ documented }}

## Was diese Seite ist

Der vollständige, reale Navigationspfad aus Entwicklungsauftrag 2 --
von der RealSense bis zum tatsächlichen `/cmd_vel`-Befehl.

## Der vollständige Pfad

```{figure} ../_static/images/realsense-nav2-dataflow.svg
:alt: Datenfluss von RealSense über die statische Kopf-TF, RTAB-Map-Odometrie und -Lokalisierung, Nav2 (Controller/Planner/BT-Navigator), Velocity Smoother, Collision Monitor, Motion Guard bis /cmd_vel und naoqi_driver2. Kein AMCL, keine EKF, keine Pepper-eigene Odometrie im Bild.
:width: 100%

Jeder Pfeil ist ein reales ROS2-Topic/eine reale TF -- keine entfernten
Komponenten (AMCL, EKF, Pepper-Laser als Costmap-Quelle) sind hier
gezeichnet.
```

```text
RealSense
  → statische Kopf-/Kamera-TF (siehe RealSense und Koordinatenrahmen)
  → RTAB-Map RGB-D Visual Odometry (odom -> base_link)
  → RTAB-Map SLAM/Lokalisierung (map -> odom)
  → Nav2 (Controller/Planner/BT-Navigator)
  → controller_server → cmd_vel_raw
  → velocity_smoother → cmd_vel_smoothed_raw
  → collision_monitor → cmd_vel_smoothed
  → Motion Guard → /cmd_vel
  → naoqi_driver2 → Pepper (ALMotion)
```

## Architektur-Pivot: keine Pepper-eigene Odometrie mehr

`nav2_bringup.launch.py` startete ursprünglich `amcl` + `map_server` +
`robot_localization`s `ekf_filter_node` mit **Peppers eigener
Odometrie/IMU** (`/odom`, `/imu/base`) — das war laut Auftrag 2
verboten. Beide Nodes wurden **entfernt**. `map → odom → base_link`
kommt jetzt ausschließlich aus `realsense_localization.launch.py`/
`realsense_odometry.launch.py` — die müssen **vor**
`nav2_bringup.launch.py` separat laufen. `robot_localization.yaml`/
`slam_mapping.launch.py` bleiben als Dateien im Repository erhalten
(nicht gelöscht, falls ein späterer, ausdrücklich nicht-RealSense-only-
Modus sie braucht), werden aber von keinem aktuellen Launch mehr
eingebunden.

## Vier behobene cmd_vel-Verdrahtungsfehler

Vor Auftrag 2 gefunden, nie live getestet: `controller_server` blieb
unremapped (zweiter Publisher auf `/cmd_vel`), `velocity_smoother`
abonnierte ein Topic, das niemand publizierte, `collision_monitor` las
vom selben statt vom nachgelagerten Topic, `twist_mux`s Not-Halt-Lock
erwartete ein Topic, das kein Node publizierte. Alle vier behoben — die
finale, eindeutige Namenskette steht oben. `twist_mux` **entfällt
komplett**, Motion Guard übernimmt seine Rolle als letzte Instanz.

## Mapping/Lokalisierung: gegenseitiger Ausschluss

`mode_lock.py` (dateibasierte Sperre) verhindert, dass Mapping- und
Lokalisierungsmodus gleichzeitig laufen — beide würden sich sonst bei
`map → odom` widersprechen. `database_path` liegt für Mapping
standardmäßig unter `~/.ihk_pepper_maps/` (außerhalb jedes Git-/
Colcon-Baums — `.db`-Dateien sind laut CI-Regel nie im Repository
erlaubt), für Lokalisierung ist er Pflicht und wird vor dem Start auf
Existenz geprüft.

## Was davon echt läuft vs. was nur Konfiguration ist

```{list-table}
:header-rows: 1
:widths: 40 60

* - Komponente
  - Status
* - RTAB-Map-Odometrie/-SLAM (Prozessstart)
  - {{ offlinetested }} echt gestartet und live verifiziert, **ohne**
    echten Kamerastream
* - Nav2-Vollstack
  - {{ unverified }} **nicht installiert** in dieser Umgebung (kein
    passwortloses `sudo`) -- rein konfigurationsseitig fertig
* - Holonome Fahrt (`vy != 0`)
  - {{ unverified }} quellcode-bestätigt, **nicht** hardwaregetestet
* - Motion Guard (Block-/Allow-Pfad)
  - {{ offlinetested }} beide Pfade live gegen echte ROS2-Topics
    verifiziert
* - `navigation_live.launch.py`
  - {{ navblocked }} technisch vorbereitet, **nie ausgeführt**
```

## Selbst nachvollziehen (ohne Hardware)

```bash
ros2 launch ihk_pepper_navigation realsense_odometry.launch.py --show-args
ros2 launch ihk_pepper_bringup navigation_dry_run.launch.py --show-args
```

`navigation_dry_run.launch.py` läuft gegen den **echten** Nav2-Stack
(sofern installiert), biegt aber Motion Guards Ausgabetopic auf einen
Sink um — **kein Publisher zum echten `/cmd_vel`**.
`navigation_live.launch.py` verlangt ein zusätzliches Pflichtargument
(`i_understand_this_moves_pepper`) und ist ausschließlich dafür gebaut,
später **beaufsichtigt** gestartet zu werden — siehe
`docs/NAVIGATION_SAFETY_ACCEPTANCE.md` im Repository-Wurzelverzeichnis
für die vollständige, überwiegend noch offene Abnahme-Checkliste.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} für alles, was ohne Nav2/Hardware geprüft werden
konnte. {{ navblocked }} für Livebewegung, solange die
[Abdeckungslücke](../realsense-frames/coverage-gap.md) nicht
geschlossen ist und kein Nav2-Vollstack installiert wurde.

## Nächster Schritt

[Wahrnehmung und Interaktion](../perception-interaction/index.md).
