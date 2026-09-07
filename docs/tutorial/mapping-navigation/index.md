# Mapping und Navigation

## Überblick und Ziel des Themas

Der vollständige RealSense-only-Navigationspfad (Entwicklungsauftrag 2):
Odometrie, Mapping, Lokalisierung, Nav2, und die durchgängige
Sicherheitskette bis `/cmd_vel`. Bewusst **ausschließlich** RealSense-
Daten, nie Peppers eigene Odometrie/IMU.

## Position in der Pepper-Gesamtarchitektur

Baut auf [RealSense und Koordinatenrahmen](../realsense-frames/index.md)
auf; liefert die `ApproachPerson`-Fähigkeit, die der
[Verhaltensbaum](../decision-making/index.md) in `GreetAndApproachSubtree`
nutzt.

## Lernziele

Nach diesem Thema kannst du:

1. den vollständigen Fahrbefehlspfad benennen: `controller_server →
   cmd_vel_raw → velocity_smoother → cmd_vel_smoothed_raw →
   collision_monitor → cmd_vel_smoothed → Motion Guard → /cmd_vel →
   naoqi_driver2`;
2. erklären, warum `amcl`/`map_server`/`robot_localization` mit Peppers
   eigener Odometrie **entfernt** wurden und wodurch sie ersetzt sind;
3. den aktuellen, ehrlichen Testtand einordnen: welche Prozesse echt
   gestartet wurden, und was **nie** live gegen Nav2 oder echte Hardware
   lief.

## Voraussetzungen

[RealSense und Koordinatenrahmen](../realsense-frames/index.md) --
insbesondere die [Abdeckungslücke](../realsense-frames/coverage-gap.md).

## Pepper-spezifische Verwendung

{{ pepper }} Holonome Fahrt (`vy != 0`) ist für Pepper freigegeben,
basierend auf einem Quellcode-Fund in `naoqi_driver2`
(`TeleopSubscriber::cmd_vel_callback` reicht `linear.y` unverändert
durch) — **quellcode-bestätigt, nicht hardwaregetestet**.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} RealSense-only-Navigationspfad
:link: realsense-only-navigation
:link-type: doc

{{ documented }} Odometrie, Mapping, Lokalisierung, Nav2, Motion Guard --
der vollständige Pfad.
:::

::::

## Praktische Übungen

{{ offlineexercise }} `ros2 launch ihk_pepper_navigation
realsense_odometry.launch.py --show-args` ausführen (startet nichts,
zeigt nur die Launch-Struktur) — siehe
[RealSense-only-Navigationspfad](realsense-only-navigation.md).

(warum-livenavigation-gesperrt-bleibt)=
## Verifikationsstand, Sicherheit und Einschränkungen

{{ navblocked }} `navigation_live.launch.py` wurde in keiner bisherigen
Entwicklungssitzung tatsächlich gestartet. Kein Nav2-Vollstack ist in
dieser Umgebung installiert (kein passwortloses `sudo`). Alle Aussagen
zu echter Fahrbewegung bleiben bis auf Weiteres
{{ hwverificationrequired }}.

## Weiterführende Inhalte und nächste Schritte

[Wahrnehmung und Interaktion](../perception-interaction/index.md) für
den zweiten großen Datenpfad (Personen-Tracking).

```{toctree}
:maxdepth: 1
:hidden:

realsense-only-navigation
```
