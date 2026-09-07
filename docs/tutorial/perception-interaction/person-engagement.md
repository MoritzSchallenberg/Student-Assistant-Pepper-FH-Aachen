# Personen-Engagement

{{ documented }}

## Was diese Seite ist

Die beiden ROS-freien, real getesteten Kernmodule von
`ihk_pepper_perception`: der Interessens-Score
(`interest_scoring.py`) und die zeitlich robuste Winkgesten-Erkennung
(`wave_detector.py`).

## Personen-Tracking: was eine `track_id` ist -- und was nicht

`ihk_pepper_perception` liefert einen `PersonTrackArray` (siehe
[ROS 2](../ros2/package-layout.md)) mit einer `track_id` pro erkannter
Person (ByteTrack). **Wichtig, durchgängig im ganzen Projekt gültig**:
eine `track_id` ist **keine Personenidentität** — sie gilt nur, solange
die Person durchgängig im Kamerabild sichtbar bleibt, und wird bei jedem
neuen Erscheinen neu vergeben. Der Weg von `track_id` zu echter,
dauerhafter Identität führt ausschließlich über
[Dialog und Gedächtnis](../dialogue-memory/index.md)s Identity Registry
— nie automatisch.

## Interessens-Score (`interest_scoring.py`)

Eine reine Funktion `score(history, weights) -> float in [0, 1]`, die
mehrere Signale gewichtet:

```{list-table}
:header-rows: 1
:widths: 40 15 45

* - Signal
  - Gewicht
  - Bedeutung
* - Blickt Richtung Kamera (Bildmitte)
  - +0.20
  - Bounding-Box nahe Bildmitte
* - Stabil über mehrere Frames
  - +0.15
  - `frame_count > 1`
* - Nähert sich langsam
  - +0.20
  - radiale Geschwindigkeit < 0,6 m/s, Richtung Pepper
* - Steht direkt davor
  - +0.15
  - fast keine radiale Bewegung, Distanz < 2 m
* - Winkt / Arm erhoben
  - +0.20
  - `last_wrist_above_shoulder`
* - Guter Abstand (1,0-2,5 m)
  - +0.10
  - innerhalb `GOOD_DISTANCE_RANGE_M`
* - Läuft schnell vorbei
  - −0.30
  - laterale Geschwindigkeit ≥ 0,8 m/s
* - Entfernt sich schnell
  - −0.25
  - radiale Geschwindigkeit ≥ 0,5 m/s, weg von Pepper
* - Zu weit weg
  - −0.20
  - außerhalb des guten Abstandsbereichs
* - Nur ein einzelnes Bild
  - −0.50
  - `frame_count <= 1`
* - Ungültige Tiefe
  - −0.10
  - `has_valid_depth == False`
* - Veraltete Daten
  - −0.50
  - `time_since_seen_s > 1.0s`
* - In Sperrzone
  - **−1.00 (harter Ausschluss)**
  - `in_keepout_zone` -- Score wird sofort 0, unabhängig von allen
    anderen Signalen
```

Das Ergebnis wird auf `[0, 1]` geklemmt. `SelectStablePerson` im
Verhaltensbaum verlangt `min_interest_score=0.5` — siehe
[Interaktions-Verhaltensbaum](../decision-making/interaction-behavior-tree.md).

**Ehrlichkeitshinweis, direkt aus dem Modul-Docstring übernommen**:
"Blickt Richtung Kamera" wird nur **näherungsweise** aus der 2D-
Bounding-Box-Position abgeleitet, nicht aus echter Blickrichtungs-/
Kopfpose-Schätzung — das wäre ein eigenes Forschungsthema.

## Winkgesten-Erkennung (`wave_detector.py`)

Ein Zustandsautomat **pro (`track_id`, Seite)**:

```text
IDLE
  -> ARM_RAISED       (Handgelenk deutlich über Schulter, konfidenzstark)
  -> WAVE_CANDIDATE    (mindestens 1 echter Richtungswechsel)
  -> WAVE_CONFIRMED    (>= 2 Richtungswechsel, >= 4 gültige Frames,
                         >= 0.6s Dauer)
  -> COOLDOWN           (3.0s, verhindert Mehrfachauslösung)
```

Ein **einzelnes** Bild mit erhobener Hand kann **nie** `WAVE_CONFIRMED`
erreichen — das verlangt zusätzlich echte, ausreichend große
Richtungswechsel über eine Mindestdauer.

**Körpergrößen-unabhängige Schwellen**: "erhoben" und "ausreichende
Auslenkung" werden nicht in absoluten Pixeln gemessen, sondern relativ
zur Schulter-Ellenbogen-Länge (`bone_len`) — dieselbe Formel funktioniert
für eine nahe wie eine entfernte Person.

```{list-table}
:header-rows: 1
:widths: 45 55

* - Parameter
  - Default
* - `min_keypoint_confidence`
  - 0.3
* - `raise_margin_bone_frac`
  - 0.15 × Bone-Länge über Schulterhöhe
* - `min_swing_amplitude_bone_frac`
  - 0.25 × Bone-Länge
* - `min_direction_changes`
  - 2
* - `min_duration_s`
  - 0.6 s
* - `min_valid_frames`
  - 4
* - `max_gap_s`
  - 0.5 s (größere Lücke verwirft die laufende Sequenz)
* - `cooldown_s`
  - 3.0 s
```

Ein bestätigtes Ereignis (`WaveEvent`, `stable=True`) entspricht
`ihk_pepper_interfaces/msg/WaveGestureEvent` mit `gesture_name` bereits
passend zum Gestenkatalog-Namen (`wave_right`/`wave_left`) — siehe
[Gesten und Kinematik](../gestures-kinematics/index.md).
`reset_track()` **muss** aufgerufen werden, sobald ByteTrack eine
`track_id` als verloren meldet, sonst zählt eine spätere Wiederverwendung
derselben Nummer fälschlich als Fortsetzung einer alten Sequenz.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Beide Module sind reine Python-Funktionen mit
eigener Unit-Testsuite, unabhängig von Kamera-/Pepper-Hardware.
{{ hwverificationrequired }} für die tatsächliche Erkennungsgüte gegen
eine echte Kamera.

## Nächster Schritt

[Entscheidungsfindung](../decision-making/index.md).
