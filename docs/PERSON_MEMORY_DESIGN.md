# Architektur: Personen-/Gesprächsgedächtnis (Verträge)

Stand: 2026-09-03. Teil von Entwicklungsauftrag 1, Abschnitt 9. **Nur
Datenmodell + Regelvalidierung** (`ros2/autonomy_ws/src/ihk_pepper_person_memory/`)
-- keine echte Gesichtsdatenbank, kein echter Speicher, keine
Gesichtserkennung in diesem Auftrag.

## Aktueller Stand vs. dieser Vertrag (ehrlich)

Der vorhandene Code hat **Stimmungsabfragen** (`apps/web/pepper/qicli.py::get_mood`,
`get_robot_mood`), liefert aber **keine verlässliche dauerhafte
Gesichts-/Namensidentität** über die bestehende SSH/qicli-Brücke. Eine
ByteTrack-`track_id` aus `ihk_pepper_perception` (siehe
`ihk_pepper_interfaces/msg/PersonTrack.msg`) ist **keine Identität** --
sie gilt nur, solange die Person durchgängig im Kamerabild sichtbar
bleibt, und wird bei jedem neuen Erscheinen neu vergeben. Dieser Auftrag
baut absichtlich noch keine Brücke von Track-ID zu echter Person.

## Zwei getrennte Konzepte

### 1. Identity Registry (`identity_registry.py`)

`IdentityRecord`: `person_id` (interne, stabile ID -- **niemals** eine
rohe `track_id`), `display_name`, `consent_status`
(`not_asked`/`granted`/`denied`/`withdrawn`), `last_seen_iso`,
`retention_deadline_iso`, `confidence`.

`IdentityLookupResult.known` ist standardmäßig `False` -- der sichere
Default. Er wird **niemals** durch ein LLM gesetzt und **niemals**
allein aus einer aktuellen `track_id` abgeleitet, sondern ausschließlich
durch einen (späteren) Identity-Service mit eigener Konfidenz und
Aktualitätsangabe (`as_of_iso`).

`is_storage_allowed(record)` / `effective_session_key(record, fallback)`:
personenbezogene Speicherung ausschließlich mit `consent_status ==
GRANTED`. Ohne Freigabe bleibt **nur eine flüchtige Session-ID** übrig
-- nie die dauerhafte `person_id`.

### 2. Vector Memory (`vector_memory.py`)

`MemoryEntry`: `person_id`, `source`, `timestamp_iso`, `topics`,
`text_summary`, `embedding_ref`, `valid_until_iso`.

Verbindliche Regeln, durchgesetzt in `validate_memory_write()`:

- **Keine Rohbilder, keine Gesichts-Embeddings als Klartext**:
  `embedding_ref` ist ausschließlich eine kurze *Referenz* in eine
  separate, getrennt zugriffsgeschützte Ablage -- eine grobe
  Längenheuristik (`MAX_EMBEDDING_REF_CHARS`) lehnt alles ab, was nach
  einem Inline-Datenblob statt einer Referenz aussieht.
- **Kein Schreiben ohne passenden, eingewilligten `IdentityRecord`**
  (`consent_status == GRANTED`).
- **Kein Schreiben ohne Gültigkeits-/Löschregel** (`valid_until_iso`
  ist Pflicht).
- **Keine Namenszuordnung allein durch ein LLM** -- `MemoryEntry` selbst
  enthält keinen `display_name`, der kommt ausschließlich aus dem
  `IdentityRecord` der Identity Registry.

## Emotion/Stimmung als Beobachtungssignal (`mood_signal.py`)

`MoodObservation` (`label`, `confidence`, `observed_at_iso`,
optional `person_id`) hat `is_usable_as_fact()`, das **immer** `False`
zurückgibt -- macht explizit im Typsystem, was sonst nur eine
Konvention wäre: eine Stimmungsbeobachtung ist nie eine Tatsache und darf
z.B. nie als `source_id`/Faktengrundlage in einem `ResponsePlan`
(`ihk_pepper_llm_contracts`) landen.

## LLM-Bezug

`LLM 1` (Knowledge Planner) darf gemäß `docs/LLM_PIPELINE_DESIGN.md`
höchstens einen `memory_summary_candidate`-**Vorschlag** in einem
`ResponsePlan` platzieren (freier Text). Ob daraus tatsächlich ein
`MemoryEntry` wird, entscheidet ausschließlich ein späterer,
deterministischer Dienst über `validate_memory_write()` -- niemals das
LLM selbst und niemals automatisch.

## Grenzen dieser Runde

- Keine echte Datenbank, kein echter Identity-Service, keine
  Gesichtserkennung, kein Consent-UI-Flow -- nur die Vertragsschicht +
  Tests (`ihk_pepper_tests/test/test_person_memory.py`).
