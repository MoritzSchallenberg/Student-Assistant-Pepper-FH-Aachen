# Personengedächtnis -- Laufzeit (SQLite + Services)

Stand: 2026-09-04. Entwicklungsauftrag 3, AP5/AP6.
Implementierung: `ihk_pepper_person_memory/{identity_registry_db,
vector_memory_db,embedding_backend,affect_observation,person_memory_node}.py`.
Siehe `docs/PERSON_MEMORY_DESIGN.md` für die zugrundeliegenden Verträge/
Validierungsregeln (`identity_registry.py`, `vector_memory.py`).

## Speicherorte

`~/.ihk_pepper_memory/identity.db`, `~/.ihk_pepper_memory/vector_memory.db`
-- außerhalb jedes Git-/Colcon-Baums (gleiches Prinzip wie
`~/.ihk_pepper_maps/` aus Entwicklungsauftrag 2), Pfad über Node-Parameter
konfigurierbar.

## `IdentityRegistryStore`

SQLite-Tabelle `identities` (`person_id` PK, `display_name`,
`consent_status`, `created_at`, `last_seen_at`,
`last_recognition_confidence`, `retention_deadline`) + append-only
`identity_audit_log`. `person_id` wird **nie** aus einer `track_id`
abgeleitet -- kein Parameter dieser Klasse heißt `track_id` (per
`inspect.signature`-Test in `test_identity_registry_db.py` abgesichert).
`get_context(person_id)` liefert `known=True` nur bei
`consent_status == GRANTED`.

## `VectorMemoryStore`

SQLite-Tabelle `memory_entries` (`person_id`, `session_id`, `source`,
`timestamp`, `topics`, `summary`, `sources`, `valid_until`,
`embedding_ref`, `embedding`, `consent_status_at_write`).
`write_validated_summary(entry, identity)` ruft zuerst die bestehende
`validate_memory_write()`-Vertragsprüfung auf, schreibt nur bei
`errors == []`. `query_by_topic`/`query_semantic` sind strikt auf
`person_id` skaliert -- abgelaufene Einträge (`valid_until` überschritten)
ausgeschlossen, nie Ergebnisse einer FREMDEN `person_id`.

`embedding_backend.py` ist eine bewusste, eigenständige Kopie von
`ihk_pepper_dialog/faq_cache.py`s `EmbeddingBackend`/
`SentenceTransformerBackend`/`DifflibFallbackBackend`/
`create_embedding_backend()`-Muster -- NICHT importiert, um eine
zirkuläre Paketabhängigkeit (`ihk_pepper_dialog` ↔
`ihk_pepper_person_memory`) zu vermeiden.

## `person_memory_node.py` -- sechs Services

| Service | Zweck |
|---|---|
| `lookup_person` | `IdentityRecord` nachschlagen |
| `set_consent` | Einwilligung setzen -- legt die Person implizit an (`create_or_touch`), falls noch unbekannt (es gibt bewusst KEIN separates "Person anlegen"-Service -- kein LLM darf eine Person anlegen) |
| `set_display_name` | Anzeigenamen setzen |
| `delete_person` | echtes Löschen aus BEIDEN Stores |
| `get_person_context` | Kontext für die LLM-Pipeline (`known`, `display_name`, `person_id`) |
| `write_memory_summary` | ruft `VectorMemoryStore.write_validated_summary()`, `success=False` + Begründung bei Ablehnung, nie stiller Erfolg |

## Live-E2E-Nachweis (dieser Session)

Über `manual_dialogue_e2e_check.py` (siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md`, AP11):
- `known_person` (Consent erteilt): nach einer beantworteten Frage ein
  echter `memory_entries`-Eintrag, per `sqlite3` gegengeprüft.
- `unknown_person` (kein Consent): `identities`-Tabelle enthält danach
  weiterhin nur den bekannten Eintrag, KEINE Zeile für die unbekannte
  Person, KEINE `memory_entries`-Zeile -- per `sqlite3` UND über
  `GetPersonContext` gegengeprüft.

## Datenschutz/Löschung

- `delete_person` löscht echte Zeilen (kein bloßes Flag) aus beiden
  Stores.
- Kein Rohbild, kein Gesichts-Embedding als Klartext, keine rohe
  LLM-Zwischenausgabe wird je persistiert -- strukturell durch das
  Schema erzwungen (`summary` ist immer eine kurze, nachträglich erzeugte
  Zusammenfassung).
- `valid_until` (Löschfrist) ist Pflichtfeld, durchgesetzt in
  `validate_memory_write()`.

## Grenzen

Keine Gesichtserkennung, kein Consent-UI-Flow (Consent wird aktuell nur
über den Service, nicht über eine Nutzeroberfläche gesetzt) -- beides
nicht Teil dieses Auftrags.
