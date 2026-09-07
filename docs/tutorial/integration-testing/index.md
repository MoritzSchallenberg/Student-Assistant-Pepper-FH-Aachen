# Integration und Tests

## Überblick und Ziel des Themas

Wie sich Dialog- und Gesten-Pfad **ohne** angeschlossenen Pepper und
ohne RealSense-Hardware vollständig durchspielen lassen — echte
Prozesse, echte ROS2-Topics/Actions, nur die letzte Hardware-Stufe
gemockt.

## Position in der Pepper-Gesamtarchitektur

Der praktische Beweis dafür, dass
[Dialog und Gedächtnis](../dialogue-memory/index.md) und
[Gesten und Kinematik](../gestures-kinematics/index.md) tatsächlich
zusammenspielen, nicht nur als isolierte Module.

## Lernziele

Nach diesem Thema kannst du:

1. `manual_dialogue_e2e_check.py` selbst ausführen und sein Ergebnis
   interpretieren;
2. `gesturectl dry-run`/`validate` für eine beliebige Katalog-Geste
   ausführen;
3. erklären, warum ein bestandener Offline-/Dry-Run-Test **nicht**
   dasselbe ist wie ein Hardware-Test.

## Voraussetzungen

[Dialog und Gedächtnis](../dialogue-memory/index.md) und
[Gesten und Kinematik](../gestures-kinematics/index.md).

## Pepper-spezifische Verwendung

{{ pepper }} Alle Übungen hier laufen gegen dieselben ROS2-Interfaces,
die auch der echte Pepper am Ende nutzt — nur der letzte Hardware-
Schritt fehlt.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Offline-Dialogübung
:link: offline-dialogue-test
:link-type: doc

{{ offlinetested }} Die vollständige, tatsächlich durchgeführte
Dialog-Pipeline ohne Hardware.
:::

:::{grid-item-card} Gestenvalidierung
:link: gesture-validation
:link-type: doc

{{ offlinetested }} Katalog laden, validieren, per Dry-Run prüfen --
alle Schritte ohne Hardware.
:::

::::

## Praktische Übungen

Siehe die beiden Unterthemen — beide enthalten vollständig
durchgeführte, reale Übungen mit tatsächlichem Terminal-Output.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Jede Übung auf dieser Seite wurde für dieses
Tutorial tatsächlich ausgeführt (nicht nur aus früheren Berichten
übernommen) — siehe die konkreten Kommandos und Ergebnisse auf den
Unterseiten.

## Weiterführende Inhalte und nächste Schritte

[Deployment](../deployment/index.md) für den Weg von hier zu einem
echten NUC.

```{toctree}
:maxdepth: 1
:hidden:

offline-dialogue-test
gesture-validation
```
