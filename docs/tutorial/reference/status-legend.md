# Status-Legende

## Was diese Seite ist

Die vollständige, verbindliche Definition jedes Markers auf dieser
Seite -- übernimmt das Markerprinzip des ALeRT-Tutorials
(Learning-Robotics-Crash-Course), mit Pepper-spezifischen Markern.

## Schwierigkeit

```{list-table}
:header-rows: 1
:widths: 25 75

* - Marker
  - Bedeutung
* - {{ foundation }}
  - Braucht kein vorheriges Thema über das eigene Voraussetzungen-Kapitel
    hinaus.
* - {{ intermediate }}
  - Baut direkt auf einem oder mehreren Foundation-Themen auf.
* - {{ advanced }}
  - Eine reale, im Projekt genutzte Fähigkeit, die mehr Hintergrund oder
    Sorgfalt braucht.
* - {{ research }}
  - Dokumentiert der Vollständigkeit halber, nicht Teil des heutigen
    produktiven Pfads.
```

## Verifikation

```{list-table}
:header-rows: 1
:widths: 25 75

* - Marker
  - Bedeutung
* - {{ documented }}
  - Bestätigt über eine reale Quelle (Code, Bericht, Repository-Doku).
* - {{ offlinetested }}
  - Tatsächlich ausgeführt -- Unit-Test, Prozessstart, `dry-run`,
    `validate`, o.ä. -- **ohne** Pepper-Hardware.
* - {{ simulationtested }}
  - Tatsächlich in einer Simulation (z.B. RViz-`preview`) geprüft.
* - {{ hardwareverified }}
  - Tatsächlich auf dem echten, angeschlossenen Pepper ausgeführt und
    unter Aufsicht bestätigt.
* - {{ hwverificationrequired }}
  - Plausibel/vorbereitet, aber noch nicht auf echter Hardware geprüft
    -- eine echte Prüfung ist vor produktivem Einsatz nötig.
* - {{ experimental }}
  - Bekanntermaßen unvollständig oder instabil -- Kanten erwartbar.
* - {{ unverified }}
  - Plausibel, aber nicht geprüft.
* - {{ historical }}
  - Nicht mehr aktuell, nur zum Kontext erhalten.
```

**Verbindliche Regeln** (Arbeitspaket 15, Abschnitt 15.4):

- Ein bestandener Mock-/Offline-Test ist **nicht** {{ hardwareverified }}.
- Ein erfolgreicher Kinematiktest ohne echten Pepper ist
  {{ offlinetested }}, nicht mehr.
- Eine live ausgeführte Armbewegung darf **nur** nach einem
  beaufsichtigten Test als {{ hardwareverified }} gelten -- und nur,
  nachdem ein Mensch das manuell in der Geste-YAML eingetragen hat (kein
  Tool in diesem Projekt markiert sich selbst als
  hardwareverifiziert, siehe
  [Sichere Gestenentwicklung](../gestures-kinematics/safe-gesture-development.md)).
- Navigation bleibt {{ navblocked }}, solange die in
  Entwicklungsauftrag 2 ermittelte Sensorabdeckung nicht ausreicht --
  siehe [Abdeckungslücke](../realsense-frames/coverage-gap.md).
- Verifikationsmarker stehen an der **konkreten Behauptung oder Übung**,
  nicht pauschal am Seitenanfang, wenn unterschiedliche Aussagen einer
  Seite unterschiedlich geprüft sind.

## Sicherheitsstufen (nur für Hardware-Übungen)

```{list-table}
:header-rows: 1
:widths: 25 75

* - Marker
  - Bedeutung
* - {{ offlineexercise }}
  - Keine Hardware beteiligt -- risikofrei jederzeit ausführbar.
* - {{ readonlypepper }}
  - Darf gegen einen erreichbaren Pepper ausgeführt werden, aber nur
    lesend (z.B. Akkustand abfragen) -- keine Bewegung, keine
    Zustandsänderung.
* - {{ supervisedgesture }}
  - Eine Gestenbewegung -- nur unter direkter Aufsicht, nach
    `gesturectl live-test`s vollständiger Checkliste.
* - {{ supervisedmotion }}
  - Eine Fahrbewegung -- nur unter direkter Aufsicht, nur mit
    explizitem `enable_live_motion`.
* - {{ navblocked }}
  - Live-Navigation ist strukturell gesperrt (Motion Guard) -- diese
    Übung ist derzeit **nicht** durchführbar, unabhängig von Aufsicht.
```

## Pepper-Marker

{{ pepper }} kennzeichnet Inhalt, der spezifisch für diesen konkreten
Roboter (Pepper 1.8, NAOqi 2.9.5.172) gilt, statt eine generische
ROS-2-Aussage zu sein.
