# Fähigkeiten und Grenzen

{{ documented }}

## Was diese Seite ist

Eine kondensierte, mit Quellenangabe versehene Zusammenfassung von
`docs/CAPABILITIES.md` und `docs/STATUS.md` im Repository-
Wurzelverzeichnis — dort steht die vollständige, laufend aktualisierte
Fassung inklusive aller `qicli.py`-Methodennamen.

## Real getestet (Auszug)

```{list-table}
:header-rows: 1
:widths: 34 66

* - Fähigkeit
  - Status
* - Sprechen (`say()` oder ROS-Topic `/speech`)
  - {{ hardwareverified }} beide Wege getestet
* - Einzelnes Gelenk bewegen (`set_angle()`)
  - {{ hardwareverified }} zuverlässig
* - Winken (`wave()`)
  - {{ hardwareverified }}
* - Fahren (`moveTo(x, y, theta)`)
  - {{ hardwareverified }} -- **nur ohne Ladekabel** (Fahr-Interlock)
* - Kamera (`/camera/{front,bottom,depth,stereo}/image_raw`)
  - {{ hardwareverified }} ~1 Hz, 320×240
* - Laser (`/laser`)
  - {{ hardwareverified }} 240° FOV, ~61 Punkte, ~1,1 Hz
* - Sonar vorne/hinten
  - {{ hardwareverified }} je 1 Wert, kein Scan
* - Berührung (Kopf/Hände/Bumper)
  - {{ hardwareverified }}
* - Akkustand (`get_battery()`)
  - {{ hardwareverified }}
```

## Als aufrufbar bestätigt, aber nicht live ausgeführt

- Zu Navigationsziel fahren (`ALNavigation.computePathInMap`) — bewusst
  nicht in vollgestelltem Raum getestet.
- Auf Person zugehen (`HumanAwareness.makeApproachHuman`) — bewegt den
  Roboter autonom, bewusst nicht getestet.
- Eigene Kartenerstellung (`Mapping.makeMap()`).

## Blockiert / nicht erreichbar

- **Personen-/Gesichtserkennung (Rohdaten)**: `HumanPerception`-Signale
  sind weder per `qicli` noch per `ALMemory` abrufbar — bräuchten eine
  echte `qi`-Python-Signal-Subscription, die an einem TLS-
  Zertifikatsproblem scheitert (Port 9503, selbstsigniertes Aldebaran-
  Zertifikat). Bewusst nicht weiterverfolgt (Architektur-Entscheidung,
  siehe [Netzwerk und Zugriff](network-and-access.md)) — deshalb baut
  dieses Projekt Personen-Tracking komplett über eine eigene
  YOLOv8-Pose-Pipeline statt über NAOqis eingebaute Personenerkennung,
  siehe [Wahrnehmung und Interaktion](../perception-interaction/index.md).

## Harte Grenzen (nicht per Software behebbar)

1. **Hand hat nur 1 Motor** (auf/zu) — keine einzelnen Finger, kein
   Fingerzeigen, keine Peace-Zeichen. Relevant für jede Zeige-Geste, siehe
   [Gestenformat](../gestures-kinematics/gesture-format.md).
2. **Fahr-Interlock**: `moveTo()` funktioniert nur, wenn kein Ladekabel
   angeschlossen ist.
3. **Sensor-Update-Rate ~1 Hz** (Kamera, Laser, Sonar) — hardware-/
   NAOqi-bedingt, nicht durch mehr Rechenleistung behebbar. Ein
   Flaschenhals für jedes Verhalten, das schnell auf Bewegung reagieren
   muss.
4. **Gehaltene Posen verziehen sich nach ~10s** (z.B. eine T-Pose) —
   ein nicht identifizierter Idle-Mechanismus greift ein, auch nachdem
   `raise_arms_sideways()` "Breathing" bereits deaktiviert hat. Gesten
   müssen deshalb kurz sein, nicht dauerhaft gehalten werden.
5. **Rechter Arm etwas ungenauer** als linker (mechanische
   Kalibrierungs-Differenz dieser konkreten Einheit).

## Für den Verhaltensbaum: Knoten-Kategorien

- **Bedingungen** (Sensor-Checks): Touch-Status, Akkustand, erkannter
  Text (Whisper-Pipeline), Hindernis nah, Stimmung.
- **Aktionen**: Sprechen, Gelenk/Geste bewegen, LED färben, Tablet
  anzeigen, Posen einnehmen.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ hwverificationrequired }} Alle oben als hardwareverified markierten
Punkte stammen aus früheren Sessions mit angeschlossenem Pepper (Stand
`docs/STATUS.md`, 2026-08-17/18/20) — nicht aus dieser Tutorial-Session
neu geprüft.

## Nächster Schritt

[Netzwerk und Zugriff](network-and-access.md).
