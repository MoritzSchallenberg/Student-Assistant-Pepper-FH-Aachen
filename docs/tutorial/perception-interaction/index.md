# Wahrnehmung und Interaktion

## Überblick und Ziel des Themas

Wie Pepper überhaupt "merkt", dass jemand da ist, wie stabil dieser
Track ist, wie interessiert die Person wirkt, und wie eine Winkgeste
zeitlich robust (nicht per Einzelbild) erkannt wird.

## Position in der Pepper-Gesamtarchitektur

Der Eingang für praktisch alles Interaktive: der
[Verhaltensbaum](../decision-making/index.md) wählt seine Zielperson
über `SelectStablePerson`, gestützt auf genau die Werte, die dieses
Thema erzeugt.

## Lernziele

Nach diesem Thema kannst du:

1. erklären, warum eine ByteTrack-`track_id` **keine** Personenidentität
   ist (siehe auch [Dialog und Gedächtnis](../dialogue-memory/index.md));
2. die Interessens-Score-Formel (positive/negative Gewichte) benennen
   und ein Beispiel-Szenario durchrechnen;
3. den Winkgesten-Zustandsautomaten (`IDLE → ARM_RAISED →
   WAVE_CANDIDATE → WAVE_CONFIRMED → COOLDOWN`) erklären und begründen,
   warum ein Einzelbild nie ausreicht.

## Voraussetzungen

[ROS 2](../ros2/index.md) — dieses Thema nutzt `ihk_pepper_perception`
direkt.

## Pepper-spezifische Verwendung

{{ pepper }} Da Peppers eigene `HumanPerception`-Signale blockiert sind
(siehe [Pepper-Plattform und Sicherheit](../pepper-platform/index.md)),
baut dieses Projekt Personenwahrnehmung komplett über eine eigene
YOLOv8-Pose-Pipeline auf den Kamera-Topics — unabhängig von NAOqi.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Personen-Engagement
:link: person-engagement
:link-type: doc

{{ documented }} Interessens-Score-Formel und Winkgesten-Erkennung im
Detail.
:::

::::

## Praktische Übungen

{{ offlineexercise }} `python3 -m pytest
ros2/autonomy_ws/src/ihk_pepper_tests/test/test_wave_detector.py
ros2/autonomy_ws/src/ihk_pepper_tests/test/test_interest_scoring.py -v`
ausführen — siehe [Personen-Engagement](person-engagement.md) für die
Herleitung der Testfälle.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Beide Module sind reine, ROS-freie Python-Funktionen
mit eigener Unit-Testsuite — unabhängig von echter Kamera-/Pepper-
Hardware testbar und getestet. {{ hwverificationrequired }} für die
tatsächliche Erkennungsgüte gegen eine echte Kamera und echte Personen.

## Weiterführende Inhalte und nächste Schritte

[Entscheidungsfindung](../decision-making/index.md) für den
Verhaltensbaum, der diese Werte konsumiert.

```{toctree}
:maxdepth: 1
:hidden:

person-engagement
```
