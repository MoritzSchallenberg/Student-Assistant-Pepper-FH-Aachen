# TF-Kette und Kopfpose

{{ documented }}

## Was diese Seite ist

Die vollständige, beabsichtigte TF-Kette dieses Projekts und warum ihr
statischer Teil trotz fehlender echter Kopf-Kinematik sicher ist.

## Die vollständige Kette

```{figure} ../_static/images/pepper-realsense-tf-tree.svg
:alt: TF-Baum map zu odom zu base_link zu realsense_mount_link zu camera_link, mit map-zu-odom und odom-zu-base_link als dynamisch markiert (RTAB-Map) und base_link-zu-realsense_mount_link-zu-camera_link als statisch markiert, abgesichert durch camera_pose_gate_node.
:width: 100%

Nur der äußere Teil der Kette (map/odom/base_link) ist dynamisch --
die Kamera selbst hängt an einer festen, angenommenen Kopfpose.
```

```text
map -> odom -> base_link -> realsense_mount_link -> camera_link
                              (statisch, Entw.auftrag 1)  (RTAB-Map, Entw.auftrag 2)
```

## `base_link → realsense_mount_link → camera_link` (statisch)

Werte aus `config/realsense_extrinsics.yaml` — aktuell **Platzhalter**,
`is_calibrated: false`. Diese Teilkette modelliert **bewusst nicht**
Peppers echte Kopf-Kinematik (`HeadYaw`/`HeadPitch`) — sie geht von einer
**festen** Kopfpose aus.

**Warum das trotzdem sicher ist**: `camera_pose_gate_node` (aus
Entwicklungsauftrag 1) entzieht die Bewegungsfreigabe, sobald der Kopf
von dieser angenommenen Navigationspose abweicht
(`head_navigation_pose_valid`). Eine echte kinematische Kette wäre
präziser, war aber für den bisherigen Auftragsumfang nicht
erforderlich.

`extrinsics_plausibility.py` (rein, kein ROS) prüft die konfigurierten
Montagewerte auf grobe Plausibilität (Translation < 2 m, Rotation im
gültigen `[-π, π]`-Bereich) — ergänzt die `is_calibrated`-Warnung um
eine echte Wertprüfung, **ersetzt aber keine echte Vermessung**.

## `odom → base_link` (dynamisch, RGB-D Visual Odometry)

Aus `rtabmap_odom/rgbd_odometry`, ausschließlich RealSense-Daten —
**keine** Pepper-Odometrie, **keine** Pepper-/RealSense-IMU
(`wait_imu_to_init: false`). `odometry_health_node` bewertet
`rtabmap_msgs/OdomInfo` fortlaufend; Tracking-Verlust hat immer Vorrang
vor jedem anderen Kriterium.

## `map → odom` (dynamisch, RTAB-Map-Lokalisierung)

Aus RTAB-Map-Lokalisierung gegen eine gespeicherte Karte.
`localization_health_node` publiziert direkt auf `/localization_valid`.

## Der durchgängige Grundsatz

Fehlende oder veraltete TF führt an **jeder** Stelle dieser Kette immer
zu einem sicheren ungültigen Zustand, **nie** zu einer geschätzten
Position — siehe `realsense_diagnostics_node`
(`tf_zur_roboterbasis_fehlt`) und `person_approach_node.py`
(`keine_tf_fuer_roboterpose`).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Die Kettenstruktur ist per Launch-Datei-Verifikation
und Unit-Tests geprüft. Kameraextrinsik bleibt vollständig unvermessen
(Platzhalterwerte). {{ hwverificationrequired }} vor jeder produktiven
Nutzung: echte Vermessung nötig (siehe
`docs/REALSENSE_CALIBRATION.md` im Repository-Wurzelverzeichnis).

## Nächster Schritt

[Abdeckungslücke](coverage-gap.md).
