# Abdeckungslücke

{{ offlinetested }}

## Was diese Seite ist

Der reale, geometrische Nachweis, dass eine einzelne kopfmontierte
RealSense **nicht** für eigenständige Livebewegung ausreicht — und was
das strukturell zur Folge hat.

## Der Nachweis

`coverage_analysis.py` (reines Python-Modul, kein ROS) berechnet per
Lochkamera-Näherung zwei Größen:

- den **Nahbereichs-Blindfleck**: wie nah ein Hindernis auf Bodenhöhe an
  die Kamera heran kann, bevor es aus dem Sichtfeld fällt;
- den **horizontal komplett unabgedeckten Winkel**.

Mit den realen Pepper-/RealSense-Referenzwerten (Kopfhöhe ~1,2 m,
RealSense-D435-Datenblatt: horizontal ~87°, vertikal ~58°) bestätigt der
Test explizit und reproduzierbar:

```text
test_single_realsense_on_pepper_head_is_not_sufficient_for_live_motion
uncovered_horizontal_deg = 273°
```

Eine einzelne Kamera mit ~87° horizontalem Sichtfeld deckt nur einen
schmalen Sektor nach vorne ab — seitlich und hinten bleibt der Roboter
für diese Kamera komplett blind.

## Ein echter, während der Entwicklung gefundener Fehler

Beim Implementieren wurde ein echter Geometriefehler in
`coverage_analysis.py` selbst gefunden und behoben: Tangens bei einem
Blickwinkel über 90° lieferte einen negativen statt eines
Null-Blindflecks. Gefunden per Test
(`test_camera_looking_straight_down_has_zero_blind_zone`), nicht durch
Inspektion — ein Beispiel dafür, dass Tests hier echte Fehler finden,
nicht nur bestehendes Verhalten dokumentieren.

## Strukturelle Konsequenz, nicht nur Dokumentation

```{figure} ../_static/images/pepper-realsense-tf-tree.svg
:alt: Derselbe TF-Baum wie auf der vorherigen Seite, hier zur Einordnung der Abdeckungslücke referenziert.
:width: 60%

Die Kamera sitzt fest am Kopf -- ihr Sichtfeld deckt nur einen
schmalen vorderen Sektor ab, siehe Text.
```

Wegen dieses Befunds bleibt Livebewegung **strukturell** gesperrt, nicht
nur als Empfehlung:

1. **Motion Guard** ([Systemüberblick](../architecture/system-overview.md#sicherheit-als-querschnittsthema))
   lässt `enable_live_motion` standardmäßig `false` und prüft die
   RealSense-Diagnose als eine von mehreren unabhängigen Bedingungen.
2. Der unabhängige **Collision-Monitor-`BumperStop`** und **Peppers
   eigener Laser** (`laser_filter_node`, weiterhin aktiv, aber **nicht**
   mehr Teil der Nav2-Costmap seit der RealSense-only-Umstellung)
   bleiben als zusätzliche, RealSense-unabhängige Nahbereichs-
   Absicherung bestehen.

## Für Entwicklungsauftrag 4 empfohlen (noch nicht umgesetzt)

Laut `docs/DEVELOPMENT_ORDER_02_REPORT.md`: die Abdeckungslücke muss vor
jedem produktiven Live-Einsatz entweder durch zusätzliche Sensorik oder
einen bewusst reduzierten Geltungsbereich (z.B. nur sehr langsame,
eng überwachte Fahrten) geschlossen oder explizit eingehegt werden — dies
ist eine offene Sicherheitsfrage, kein Kritikpunkt an der bisherigen
Arbeit.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Der Nachweis selbst ist ein reiner Geometrietest,
unabhängig von echter Hardware — daher zuverlässig, auch ohne
angeschlossene Kamera. {{ navblocked }} Die Konsequenz (Livebewegung
gesperrt) gilt, bis diese Lücke geschlossen ist.

## Nächster Schritt

[Mapping und Navigation](../mapping-navigation/index.md).
