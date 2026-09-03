# Architektur: Drei-LLM-Pipeline (Verträge)

Stand: 2026-09-03. Teil von Entwicklungsauftrag 1, Abschnitt 8. **Dieses
Dokument beschreibt nur Verträge/Schemas** (`ros2/autonomy_ws/src/ihk_pepper_llm_contracts/`)
-- es gibt in diesem Auftrag keine LLM-Aufrufe, keinen Retriever, keinen
Executor. Alles hier ist reine Datentyp-/Validierungsschicht.

## Warum drei Stufen statt einem großen LLM-Aufruf

Ein einzelnes LLM, das direkt Text+Gesten+ROS-Aktionen ausgibt, kann
prinzipbedingt nicht zuverlässig zwischen "das sage ich" und "das führe
ich aus" trennen. Die Architektur erzwingt diese Trennung strukturell:

```
Nutzerfrage ─▶ LLM 1 (Knowledge Planner)
                 │  Ausgabe: NUR Suchanfragen + Unsicherheiten
                 ▼
              deterministischer Retriever (kein LLM, sucht wirklich)
                 │  Ergebnis: bestätigte Quellen
                 ▼
              LLM 2 (Gesture Planner)
                 │  Ausgabe: NUR Gestennamen aus einer Allowlist
                 ▼
              LLM 3 (Response Composer)
                 │  Ausgabe: ResponsePlan (Text + Gestennamen, strukturiert)
                 ▼
              ResponsePlanValidator (deterministisch, siehe unten)
                 │  nur wenn valide:
                 ▼
              (späterer Auftrag) ResponsePlanExecutor -- synchronisiert
              TTS-/PlayGesture-Actions über die BEREITS VORHANDENEN,
              geprüften Actions (ihk_pepper_interfaces/action/Say.action,
              PlayGesture.action)
```

**Kein LLM in dieser Kette darf**: `SetMotionPermission` aufrufen, rohe
ROS2-/qicli-/SSH-/Shell-Befehle erzeugen, Gelenknamen oder -winkel
festlegen. Das wird nicht durch gute Prompts sichergestellt, sondern
durch die Vertragsschicht: Stufe 2/3 können Gesten überhaupt nur über
einen **Namen aus einer zur Laufzeit übergebenen Allowlist** referenzieren
(`ihk_pepper_bridge`'s `GestureCatalog`-Namen), nie über Gelenkdaten --
diese Felder existieren im Schema schlicht nicht.

## Stufe 1: Knowledge Planner (`knowledge_planner.py`)

- **Eingaben** (`KnowledgePlanRequest`): normalisierte Nutzerfrage,
  freigegebener `PersonContext` (kommt aus `ihk_pepper_person_memory`,
  niemals vom LLM erfunden), Gesprächsverlauf der aktuellen Session, Modus.
- **Ausgabe** (`KnowledgePlanResponse`): `search_queries`,
  `required_data_kinds`, `uncertainties`, `assumes_known_identity`
  (muss `False` sein -- `validate()` erzwingt das).
- Ein **deterministischer Retriever** (nicht Teil dieses Auftrags) führt
  die eigentliche FAQ-/RAG-/Vektorsuche aus. LLM 1 sieht nie direkt die
  Datenbank, schreibt nie direkt hinein.

## Stufe 2: Gesture Planner (`gesture_planner.py`)

- **Eingaben** (`GesturePlanRequest`): Antwort-Brief aus Stufe 1 +
  gefundene Quellen, aktuelle Robotersituation, `allowed_gesture_names`
  (von außen befüllte Allowlist, z.B. aus `GestureCatalog.reload()`).
- **Ausgabe** (`GesturePlanResponse`): Liste von `GestureSuggestion`
  (`gesture_name`, `relation` ∈ `{before_segment, with_segment_start,
  after_segment}`). `validate(allowed_gesture_names)` lehnt jeden Namen
  ab, der nicht in der übergebenen Allowlist steht, und jede unbekannte
  `relation`. Es gibt in diesem Schema **kein Feld** für Gelenke,
  Winkel, Geschwindigkeiten oder ROS-Befehle -- das ist kein
  Validierungs-, sondern ein Struktur-Ausschluss.

## Stufe 3: Response Composer (`response_plan.py`)

`ResponsePlan` = `{schema_version, segments: [{text, gesture_name,
gesture_relation}], source_ids, memory_summary_candidate}` -- exakt das
Format aus dem Entwicklungsauftrag.

`ResponsePlanValidator.validate(plan, context)` ist deterministisch,
ruft kein LLM, hat keine Seiteneffekte, und prüft (siehe Tests in
`ihk_pepper_tests/test/test_llm_contracts.py`):

1. **Safety**: `context.safety_ok` muss `True` sein, sonst wird jeder
   Plan abgelehnt, unabhängig vom Inhalt.
2. **Segmentanzahl/-länge**: max. `MAX_SEGMENTS_PER_PLAN` (6), Text
   zwischen 1 und `MAX_SEGMENT_TEXT_CHARS` (400, angelehnt an
   `ihk_pepper_dialog`s `max_speech_chars`).
3. **Rohe Anweisungen im Text**: eine feste Liste verdächtiger
   Teilstrings (`ros2 `, `ssh `, `qicli `, `sudo `, `` ` ``, `$(`,
   `SetMotionPermission`, ...) wird abgelehnt -- kein Ausführungs-
   Sandbox-Ersatz, sondern ein zusätzliches Sicherheitsnetz gegen
   versehentlich/böswillig durchgereichten Text.
4. **Gestennamen**: nur aus `context.allowed_gesture_names`, zusätzlich
   optional pro Geste eingeschränkt auf bestimmte
   `current_interaction_state`-Werte (`allowed_interaction_states_for_gestures`).
5. **Gültige `gesture_relation`**.
6. **Quellenpflicht**: eine grobe Heuristik (`FACT_CLAIM_MARKERS`, z.B.
   "laut", "unsere Ausbildung", "kostet") verlangt bei Faktenanspruch
   mindestens eine `source_id`.
7. **Erfundene Quellen**: jede `source_id` muss in
   `context.known_source_ids` (tatsächlich vom Retriever gefunden)
   auftauchen.

Ein **späterer** `ResponsePlanExecutor` (nicht Teil dieses Auftrags)
würde nur valide Pläne entgegennehmen und TTS-/`PlayGesture`-Actions
entsprechend `gesture_relation` synchronisieren.

## Grenzen dieser Runde

- Kein LLM wird aufgerufen, kein Retriever existiert, kein Executor
  existiert -- nur die Vertragsschicht + Tests.
- Die Quellenpflicht-Heuristik (`FACT_CLAIM_MARKERS`) ist bewusst grob
  (keine echte NLP-Faktenerkennung) -- ein zusätzliches Sicherheitsnetz,
  kein Ersatz für eine echte Quellenpflicht-Prüfung im Retriever selbst.
