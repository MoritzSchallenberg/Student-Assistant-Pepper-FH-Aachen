# Systemarchitektur

## Überblick und Ziel des Themas

Wie die elf `ihk_pepper_*`-Pakete zusammenspielen: welche Daten von wo
nach wo fließen, wer welche Priorität hat, und wo die Sicherheitsschicht
sitzt. Dieses Thema ist der Einstiegspunkt vor jedem tieferen Thema.

## Position in der Pepper-Gesamtarchitektur

Diese Seite selbst IST der Überblick über die Gesamtarchitektur — alle
anderen Themen vertiefen jeweils einen Ausschnitt davon.

## Lernziele

Nach diesem Thema kannst du:

1. die elf Pakete und ihre jeweilige Rolle benennen;
2. die Priorität des Verhaltensbaums (Safety > Battery > GreetAndApproach
   > Dialogue > Interaction > Presentation > IdleAttract) erklären;
3. die zwei Hauptdatenpfade (Wahrnehmung→Interaktion,
   RealSense→Navigation) skizzieren;
4. die drei sich überlappenden Sicherheitsschichten benennen.

## Voraussetzungen

[Erste Schritte](../getting-started/index.md) abgeschlossen — ein
gebauter Workspace mit grüner Testsuite.

## Pepper-spezifische Verwendung

{{ pepper }} Jede Komponente auf dieser Seite ist speziell für Pepper
1.8 gebaut, nicht generisch für "einen Roboter".

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Systemüberblick
:link: system-overview
:link-type: doc

{{ documented }} Der vollständige Datenfluss, Paketrollen,
Sicherheitsschichten.
:::

::::

## Praktische Übungen

Keine eigene Hardware-Übung auf dieser Überblicksseite — die
praktischen Übungen sitzen bei den einzelnen Themen selbst (z.B.
[Offline-Dialogübung](../integration-testing/offline-dialogue-test.md)).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ documented }} Architektur-/Code-Struktur ist real und im Repository
nachprüfbar; Live-Hardware-Verifikation ist ein separates, deutlich
kleineres Thema — siehe die jeweiligen Verifikationsmarker auf jeder
Themenseite.

## Weiterführende Inhalte und nächste Schritte

[ROS 2](../ros2/index.md) für den Paketaufbau im Detail, oder direkt
[Entscheidungsfindung](../decision-making/index.md) für den
Verhaltensbaum.

```{toctree}
:maxdepth: 1
:hidden:

system-overview
```
