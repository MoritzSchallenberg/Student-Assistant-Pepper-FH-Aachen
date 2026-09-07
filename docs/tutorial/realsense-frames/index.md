# RealSense und Koordinatenrahmen

## Überblick und Ziel des Themas

Wie die kopfmontierte RealSense-Kamera mechanisch/TF-mäßig mit Pepper
verbunden ist, warum diese Kette bewusst eine Vereinfachung ist, und die
bestätigte, strukturelle Grenze: **eine einzelne Kamera reicht nicht
für eigenständige Livebewegung**.

## Position in der Pepper-Gesamtarchitektur

Voraussetzung für [Mapping und Navigation](../mapping-navigation/index.md)
— jede Odometrie/Karte/Lokalisierung baut auf dieser TF-Kette auf.

## Lernziele

Nach diesem Thema kannst du:

1. die vollständige TF-Kette `map → odom → base_link →
   realsense_mount_link → camera_link` benennen und wissen, welcher
   Teil statisch und welcher dynamisch ist;
2. erklären, warum die statische Kopf-Teilkette trotz fehlender echter
   Kopf-Kinematik sicher ist (`camera_pose_gate_node`);
3. die konkrete Abdeckungslücke einer einzelnen Kopfkamera benennen
   (273° horizontal unabgedeckt) und ihre sicherheitstechnische
   Konsequenz erklären.

## Voraussetzungen

[Pepper-Plattform und Sicherheit](../pepper-platform/index.md).

## Pepper-spezifische Verwendung

{{ pepper }} Diese Kette ist exakt für die eine reale Montageposition
gebaut (Kopfhöhe ~1,2 m), nicht generisch.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} TF-Kette und Kopfpose
:link: tf-chain-and-head-pose
:link-type: doc

{{ documented }} Die vollständige Kette, was statisch/dynamisch ist, und
die Kopfpose-Sicherheitsfreigabe.
:::

:::{grid-item-card} Abdeckungslücke
:link: coverage-gap
:link-type: doc

{{ offlinetested }} Der reale, geometrisch nachgewiesene Blindfleck
einer einzelnen Kopfkamera.
:::

::::

## Praktische Übungen

{{ offlineexercise }} `python3 -m pytest
ros2/autonomy_ws/src/ihk_pepper_tests/test/test_coverage_analysis.py -v`
ausführen und den Testnamen
`test_single_realsense_on_pepper_head_is_not_sufficient_for_live_motion`
im Ergebnis finden — siehe [Abdeckungslücke](coverage-gap.md).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Die TF-Kettenstruktur und die Abdeckungsberechnung
sind unit-getestet und real gegen Launch-Dateien geprüft. **Keine
echten RealSense-Sensordaten** wurden in bisherigen Sessions verarbeitet
(keine Kamera angeschlossen) — die Extrinsik-Werte sind Platzhalter.

## Weiterführende Inhalte und nächste Schritte

[Mapping und Navigation](../mapping-navigation/index.md) für den
vollständigen Navigations-Datenpfad, der auf dieser TF-Kette aufbaut.

```{toctree}
:maxdepth: 1
:hidden:

tf-chain-and-head-pose
coverage-gap
```
