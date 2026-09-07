# Pepper-Plattform und Sicherheit

## Überblick und Ziel des Themas

Was der reale Pepper 1.8 dieses Projekts tatsächlich kann und wo seine
harten, hardwarebedingten Grenzen liegen — als Grundlage für jede
spätere Entscheidung, ob eine geplante Funktion überhaupt sinnvoll ist.

## Position in der Pepper-Gesamtarchitektur

Diese Seite ist die Hardware-Wahrheit, an der sich jede andere
Themenseite messen lassen muss — insbesondere
[Gesten und Kinematik](../gestures-kinematics/index.md) (Gelenkgrenzen)
und [Mapping und Navigation](../mapping-navigation/index.md)
(Fahr-Interlock, Sensorabdeckung).

## Lernziele

Nach diesem Thema kannst du:

1. die real getesteten Fähigkeiten (Sprechen, Bewegen, Fahren, Sensoren)
   von den nur "als aufrufbar bestätigten" unterscheiden;
2. die drei wichtigsten harten Grenzen benennen (1-Motor-Hand, Fahr-
   Interlock bei Ladekabel, ~1 Hz Sensor-Update-Rate);
3. das Zwei-Schlüssel-Sicherheitssystem und Motion Guard erklären.

## Voraussetzungen

Keine über [Erste Schritte](../getting-started/index.md) hinaus.

## Pepper-spezifische Verwendung

{{ pepper }} Diese ganze Seite ist per Definition Pepper-spezifisch —
Modell "Pepper 1.8", NAOqi `2.9.5.172`, Robotername `pepper`, angebunden
über SSH + `qicli` (kein Root nötig, siehe
[Netzwerk und Zugriff](network-and-access.md)).

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Fähigkeiten und Grenzen
:link: capabilities-and-limits
:link-type: doc

{{ documented }} Was real getestet ist, was nur bestätigt-aufrufbar ist,
und die harten Grenzen.
:::

:::{grid-item-card} Netzwerk und Zugriff
:link: network-and-access
:link-type: doc

{{ documented }} SSH/`qicli`-Architektur, Port-9503-Besonderheit, warum
kein Root nötig ist.
:::

::::

## Praktische Übungen

{{ readonlypepper }} Ohne echten Pepper: keine Hardware-Übung auf dieser
Überblicksseite möglich. Mit erreichbarem Pepper: `qicli call
ALBattery.getBatteryCharge` als risikofreier erster Verbindungstest
(rein lesend) — siehe
[Fähigkeiten und Grenzen](capabilities-and-limits.md).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ hwverificationrequired }} Die auf dieser Seite referenzierten
Fähigkeiten wurden in früheren Entwicklungssitzungen gegen einen echten
Pepper getestet (siehe `docs/STATUS.md`/`docs/CAPABILITIES.md` im
Repository-Wurzelverzeichnis) — **in der aktuellen Session war kein
Pepper erreichbar**, nichts hier wurde für dieses Tutorial neu
hardwareverifiziert. Vor jeder produktiven Nutzung: Stand gegen einen
tatsächlich angeschlossenen Roboter neu prüfen.

## Weiterführende Inhalte und nächste Schritte

[RealSense und Koordinatenrahmen](../realsense-frames/index.md) für die
Kamera, die Pepper selbst nicht besitzt, aber für Navigation zusätzlich
trägt.

```{toctree}
:maxdepth: 1
:hidden:

capabilities-and-limits
network-and-access
```
