# Audiovisuelle Personenzuordnung

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6, Abschnitt 13.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_perception/
ihk_pepper_perception/audiovisual_association.py` (reine Logik),
`audiovisual_association_node.py` (ROS-Wrapper, `AssociatePersonWithSound`-
Service).

## Zweck

Nach der Kopfausrichtung (`OrientHeadToSound`) muss GENAU EINE Person
mit der RealSense bestätigt werden, bevor gewunken wird -- nie eine
geratene Auswahl bei Mehrdeutigkeit, keine Gesichtserkennung als
Krücke dafür (Auftrag: "Es darf keine Gesichtserkennung verwendet
werden, um eine mehrdeutige Richtungszuordnung zu 'erraten'").

## Ablauf (`associate_person_to_sound()`, reine Funktion)

1. Harte Filter je Track: gültige 3D-Position (`has_3d_position`),
   aktueller Zeitstempel (`age_s <= maximum_track_age_s`, Standard
   0.5s), ausreichende Konfidenz (`confidence >= minimum_track_confidence`,
   Standard 0.70), über mehrere Frames stabil (`stable`, kommt direkt
   aus `PersonTrack.msg::stable` -- KEINE separate "Confirm"-Prüfung
   nötig, dieses Feld bedeutet bereits "stabil über mehrere Frames"),
   nicht in einer Keepout-Zone (siehe Einschränkung unten).
2. Peilwinkel (`bearing_deg()`, REP-103-Konvention, robust gegen den
   180-Grad-Übergang) jedes verbliebenen Kandidaten berechnen.
3. Mit dem Schallstrahl vergleichen, nach Winkelfehler sortieren.
4. Kandidaten außerhalb `maximum_angular_error_deg` (Standard 20°)
   verwerfen.
5. Bleibt kein Kandidat: `valid=False`,
   `reason="keine_person_im_winkelkorridor"`.
6. Bleibt genau einer: ausgewählt.
7. Bleiben mehrere: ist der Abstand zwischen bestem und zweitbestem
   Kandidaten kleiner als `minimum_ambiguity_margin_deg` (Standard 10°),
   wird NIEMAND ausgewählt (`valid=False`, `reason="mehrdeutig"`) --
   sonst der beste Kandidat.

## Warum keine separaten `ConfirmStablePersonTrack`-/`CheckAudioDirection`-Knoten

Der im Auftrag gezeigte Beispiel-Subtree (Abschnitt 14) nennt diese
als eigene Knoten. In dieser Implementierung sind sie bewusst
zusammengefasst:

- `stable` auf `PersonTrack.msg` bedeutet bereits "stabil über mehrere
  Frames" (siehe dessen eigene Feld-Dokumentation) -- eine separate
  `ConfirmStablePersonTrack`-Prüfung wäre redundant mit dem harten
  Filter in Schritt 1.
- Die Prüfung "ist die Richtung überhaupt gültig" passiert bereits VOR
  diesem Service-Aufruf (`WaitForFreshWakeword` im Behavior Tree lässt
  nur `direction_valid=true`-Ereignisse durch) -- ein separater
  `CheckAudioDirection`-Knoten hätte nichts mehr zu prüfen.

Diese Vereinfachung ist im Sinne des Auftrags ausdrücklich erlaubt
("Ein möglicher Subtree" -- keine zwingende 1:1-Struktur).

## Ehrlicher Stand: Keepout-Zonen-Prüfung nicht verdrahtet

`TrackCandidate.in_keepout_zone` ist im reinen Funktionsvertrag
vorbereitet (die Funktion respektiert es korrekt, siehe
`test_track_in_keepout_zone_is_excluded`), aber
`audiovisual_association_node.py` setzt es aktuell immer auf `False`.
Eine echte Prüfung bräuchte eine Transformation der Track-Position
(je nach `source_camera` in einem kamera-/basisnahen Frame) nach `map`
(wo die Keepout-Zonen aus `ihk_pepper_navigation/zone_config.py`
definiert sind) -- diese Transformation existiert in diesem Node noch
nicht. Dokumentierte Vereinfachung, kein verschwiegener Bug.

## Getestet

`test_audiovisual_association.py` (13, inkl. 180-Grad-Wraparound-Test,
alle Ausschlussgründe einzeln), `test_audiovisual_association_node.py`
(6). Kein Test gegen echte RealSense-Hardware -- siehe
`docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`, Phase B.
