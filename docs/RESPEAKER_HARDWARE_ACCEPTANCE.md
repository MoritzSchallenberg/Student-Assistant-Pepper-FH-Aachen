# ReSpeaker/Wakeword-Hardwareabnahme

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6, Abschnitt 20.

**Keine der folgenden fünf Phasen wurde in dieser Session durchgeführt
-- kein ReSpeaker Core v2.0 und kein Pepper waren erreichbar.** Dieses
Dokument beschreibt den vorgesehenen Ablauf und die Freigabekriterien,
analog zu `docs/NAVIGATION_SAFETY_ACCEPTANCE.md` aus Entwicklungsauftrag 2.
Keine Funktion aus AP6 darf als hardwareverifiziert bezeichnet werden,
solange die zugehörige Phase hier nicht mit einem echten,
dokumentierten Ergebnis abgeschlossen ist.

## Phase A -- ReSpeaker allein

Keine Verbindung zu Pepper erforderlich. Zu prüfen:
Kanalzahl/-reihenfolge, Samplerate, Daueraufnahme (Stabilität über
Stunden), Reconnect-Verhalten (WLAN-Aussetzer simulieren), Paketverlust
unter Last, Zeitstempel-Drift, Wakeword-Erkennungsrate, Richtungs-
bestimmung (siehe `docs/RESPEAKER_CALIBRATION.md`).

**Freigabekriterium**: alle Punkte dokumentiert, keiner davon
"vermutlich funktioniert" -- entweder gemessen oder als offen markiert.

**Status: NICHT DURCHGEFÜHRT.**

## Phase B -- ReSpeaker und RealSense

Keine Pepper-Bewegung. Zu prüfen: TF/Koordinatensysteme kalibrieren
(siehe `docs/RESPEAKER_CORE_V2_INTEGRATION.md`, Abschnitt TF -- diese
Transformation existiert im Code noch NICHT, Phase B kann daher erst
beginnen, NACHDEM sie implementiert wurde), Schallstrahl gegen
Personenpeilung vergleichen (Einzelperson, zwei Personen, Person
außerhalb des Sichtfelds, Hintergrundgespräch, bewegte Person).

**Status: NICHT DURCHGEFÜHRT** (zusätzlich blockiert durch die fehlende
TF-Transformation, siehe oben -- kein reines Terminverschiebungsproblem).

## Phase C -- Pepper-Kopf

Ausschließlich Kopf, niedrige Geschwindigkeit, freier Sicherheitsbereich,
**Bedienperson am Not-Stopp erforderlich**. Zu prüfen: Winkelbegrenzung
(`SetHeadPose` klemmt auf `HEAD_YAW/PITCH_OPERATIONAL_*` -- am echten
Roboter verifizieren, dass die Bewegung tatsächlich dort stoppt),
Lease-Verweigerung (zweite Anfrage während einer laufenden Bewegung
muss abgelehnt werden), Cancel (Abbruch während der Bewegung muss den
Kopf wirklich stoppen -- NICHT nur den ROS2-Goal-Status ändern, siehe
`docs/ACTION_CANCELLATION.md` für den Unterschied), Verbindungsverlust,
Rückkehr in neutrale Kopfposition.

Erreichbar über `interaction_full_safe.launch.py mode:=respeaker_head_test
i_confirm_head_test_supervised:=true` (Bridge NICHT dry_run -- echte
Bewegung möglich).

**Status: NICHT DURCHGEFÜHRT.**

## Phase D -- Gesprächsfokus

Zu prüfen: frontale Zielperson, seitlicher Störsprecher, rückwärtiger
Störsprecher, Raumgeräusche, Pepper-TTS (Selbstauslösungstest --
Zielwert aus Auftrag Abschnitt 21: keine Selbstauslösung in 20
definierten TTS-Testdurchläufen), Halbduplex, optional AEC (nicht
implementiert in diesem Auftrag, siehe Auftrag Abschnitt 9 -- Halbduplex
bleibt verpflichtend, `allow_barge_in` bleibt `false`), keine Sprach-/
biometrische Datenspeicherung (Code-Review reicht hier aus, siehe
`docs/RESPEAKER_CORE_V2_INTEGRATION.md`, Abschnitt Datenschutz).

**Status: NICHT DURCHGEFÜHRT.**

## Phase E -- vollständige Begrüßung

Wakeword → Kopfausrichtung → visuelle Bestätigung → Winken →
Rückwinkerkennung → Annäherung weiterhin als Nav2-Mock/Dry-Run (KEINE
reale Annäherung Teil dieser automatischen Testausführung, siehe
Auftrag Abschnitt 20 ausdrücklich).

**Status: NICHT DURCHGEFÜHRT.**

## Was STATTDESSEN in dieser Session verifiziert wurde

Jede einzelne Komponente ist gegen Fakes/Mocks/synthetische Daten
unit-getestet (vollständige Liste in
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`). Die Launch-Modi
`respeaker_offline_test`/`respeaker_hardware_test`/`audio_visual_test`/
`respeaker_head_test` sind strukturell geprüft (`test_interaction_full_safe_launch.py`)
-- welche Knoten in welchem Modus starten, dass `respeaker_head_test`
ohne explizite Bestätigung abbricht, dass keiner der vier Modi jemals
`/cmd_vel` erreicht. Kein Prozess wurde tatsächlich gestartet
(`ros2 launch`), keine echte Hardware angesprochen.
