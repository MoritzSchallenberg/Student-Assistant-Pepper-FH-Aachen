# Face-Track Association (AP7.1)

`ihk_pepper_identity/face_track_association.py` -- ordnet erkannte
Gesichter (`FaceDetection`, siehe `IDENTITY_RUNTIME.md`) den bereits vom
Perception-Stack getrackten Personen (`PersonTrack`) zu. Reine Logik,
KEIN ROS, unabhängig testbar (`test_face_track_association.py`, 15
Tests).

## Algorithmus (`match_faces_to_tracks`)

Global-greedy statt "erster Treffer gewinnt":

1. Alle Face-Track-Kandidatenpaare werden nach IoU (Intersection over
   Union der Bounding-Boxes) absteigend sortiert.
2. Paare werden in dieser Reihenfolge zugewiesen -- das global beste
   Paar zuerst.
3. Ein Track wird komplett ausgeschlossen, wenn seine beste und
   zweitbeste IoU-Kandidatur zu nah beieinanderliegen
   (`ambiguity_margin`, Standard 0.1) -- eine mehrdeutige Zuordnung wird
   NIE geraten.
4. Ein Gesicht kann nie zwei Tracks gleichzeitig zugeordnet werden
   (`used_face_ids`-Tracking).
5. Ein Minimum-IoU-Schwellwert (`minimum_iou`, Standard 0.3) verhindert
   Zuordnungen ohne echte räumliche Überlappung.

Weitere Bausteine:

- `bbox_iou()`/`bbox_center_distance()`: reine Geometriefunktionen.
- `is_depth_plausible()`: prüft, ob ein Tiefenwert an der
  Gesichtsposition aktuell und plausibel ist (Alter,
  Mindest-/Maximalabstand) -- verwirft sonst die Zuordnung, statt einen
  geschätzten Tiefenwert zu verwenden.

## Auftragsvorgaben abgedeckt

Bbox-Containment/IoU, Mittelpunktabstand, Tiefenkonsistenz,
zeitliche Track-Stabilität (über `identity_frame_processor.py`s
Mehrfach-Frame-Bestätigung, nicht in diesem Modul selbst) und
eindeutiger bester Treffer sind damit erfüllt. Ein Gesicht wird
NIEMALS mehreren Tracks gleichzeitig zugewiesen (strukturell durch
`used_face_ids` garantiert, per Test bestätigt).

## Verwandte Dokumente

`IDENTITY_RUNTIME.md` (Gesamtpipeline), `docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md`
(analoges Verfahren für Schallrichtung statt Bildposition).
