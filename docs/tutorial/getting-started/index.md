# Erste Schritte

## Überblick und Ziel des Themas

Dieses Thema bringt dich vom Repository-Checkout zu einer Umgebung, in
der du den restlichen Code dieses Projekts lesen, bauen und offline
testen kannst — ohne dass ein Pepper oder eine RealSense-Kamera
angeschlossen sein muss. Es ersetzt keine ROS-2-Grundlagen-Schulung,
sondern setzt sie voraus.

## Position in der Pepper-Gesamtarchitektur

Alle folgenden Themen bauen auf einem lauffähigen ROS-2-Jazzy-
Arbeitsbereich auf. Dieses Thema ist die Voraussetzung für praktisch
jede Übung auf dieser Seite.

## Lernziele

Nach diesem Thema kannst du:

1. den Repository-Aufbau (`apps/web`, `ros2/autonomy_ws`, `vision`,
   `ansible`, `docs`) benennen und weißt, wo welcher Code liegt;
2. den ROS-2-Workspace `ros2/autonomy_ws` bauen und die Python-Testsuite
   ausführen, ganz ohne Pepper- oder RealSense-Hardware;
3. einordnen, welche Aussagen in der bestehenden Projektdokumentation
   (`docs/*.md` im Wurzelverzeichnis) als *tatsächlich implementiert und
   getestet* gelten und welche als *vorbereitet, aber ungetestet*.

## Voraussetzungen

- Ubuntu 24.04 (oder kompatibel), Python 3.
- Grundkenntnisse in ROS 2 (Nodes, Topics, `colcon build`, `pytest`).
- Kein Pepper, keine RealSense-Kamera nötig für dieses Thema.

## Pepper-spezifische Verwendung

{{ pepper }} Dieses Projekt ist von Grund auf für genau einen Roboter
gebaut — Pepper 1.8, NAOqi 2.9.5.172, Robotername `pepper` — und für
genau eine Kamera, eine kopfmontierte Intel RealSense. Es ist kein
generisches Mehrroboter-Framework.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Repository und Umgebung
:link: repository-and-environment
:link-type: doc

{{ foundation }} Repository-Layout, ROS-2-Workspace bauen, Tests
ausführen — alles offline.
:::

::::

## Praktische Übungen

{{ offlineexercise }} Siehe
[Repository und Umgebung](repository-and-environment.md): Workspace
bauen, `pytest` gegen `ihk_pepper_tests` laufen lassen, Ergebnis mit dem
im [Systemarchitektur](../architecture/index.md)-Thema genannten
Sollstand (384/384) vergleichen.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Der beschriebene Build-/Test-Ablauf ist genau der,
der in `docs/DEVELOPMENT_ORDER_03_REPORT.md` dokumentiert und dort
tatsächlich ausgeführt wurde (384/384 Python-Tests, BT-Test 17/0/0/3).
Kein Schritt hier benötigt oder berührt echte Hardware.

## Weiterführende Inhalte und nächste Schritte

Weiter mit [Systemarchitektur](../architecture/index.md) für den
Überblick über alle Teilsysteme, oder direkt mit
[ROS 2](../ros2/index.md) für den Paketaufbau.

```{toctree}
:maxdepth: 1
:hidden:

repository-and-environment
```
