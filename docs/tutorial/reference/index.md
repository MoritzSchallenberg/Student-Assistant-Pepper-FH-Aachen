# Referenz

## Überblick und Ziel des Themas

Nachschlagematerial: die vollständige Interface-Liste, die Status-/
Marker-Legende, und Verweise auf die bestehende, tiefere
Projektdokumentation im Repository-Wurzelverzeichnis.

## Position in der Pepper-Gesamtarchitektur

Kein eigener Datenfluss — reines Nachschlagewerk für alle anderen
Themen.

## Lernziele

Nach diesem Thema kannst du jeden Marker auf dieser Seite korrekt
nachschlagen und weißt, wo im Repository die tiefere, technische Doku
zu jedem Thema liegt.

## Voraussetzungen

Keine.

## Pepper-spezifische Verwendung

{{ pepper }} Alle Interfaces hier sind `ihk_pepper_*`-spezifisch.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Interfaces
:link: interfaces
:link-type: doc

{{ documented }} Alle Messages/Services/Actions, real per
`ros2 interface list` bestätigt.
:::

:::{grid-item-card} Status-Legende
:link: status-legend
:link-type: doc

Die vollständige Definition jedes Schwierigkeits-, Verifikations- und
Sicherheitsmarkers.
:::

::::

## Praktische Übungen

Keine eigenen Übungen — siehe die jeweiligen Themenseiten.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ documented }}

## Weiterführende Inhalte und nächste Schritte

Bestehende, tiefere Projektdokumentation im Repository-
Wurzelverzeichnis (`docs/*.md`, nicht Teil dieses Tutorials, aber von
praktisch jeder Seite hier aus verlinkt):

- `docs/STATUS.md`, `docs/CAPABILITIES.md` -- Hardware-Fähigkeiten.
- `docs/DEVELOPMENT_ORDER_01_REPORT.md`,
  `docs/DEVELOPMENT_ORDER_02_REPORT.md`,
  `docs/DEVELOPMENT_ORDER_03_REPORT.md` -- die vollständige,
  chronologische Entwicklungsgeschichte.
- `docs/ARCHITECTURE_REALSense_BT.md`,
  `docs/REALSENSE_NAVIGATION_ARCHITECTURE.md`,
  `docs/REALSENSE_CALIBRATION.md` -- RealSense/Navigation im Detail.
- `docs/LLM_PIPELINE_DESIGN.md`, `docs/LLM_RUNTIME_ARCHITECTURE.md`,
  `docs/LLM_PROVIDER_CONFIGURATION.md` -- die LLM-Pipeline im Detail.
- `docs/PERSON_MEMORY_DESIGN.md`, `docs/PERSON_MEMORY_RUNTIME.md` --
  das Personengedächtnis im Detail.
- `docs/GESTURE_AUTHORING.md`, `docs/GESTURE_TRANSPORT.md`,
  `docs/GESTURE_LIVE_TEST_CHECKLIST.md` -- Gesten im Detail.
- `docs/NAVIGATION_SAFETY_ACCEPTANCE.md` -- die Abnahme-Checkliste für
  echte Livenavigation.
- `docs/INSTALL.md`, `docs/configuration.md`, `docs/operations.md`,
  `docs/troubleshooting.md`, `docs/rollback.md` -- Betrieb.

```{toctree}
:maxdepth: 1
:hidden:

interfaces
status-legend
```
