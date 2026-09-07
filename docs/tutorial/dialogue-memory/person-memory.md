# Personengedächtnis

{{ documented }}

## Was diese Seite ist

Das einwilligungsgebundene, persistente Personengedächtnis
(`ihk_pepper_person_memory`, Entwicklungsauftrag 3 AP5/AP6) --
Datenmodell, Regeln, und der real live geprüfte vollständige
Lebenszyklus.

## Der wichtigste Grundsatz zuerst

Eine `track_id` (siehe
[Personen-Engagement](../perception-interaction/person-engagement.md))
ist **niemals** eine Identität. `person_id` wird **nie** automatisch aus
einer `track_id` abgeleitet — strukturell erzwungen: `create_or_touch()`
und jede andere Methode der `IdentityRegistryStore`-Klasse besitzt gar
kein `track_id`-Argument (per `inspect.signature`-Test bestätigt, nicht
nur per Konvention).

## Zwei getrennte Konzepte

### 1. Identity Registry

SQLite-Tabelle `identities` (`person_id` PRIMARY KEY, `display_name`,
`consent_status` ∈ `{not_asked, granted, denied, withdrawn}`,
`created_at`, `last_seen_at`, `last_recognition_confidence`,
`retention_deadline`) + append-only `identity_audit_log` (jede
Schreiboperation braucht einen Pflicht-`reason`-String).
`get_context(person_id)` liefert `known=True` **nur** bei
`consent_status == GRANTED` — auch wenn ein Datensatz existiert.

### 2. Vector Memory

SQLite-Tabelle `memory_entries` (`person_id`, `session_id`, `source`,
`timestamp`, `topics`, `summary`, `sources`, `valid_until`,
`embedding_ref`). `write_validated_summary()` ruft zuerst
`validate_memory_write()` auf, schreibt **nur** bei `errors == []`.

**Verbindliche Regeln**:

- **Keine Rohbilder, keine Gesichts-Embeddings als Klartext** —
  `embedding_ref` ist ausschließlich eine kurze *Referenz*, eine
  Längenheuristik lehnt alles ab, was nach einem Inline-Datenblob statt
  einer Referenz aussieht.
- **Kein Schreiben ohne passenden, eingewilligten Identity-Datensatz**.
- **Kein Schreiben ohne Gültigkeits-/Löschregel** (`valid_until` ist
  Pflichtfeld).
- **Keine Namenszuordnung allein durch ein LLM** — `MemoryEntry` selbst
  enthält keinen `display_name`.

## Es gibt kein "Person anlegen"-Service

Bewusste Design-Entscheidung: **kein** LLM darf eine Person anlegen. Die
erste `SetConsent`-Anfrage für eine unbekannte `person_id` legt den
Datensatz implizit an — ausschließlich über diesen von einem
Menschen/`RunDialogue` ausgelösten Weg.

## Die sechs Services

```{list-table}
:header-rows: 1
:widths: 30 70

* - Service
  - Zweck
* - `lookup_person`
  - `IdentityRecord` nachschlagen.
* - `set_consent`
  - Einwilligung setzen -- legt die Person implizit an, falls unbekannt.
* - `set_display_name`
  - Anzeigenamen setzen.
* - `delete_person`
  - **Echtes** Löschen aus beiden Stores (kein Flag).
* - `get_person_context`
  - Kontext für die LLM-Pipeline (`known`, `display_name`, `person_id`).
* - `write_memory_summary`
  - Ruft `validate_memory_write()`, `success=False` + Begründung bei
    Ablehnung -- nie stiller Erfolg.
```

## Datenschutz und Einwilligung

- Speicherorte: `~/.ihk_pepper_memory/{identity,vector_memory}.db` --
  **außerhalb** jedes Git-/Colcon-Baums, konfigurierbar.
- `delete_person` löscht **echte Zeilen** aus beiden Stores, kein bloßes
  Flag.
- Kein Rohbild, kein Gesichts-Embedding im Klartext, keine rohe
  LLM-Zwischenausgabe wird je persistiert — strukturell durch das Schema
  ausgeschlossen (`summary` ist immer eine kurze, nachträglich erzeugte
  Zusammenfassung).
- `valid_until` ist Pflichtfeld für jeden Eintrag.
- Stimmungsbeobachtungen (`AffectObservation.is_reliable_fact()`) sind
  **immer** `False` — dürfen nie als Faktengrundlage in einem
  `ResponsePlan` landen.

## Real live geprüfter Lebenszyklus

Über `manual_dialogue_e2e_check.py` (kein Mock, echte Prozesse):

- **`known_person`** (Einwilligung erteilt): nach einer beantworteten
  Frage ein echter `memory_entries`-Datensatz — per `sqlite3` gegen die
  Datenbank direkt bestätigt.
- **`unknown_person`** (keine Einwilligung): danach **kein** Eintrag in
  `identities` und **keine** Zeile in `memory_entries` für diese Person
  — sowohl über den `GetPersonContext`-Service als auch per direkter
  `sqlite3`-Abfrage bestätigt.

Zusätzlich einzeln über echte `ros2 service call`-Aufrufe geprüft:
`set_consent` (neue Person, `granted`) → `set_display_name` →
`lookup_person` (bestätigt `known=true`) → `get_person_context` →
`delete_person` (`identity_geloescht=True`) → `lookup_person` erneut
(bestätigt wieder `known=false`).

## Grenzen (weiterhin gültig)

Keine Gesichtserkennung, kein Consent-UI-Flow (Einwilligung wird
aktuell nur über den ROS2-Service gesetzt, nicht über eine
Nutzeroberfläche).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Vollständiger Service-Lebenszyklus real über echte
`ros2 service call`-Aufrufe geprüft, plus 18+13+6 Unit-Tests. Keine
Pepper-Hardware nötig für dieses Thema — reine SQLite-/ROS2-Service-
Logik.

## Nächster Schritt

[Gesten und Kinematik](../gestures-kinematics/index.md).
