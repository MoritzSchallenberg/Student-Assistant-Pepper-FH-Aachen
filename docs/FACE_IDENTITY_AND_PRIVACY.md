# Gesichtsidentität und Datenschutz

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 3/11.
Implementierung: `ihk_pepper_identity/` (`face_identity_backend.py`,
`liveness.py`, `identity_matching.py`,
`persistent_identity_confirmer.py`, `biometric_template_store.py`).

## Zwei strikt getrennte Pfade

`FaceIdentityBackend` (ABC) trennt bewusst zwei Methoden, die NIE
denselben Code-/Datenpfad teilen:

- `observe_transient(...)` -- für Gruppengespräche (siehe
  `docs/GROUP_CONVERSATION.md`). Liefert höchstens ein anonymes,
  sitzungsgebundenes Embedding zur Wiedererkennung INNERHALB einer
  laufenden Konversation ("ist das dieselbe Person wie vor 3 Sekunden").
  Wird NICHT gespeichert, NICHT mit der persistenten Identitätsdatenbank
  abgeglichen.
- `identify_persistent(...)` -- NUR für Personen, die vorher
  ausdrücklich eingewilligt haben (`SetConsent.srv`, Auftrag 3). Erst
  nach `PersistentIdentityConfirmer`s Mehrbild-Bestätigung (mehrere
  aufeinanderfolgende Frames müssen übereinstimmen, kein
  Einzelbild-Fehlalarm) wird ein `person_id`-Treffer zurückgegeben.

Kein Pfad speichert je ein unbekanntes Gesicht automatisch als neue
Person -- neue Personen entstehen weiterhin nur über den bestehenden
`person_memory_node`-Registrierungspfad aus Auftrag 3.

## Liveness (`liveness.py`)

Tiefenvarianz-Heuristik: ein flaches Foto/ein Bildschirm hat eine
andere Tiefenverteilung im Gesichtsbereich als ein echtes Gesicht.
`check_liveness()` ist die letzte Verteidigungslinie gegen genau dieses
Spoofing -- deshalb ist Bedingung 4 in `check_authorization()`
(`docs/PERSON_ROLES_AND_AUTHORIZATION.md`) niemals optional, wenn ein
privilegierter Befehl von einer erkannten Rolle abhängt.

## Separater biometrischer Speicher

`biometric_template_store.py`: eigene, Fernet-verschlüsselte SQLite-
Datei unter `/var/lib/ihk-pepper/identity/biometric_templates.db`,
0600-Rechte (`_restrict_permissions()`), Schlüssel wird bei Bedarf neu
erzeugt (`_load_or_create_key()`). Vorlagen werden AUSSCHLIESSLICH über
`person_id` referenziert -- nie in der Identitätsdatenbank
(`identity_registry_db.py`), nie in der Gesten-/Personen-Vektordatenbank,
nie in irgendeiner LLM-Pipeline-Nachricht. `purge_expired()` erlaubt
eine Aufbewahrungsfrist statt unbegrenzten Speicherns.

## `LocalOnnxIdentityBackend`

Läuft komplett lokal (CPU-fähiges ONNX-Modell), fail-closed bei
fehlendem/leerem/ungültigem Modellpfad
(`FaceIdentityModelNotFoundError`) -- niemals ein stiller Fallback auf
"jeder ist unbekannt" ohne Fehlermeldung. `identity_matching.py`s
`match_embedding()` lehnt zusätzlich bei zu geringer Marge zwischen
bestem und zweitbestem Treffer ab (Mehrdeutigkeits-Schutz).

## Ehrlicher Stand

48 Tests, alle ohne Skip -- aber NUR der fail-closed-
Konstruktionspfad und die reinen Geometrie-/Matching-Hilfsfunktionen
sind abgedeckt. Die tatsächliche ONNX-Inferenz selbst ist NICHT
getestet (kein `onnx`-Paket zum Selbstbauen eines Testmodells in dieser
Session verfügbar, nur `onnxruntime`). **Es existiert noch KEIN
ROS2-Node, der dieses Paket instanziiert und `PersonIdentityArray`
veröffentlicht** -- `ihk_pepper_identity` ist ein fertiges, getestetes
Backend ohne Laufzeit-Anbindung (siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7 "Empfehlung"). Kein echtes
Gesicht, keine echte Kamera in dieser Session verifiziert.
