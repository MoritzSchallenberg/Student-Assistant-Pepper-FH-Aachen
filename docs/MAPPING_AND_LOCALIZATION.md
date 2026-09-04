# Mapping und Lokalisierung (RTAB-Map, RealSense-only)

Stand: 2026-09-04. Entwicklungsauftrag 2, AP5. Voraussetzung: eine
angeschlossene RealSense-Kamera (`realsense_diagnostics_valid=true`,
siehe AP2) -- ohne echte Kamera starten die Nodes fehlerfrei, liefern
aber keine sinnvolle Karte (nur mit dieser Session getestet: kein
Kamera-Stream, siehe `docs/DEVELOPMENT_ORDER_02_REPORT.md`).

## Eine neue Karte erstellen (Mapping)

```bash
cd ros2/autonomy_ws && source install/setup.bash
ros2 launch ihk_pepper_navigation realsense_mapping.launch.py
```

Erzeugt automatisch eine neue, zeitgestempelte Datenbank unter
`~/.ihk_pepper_maps/mapping_<datum>_<uhrzeit>.db` -- **niemals** unter
`ros2/autonomy_ws/install/...` (wird bei jedem `colcon build`
überschrieben) und **niemals** ins Git-Repo committen (`.db`-Dateien
werden von der CI-Prüfung ohnehin abgelehnt, siehe `.github/workflows/ci.yml`).

Eigenen Pfad erzwingen:
```bash
ros2 launch ihk_pepper_navigation realsense_mapping.launch.py \
  database_path:=/pfad/zu/meiner_karte.db
```

RTAB-Map schreibt während des gesamten Laufs kontinuierlich in diese
Datei -- das ist so vorgesehen (kein separater "Speichern"-Knopf). Mit
`Strg+C` sauber beenden (SIGINT) -- die Modus-Sperrdatei wird dabei
automatisch entfernt.

## Gegen eine vorhandene Karte lokalisieren

```bash
ros2 launch ihk_pepper_navigation realsense_localization.launch.py \
  database_path:=/pfad/zu/meiner_karte.db
```

`database_path` ist PFLICHT -- ohne Angabe oder bei einer nicht
existierenden Datei bricht das Launch sofort mit einer klaren
Fehlermeldung ab (kein stiller Fallback auf eine geratene Karte).
Verändert die geladene Karte nicht (`Mem/IncrementalMemory=false`).
`localization_health_node` publiziert `/localization_valid` -- denselben
Sicherheitseingang, den `supervisor_node` (Auftrag 1) bereits abonniert.

## Mapping und Lokalisierung gleichzeitig?

**Nicht möglich** -- `mode_lock.py` verhindert das strukturell (beide
Modi würden sich sonst bei `map -> odom` widersprechen). Ein Versuch,
den jeweils anderen Modus während eines laufenden zu starten, bricht mit
einer klaren `ModeLockError`-Meldung ab. Bekannte Grenze: eine
Sperrdatei, die nach einem Absturz (`kill -9`, Stromausfall) nicht
regulär entfernt wurde, muss manuell gelöscht werden -- Pfad steht in
der Fehlermeldung (`/tmp/ihk_pepper_nav_mode_lock/<modus>.lock`).

## Rosbag-Aufnahme/-Wiedergabe (Entwicklungsauftrag 2, AP12)

Vorbereitet, aber in dieser Session nie tatsächlich aufgenommen (keine
RealSense-Hardware angeschlossen). Relevante Topics für eine
deterministische Wiedergabe (z.B. um `realsense_odometry.launch.py`/
`realsense_mapping.launch.py` ohne angeschlossene Kamera gegen echte
Daten zu testen):

```bash
ros2 bag record -o realsense_session \
  /camera/color/image_raw /camera/color/camera_info \
  /camera/aligned_depth_to_color/image_raw \
  /tf /tf_static /joint_states
```

Wiedergabe (mit `--clock`, damit `use_sim_time` konsistent bleibt, falls
später genutzt):
```bash
ros2 bag play realsense_session --clock
```

**Große `.bag`-Dateien NIEMALS ins Git-Repository committen** -- die
CI-Prüfung lehnt `.bag`/`.bag2`-Dateien ohnehin ab
(`.github/workflows/ci.yml`, "Pruefen, dass keine Datenbanken/grossen
Modell-Artefakte eingecheckt sind").

## Zugrundeliegende Odometrie

Beide Launches binden `realsense_odometry.launch.py` (AP4) automatisch
ein -- **keine** separate Odometrie-Instanz nötig/erlaubt. Siehe
`docs/REALSENSE_NAVIGATION_ARCHITECTURE.md` für die volle TF-Kette.
