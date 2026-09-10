# Identity Runtime (AP7.1)

Beschreibt die Laufzeit-Architektur der Gesichtszuordnung, die AP7.1
erstmals tatsächlich verdrahtet hat (vorher: reine Bibliothek ohne
ausführbaren Node, siehe `DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7.1
Commit 1/10). Ergänzt `docs/FACE_IDENTITY_AND_PRIVACY.md` (AP7,
Datenschutzkonzept) um den tatsächlichen Node/die Pipeline.

## Node

`ihk_pepper_identity/face_identity_node.py` (Console-Script
`face_identity_node`, registriert in `setup.py`+`setup.cfg`).

Eingänge (Parameter `image_topic`/`depth_topic`/`camera_info_topic`,
Standard `/camera/front/...`): RealSense-Farbbild, Tiefenbild,
CameraInfo -- über `message_filters.ApproximateTimeSynchronizer`
(`sync_slop_s`, Standard 0.05s) synchronisiert, NIE unabgestimmt
kombiniert. Zusätzlich `/perception_node/person_tracks`
(`PersonTrackArray`, eigenständig gecacht, Alter über
`person_tracks_max_age_s` begrenzt).

Ausgänge: `/identity/person_identities` (bestehendes
`PersonIdentityArray`, wiederverwendet statt neu erfunden) und
`/identity/status` (Diagnose). **Niemals** Rohbilder/Gesichtsausschnitte/
Embeddings auf einem dieser Topics -- geprüft per
`test_face_identity_node.py`.

## Face-Detector- vs. Identity-Backend

Zwei getrennte Abstraktionen (bewusst nicht vermischt):

- `face_detector_backend.py`: findet Gesichts-Bounding-Boxes in einem
  Bild. `FaceDetectorBackend`-ABC mit `detect(image, timestamp) ->
  list[FaceDetection]`. Implementierungen: `DisabledFaceDetector`
  (Standard, liefert immer `[]`), `MockFaceDetector` (deterministisch,
  für Tests/`identity_offline_test`), `LocalOnnxFaceDetector` (echtes
  ONNX-Modell, CPU-fähig, fail-closed bei fehlendem/defektem Modell --
  **kein automatischer Modell-Download**, Pfad konfigurierbar über
  `face_detector_model_path`).
- `face_identity_backend.py` (bereits aus AP7): wertet BEREITS bekannte
  Bounding-Boxes gegen gespeicherte Templates aus -- ist selbst KEIN
  Gesichtsdetektor. `face_identity_node.py` ruft `detect()` zuerst,
  füttert die gefundenen Boxen dann in
  `PersistentIdentityConfirmer`/`identify_persistent()`.

`FaceDetection` (Dataclass) trägt `bbox_x/y/width/height`, `confidence`,
`measured_at_s`, `backend_name`, optional `landmarks`, `quality_score`,
`face_centering_score`. **Kein Feld heißt "gaze"/"Blickrichtung"** --
eine reine Bildzentrierungs-Kennzahl wird nie als echte Blickrichtung
ausgegeben (erzwungen durch
`test_face_detection_has_no_gaze_field_only_centering_score`). Echte
Blickrichtung dürfte nur aus einem eigenen, validierten Modell/
geometrischen Verfahren stammen -- **existiert in dieser Sitzung
nicht**, wird nirgends behauptet.

## Verarbeitungsschritte (`identity_frame_processor.py::process_frame`)

Zehnstufig, in dieser Reihenfolge:

1. Aktuelle Person-Tracks auswählen.
2. Gesichter im Frame erkennen (`FaceDetectorBackend.detect()`).
3. Gesichter räumlich Tracks zuordnen (`face_track_association.py`,
   siehe `FACE_TRACK_ASSOCIATION.md`).
4. Mehrdeutige Zuordnungen verwerfen (Ambiguity-Margin).
5. Tiefenwerte auf Aktualität/Plausibilität prüfen
   (`is_depth_plausible()`).
6. Liveness über mehrere Beobachtungen bewerten.
7. Identität erst über mehrere Frames hinweg bestätigen
   (`PersistentIdentityConfirmer`).
8. Dauerhafte Zuordnung nur mit gültiger Einwilligung zulassen (Consent
   wird UNMITTELBAR vor jeder Verwendung geprüft, nie zwischengespeichert).
9. Ergebnis mit Ablaufzeit veröffentlichen (`result_validity_s`).
10. Bei veralteten Daten auf UNKNOWN zurückfallen.

`PersonIdentityFrameResult` hat bewusst **kein `role`-Feld** -- Identität
und Rolle bleiben strukturell getrennt (siehe unten).

## Identität ≠ Rolle

`face_identity_node.py` setzt `identity.role` unconditional auf einen
Platzhalter (`_PLACEHOLDER_ROLE = "student"`, `role_verified=False`) --
dieses Feld wird von keinem Konsumenten mehr gelesen.
`command_router_node.py::_lookup_identity()` ruft ausschließlich
`role_resolution.py::resolve_role()`, das die echte Rolle über den
`GetEffectiveRole`-Service von `person_memory_node.py` holt (siehe
`docs/PERSON_ROLES_AND_AUTHORIZATION.md` für die vollständige
Rollentabelle). Ein Test (`test_identity_role_field_is_ignored_registry_role_wins`)
beweist das explizit: eine Nachricht mit `role="admin"` wird von der
Registry-Antwort überschrieben.

## ONNX-Inferenz -- ehrlicher Stand

`LocalOnnxFaceDetector`/`LocalOnnxIdentityBackend`: Konstruktion
(fehlendes Modell → fail-closed, kein Absturz) ist getestet. **Echte
Inferenz gegen ein reales ONNX-Modell wurde in dieser Sitzung NICHT
durchgeführt** (kein Modell, keine echte RealSense verfügbar) --
`hwverificationrequired`. `identity_offline_test`/
`authorization_tablet_test` (siehe `DEVELOPMENT_MODES.md`) verwenden
stattdessen `MockFaceDetector`/den Mock-Identity-Backend.

## Produktionsfreigaben (AP7.1.12)

`ihk_pepper_identity/production_readiness.py::check_identity_production_gates()`
prüft sieben Bedingungen (lokales Modell + Prüfsumme, Vorlagenspeicher
entschlüsselbar, Registry erreichbar, Kamerakalibrierung, Liveness
konfiguriert, Hardwarefreigabe) -- in `mode=production` erzwingt
`interaction_full_safe.launch.py::_launch_identity_node()` bei
fehlendem Gate `face_detector_kind`/`identity_backend_kind = "disabled"`
(identity bleibt UNKNOWN, role bleibt STUDENT). Einwilligung ist bewusst
NICHT Teil dieser statischen Gates -- sie ist personenbezogen und wird
laufzeit-dynamisch geprüft (siehe oben).

## Verwandte Dokumente

`FACE_TRACK_ASSOCIATION.md`, `BIOMETRIC_ENROLLMENT_AND_DELETION.md`,
`docs/FACE_IDENTITY_AND_PRIVACY.md` (AP7), `docs/PERSON_ROLES_AND_AUTHORIZATION.md`.
