# Architektur: Drei-LLM-Pipeline (Verträge + Laufzeit)

Stand: 2026-09-04. Ursprünglich Entwicklungsauftrag 1, Abschnitt 8 (reine
Verträge/Schemas, `ros2/autonomy_ws/src/ihk_pepper_llm_contracts/`).
**Seit Entwicklungsauftrag 3 (AP2-AP11) existiert die vollständige
Laufzeit** -- echte LLM-Provider, ein deterministischer Retriever, ein
TTS-/Gesten-Executor und ein echter `RunDialogue`-Action-Server. Dieses
Dokument beschreibt weiterhin primär die Verträge; die Laufzeit-Details
stehen in `docs/LLM_RUNTIME_ARCHITECTURE.md` und
`docs/LLM_PROVIDER_CONFIGURATION.md`.

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
              ResponsePlanExecutor (ihk_pepper_dialog, seit AP10) --
              synchronisiert TTS-/PlayGesture-Actions über die bereits
              vorhandenen, geprüften Actions (Say.action, PlayGesture.action)
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

`ihk_pepper_dialog/response_plan_executor.py::ResponsePlanExecutor` (seit
AP10) nimmt nur valide Pläne entgegen und synchronisiert TTS-/
`PlayGesture`-Actions entsprechend `gesture_relation` -- siehe
`docs/RESPONSE_PLAN_EXECUTION.md` für Details.

## Seit Entwicklungsauftrag 3 ergänzt (AP2-AP11)

- **Echte LLM-Provider** (`providers.py`): `MockLLMProvider`,
  `AnythingLLMProvider`, `OpenAICompatibleProvider`,
  `OfflineFallbackProvider`, je Stufe unabhängig konfigurierbar (siehe
  `docs/LLM_PROVIDER_CONFIGURATION.md`).
- **Deterministischer Retriever** (`retriever.py`): exakte FAQ →
  semantische FAQ → freigegebenes Personengedächtnis → RAG → sichere
  "keine Information"-Fallback, siehe `docs/PERSON_MEMORY_RUNTIME.md` für
  den Personengedächtnis-Teil.
- **Echter Action-Server** (`ihk_pepper_dialog/run_dialogue_action_server.py`)
  + BT-Knoten `RunDialogueViaBT` -- siehe
  `docs/LLM_RUNTIME_ARCHITECTURE.md` für den vollständigen Ablauf.
- `KnowledgePlanResponse` um `normalized_intent`/`use_person_memory`,
  `ResponseSegment` um Pflichtfeld `segment_id` und
  `estimated_duration_s()` erweitert (rückwärtskompatibel, siehe
  Commit-Historie von Entwicklungsauftrag 3 AP3/AP9).

## Gesten-Vektordatenbank in die Pipeline verdrahtet (Entwicklungsauftrag 04-B, AP5A)

`GesturePlanRequest` bekam ein neues Feld `gesture_options:
list[GestureOption]` (Name/Beschreibung/Dauer/Ähnlichkeit/erlaubte
Zustände -- niemals Gelenke/Winkel/Zeitachsen). Drei getrennte Mengen
regeln die Gestenauswahl (siehe `docs/LLM_RUNTIME_ARCHITECTURE.md` für
den vollständigen Datenfluss):

```
database_candidates    -- Ergebnis von /search_gestures (harte Filter
                           bereits angewendet, siehe
                           docs/PERSON_MEMORY_RUNTIME.md o.ä.
                           gesture_search.py)
llm2_selected_gestures  -- NUR was LLM 2 tatsächlich ausgewählt hat
                           (validiert gegen database_candidates)
final_execution_allowlist -- Schnittmenge aus llm2_selected_gestures und
                           dem, was der ResponsePlanValidator tatsächlich
                           durchgelassen hat
```

`run_response_composer()` bekommt **`llm2_selected_gestures`** als
`allowed_gesture_names` -- NICHT die volle `database_candidates`-Menge.
Das ist der entscheidende Unterschied zu einer naiven Verdrahtung: ohne
diese Trennung könnte LLM 3 einen von LLM 2 nie erwähnten
Datenbank-Kandidaten nachträglich verwenden. `system_only`/
`selectable_by_llm=false`-Gesten (z.B. `acknowledge_nod_small`,
`thinking_loop_subtle`, `look_at_person`, `neutral_stand`, `t_pose` --
vollständige, generierte Liste in
`docs/GESTURE_CATALOG_INVENTORY.md`) werden LLM 2 strukturell nie
angeboten (`include_system_only=false` in jeder LLM-Suchanfrage,
zusätzlich clientseitig defensiv nochmal gefiltert).

Seit Entwicklungsauftrag 04-B, AP8 (11/14) sind `system_only`/
`selectable_by_llm`/`semantic_tags` erstklassige, validierte
`Gesture`-Attribute (siehe `docs/GESTURE_AUTHORING.md`) -- `semantic_tags`
fließen zusätzlich zu Name/Beschreibung in den Suchtext von
`GestureIndexStore.reindex()` ein, technische Testhistorien/Keyframes/
`test_note` bewusst NICHT (die würden die semantische Auswahl
verzerren, nicht verbessern).

## Grenzen (weiterhin gültig)

- Die Quellenpflicht-Heuristik (`FACT_CLAIM_MARKERS`) ist bewusst grob
  (keine echte NLP-Faktenerkennung) -- ein zusätzliches Sicherheitsnetz,
  kein Ersatz für eine echte Quellenpflicht-Prüfung im Retriever selbst.
- Kein LLM darf `SetMotionPermission` aufrufen, rohe ROS2-/qicli-/SSH-/
  Shell-Befehle erzeugen oder Gelenknamen/-winkel festlegen -- weiterhin
  strukturell (nicht nur durch Prompts) erzwungen.
