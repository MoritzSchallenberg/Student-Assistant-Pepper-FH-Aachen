# Pepper Developer Tutorial

Ein technisches Entwickler-Tutorial für das **IHK-Pepper**-Projekt: ein
autonomes Dialog-, Interaktions- und Navigationssystem für den SoftBank-
Robotics-Humanoiden **Pepper 1.8**, aufgebaut auf **ROS 2 Jazzy** und
einer kopfmontierten **Intel-RealSense**-Kamera.

<a class="pdt-cta" href="architecture/index.html">Mit der Architektur beginnen →</a>

## Für wen dieses Tutorial gedacht ist

Für alle, die an diesem Code weiterentwickeln oder ihn warten: neue
Entwickler:innen, die sich orientieren wollen, und alle, die ein
konkretes Thema (den Verhaltensbaum, die LLM-Dialog-Pipeline, eine
Geste, die RealSense-Navigationskette) nachschlagen. Python- und
grundlegende ROS-2-Kenntnisse werden vorausgesetzt; dieses Tutorial
erklärt ROS 2 nicht von Grund auf neu (siehe
[Erste Schritte](getting-started/index.md) für die genauen Annahmen und
wo Lücken zu schließen sind).

## Was dieses Tutorial abdeckt

Den tatsächlichen, aktuellen Implementierungsstand nach
**Entwicklungsauftrag 3** (`docs/DEVELOPMENT_ORDER_03_REPORT.md` im
Wurzelverzeichnis dieses Repositories) — Personen-Tracking und
Winkgesten-Erkennung, den Interaktions-Verhaltensbaum, RealSense-only-
Mapping und -Navigation (Entwicklungsauftrag 2), die dreistufige
LLM-Dialog-Pipeline, einwilligungsgebundenes Personengedächtnis, den
kinematischen Gestenkatalog und das NUC-Deployment. Jede Seite gibt
klar an, was **dokumentiert**, was **offline getestet**, was **in
Simulation getestet** und was tatsächlich **hardwareverifiziert** ist —
das sind unterschiedliche Dinge, und diese Seite verwischt sie nie.

:::{admonition} Kein Pepper in fast der gesamten bisherigen Testgeschichte dieses Repositories
:class: important

Fast alles hier Beschriebene wurde **ohne** angeschlossenen echten
Pepper gebaut und geprüft — echte Unit-Tests, echte Prozessstarts, echte
Dry-Runs, aber keine echte Roboterbewegung. Lies auf jeder Seite den
Verifikationsmarker, nicht nur den Schwierigkeitsmarker, bevor du
annimmst, dass etwas tatsächlich auf dem Roboter gelaufen ist.
:::

## Themenbereiche

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Erste Schritte
:link: getting-started/index
:link-type: doc

Repository-Aufbau, Umgebungs-Setup und wie diese Seite zu lesen ist.
:::

:::{grid-item-card} Systemarchitektur
:link: architecture/index
:link-type: doc

Wie alle Teilsysteme zusammenspielen: Wahrnehmung, Verhaltensbaum,
Dialog, Navigation, Gesten.
:::

:::{grid-item-card} ROS 2
:link: ros2/index
:link-type: doc

Der `ihk_pepper_*`-Paketaufbau, Schnittstellen, und wie die Pakete
voneinander abhängen.
:::

:::{grid-item-card} Pepper-Plattform und Sicherheit
:link: pepper-platform/index
:link-type: doc

Reale Hardwarefähigkeiten, Einschränkungen, Netzwerk-Setup und das
Sicherheitsmodell.
:::

:::{grid-item-card} RealSense und Koordinatenrahmen
:link: realsense-frames/index
:link-type: doc

Kameramontage, die TF-Kette, und die bestätigte Abdeckungslücke einer
einzelnen Kamera.
:::

:::{grid-item-card} Mapping und Navigation
:link: mapping-navigation/index
:link-type: doc

RealSense-only RTAB-Map-Odometrie/-SLAM, Nav2, und warum Livenavigation
gesperrt bleibt.
:::

:::{grid-item-card} Wahrnehmung und Interaktion
:link: perception-interaction/index
:link-type: doc

Personen-Tracking, Interessens-Bewertung und Winkgesten-Erkennung.
:::

:::{grid-item-card} Entscheidungsfindung
:link: decision-making/index
:link-type: doc

Der BehaviorTree.CPP-Interaktionsbaum und seine sicherheitsorientierte
Prioritätsreihenfolge.
:::

:::{grid-item-card} Dialog und Gedächtnis
:link: dialogue-memory/index
:link-type: doc

Die dreistufige LLM-Pipeline, das strukturierte Aktionsprotokoll und das
einwilligungsgebundene Personengedächtnis.
:::

:::{grid-item-card} Gesten und Kinematik
:link: gestures-kinematics/index
:link-type: doc

Der Gestenkatalog, der kinematische Compiler, der Bewegungstransport und
beaufsichtigtes Live-Testen.
:::

:::{grid-item-card} Integration und Tests
:link: integration-testing/index
:link-type: doc

Offline-Dialog- und Gestenvalidierung, ganz ohne Hardware-Zugriff.
:::

:::{grid-item-card} Deployment
:link: deployment/index
:link-type: doc

Entwicklung auf dem allgemeinen NUC heute, und der Ansible-Weg zu einem
dedizierten Pepper-NUC.
:::

:::{grid-item-card} Referenz
:link: reference/index
:link-type: doc

Schnittstellen, die Status-/Marker-Legende und weiterführende Inhalte.
:::

::::

## Wie diese Seite zu lesen ist

Jedes Thema und jede Übung trägt einen Schwierigkeitsmarker:

{{ foundation }} {{ intermediate }} {{ advanced }} {{ research }}

und einen Verifikationsmarker, der beschreibt, was tatsächlich geprüft
wurde, nicht was bloß plausibel ist:

{{ documented }} {{ offlinetested }} {{ simulationtested }}
{{ hardwareverified }} {{ hwverificationrequired }} {{ experimental }}
{{ unverified }} {{ historical }}

Jede Übung, die echte Pepper-Hardware betrifft, trägt zusätzlich genau
eine Sicherheitsstufe:

{{ offlineexercise }} {{ readonlypepper }} {{ supervisedgesture }}
{{ supervisedmotion }} {{ navblocked }}

Siehe [Status-Legende](reference/status-legend.md) für die vollständige
Definition jedes Markers, und
[ASSET_PROVENANCE.yml](ASSET_PROVENANCE.yml) dafür, wie jedes Bild auf
dieser Seite vor der Veröffentlichung rechtlich geprüft wird.

```{toctree}
:hidden:
:maxdepth: 2
:caption: Erste Schritte

getting-started/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Systemarchitektur

architecture/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: ROS 2

ros2/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Pepper-Plattform und Sicherheit

pepper-platform/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: RealSense und Koordinatenrahmen

realsense-frames/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Mapping und Navigation

mapping-navigation/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Wahrnehmung und Interaktion

perception-interaction/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Entscheidungsfindung

decision-making/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Dialog und Gedächtnis

dialogue-memory/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Gesten und Kinematik

gestures-kinematics/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Integration und Tests

integration-testing/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Deployment

deployment/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Referenz

reference/index
```
