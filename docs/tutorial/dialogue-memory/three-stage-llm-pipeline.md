# Drei-Stufen-LLM-Pipeline

{{ documented }}

## Was diese Seite ist

Die vollständige, real implementierte Dialog-Pipeline aus
Entwicklungsauftrag 3 (`ihk_pepper_llm_contracts`), einschließlich der
strukturellen (nicht nur prompt-basierten) Sicherheitsgrenzen.

## Warum drei Stufen statt einem großen LLM-Aufruf

Ein einzelnes LLM, das direkt Text, Gesten und ROS-Aktionen ausgibt,
kann prinzipbedingt nicht zuverlässig zwischen "das sage ich" und "das
führe ich aus" trennen. Die Architektur erzwingt diese Trennung
strukturell -- nicht per guter Prompts, sondern per Schema:

```{figure} ../_static/images/three-stage-llm-pipeline.svg
:alt: Nutzerfrage zu LLM 1 Knowledge Planner (nur Suchanfragen), deterministischer Retriever (FAQ exakt, FAQ semantisch, Personengedächtnis nur mit Einwilligung, RAG, sichere Fallback-Antwort), LLM 2 Gesture Planner (nur Namen aus Allowlist), LLM 3 Response Composer (ResponsePlan), ResponsePlanValidator, ResponsePlanExecutor.
:width: 100%

Jeder Pfeil ist eine echte Schema-Grenze -- Stufe 2/3 können Gesten nur
über einen Namen aus einer Allowlist referenzieren, das Feld für
Gelenkdaten existiert im Schema schlicht nicht.
```

```text
Nutzerfrage
  → LLM 1 (Knowledge Planner)       -- NUR Suchanfragen + Unsicherheiten
  → deterministischer Retriever      -- kein LLM, sucht wirklich
  → LLM 2 (Gesture Planner)          -- NUR Gestennamen aus Allowlist
  → LLM 3 (Response Composer)        -- ResponsePlan (Text + Gestennamen)
  → ResponsePlanValidator            -- deterministisch
  → ResponsePlanExecutor             -- Say-/PlayGesture-Actions
```

**Kein LLM in dieser Kette darf**: `SetMotionPermission` aufrufen, rohe
ROS2-/qicli-/SSH-/Shell-Befehle erzeugen, Gelenknamen oder -winkel
festlegen. Das ist keine Prompt-Regel, sondern eine Schema-Grenze --
diese Felder existieren in den Datenstrukturen der Stufen 2/3 schlicht
nicht.

## Stufe 1: Knowledge Planner

**Eingabe**: normalisierte Nutzerfrage, freigegebener `PersonContext`
(kommt aus dem Personengedächtnis, **nie** vom LLM erfunden),
Gesprächsverlauf, Modus.

**Ausgabe**: `search_queries`, `required_data_kinds`, `uncertainties`,
`assumes_known_identity` (muss `False` sein — `validate()` erzwingt
das). Das Schema besitzt **kein** Feld für `person_context` — LLM 1 kann
eine Personenidentität strukturell nicht zurückgeben, nicht nur per
Konvention.

## Deterministischer Retriever

**Kein LLM**, feste Reihenfolge:

```text
exakter FAQ-Treffer
  → semantischer FAQ-Treffer
  → freigegebenes Personengedächtnis (NUR bei use_person_memory UND
    person_context["known"] -- sonst niemals aufgerufen)
  → RAG
  → sichere Antwort ohne Information
```

`source_id`s folgen einem festen Schema (`faq:<id>`,
`memory:topic:<slug>`, `rag:<chunk_id>`) — **niemals erfunden**, immer
aus der jeweiligen Quelle abgeleitet.

## Stufe 2: Gesture Planner

**Eingabe**: Antwort-Brief aus Stufe 1, aktuelle Robotersituation,
`allowed_gesture_names` (von außen befüllte Allowlist aus
`GestureCatalog.reload()`).

**Ausgabe**: Liste von `GestureSuggestion` (`gesture_name`, `relation`
∈ `{before_segment, with_segment_start, after_segment}`).
`validate(allowed_gesture_names)` lehnt jeden Namen ab, der nicht in der
übergebenen Allowlist steht. **Es gibt in diesem Schema kein Feld für
Gelenke, Winkel, Geschwindigkeiten oder ROS-Befehle** — ein
Struktur-Ausschluss, keine Validierungsregel, die umgangen werden
könnte.

**Fallback bei jedem Fehler**: leere `suggestions`-Liste — der Dialog
läuft ohne Geste weiter.

## Stufe 3: Response Composer

`ResponsePlan = {schema_version, segments: [{text, gesture_name,
gesture_relation}], source_ids, memory_summary_candidate}`.

`ResponsePlanValidator.validate(plan, context)` ist deterministisch,
ruft kein LLM, hat keine Seiteneffekte:

1. **Safety**: `context.safety_ok` muss `True` sein — sonst wird jeder
   Plan abgelehnt, unabhängig vom Inhalt.
2. **Segmentanzahl/-länge**: max. 6 Segmente, Text zwischen 1 und 400
   Zeichen.
3. **Rohe Anweisungen im Text**: eine feste Liste verdächtiger
   Teilstrings (`ros2 `, `ssh `, `qicli `, `sudo `,
   `` ` ``, `$(`, `SetMotionPermission`, ...) wird abgelehnt — ein
   zusätzliches Sicherheitsnetz, kein Ausführungs-Sandbox-Ersatz.
4. **Gestennamen**: nur aus `context.allowed_gesture_names`, zusätzlich
   optional pro Geste auf bestimmte `current_interaction_state`-Werte
   eingeschränkt.
5. **Quellenpflicht**: bei Faktenanspruch (Marker wie "laut", "unsere
   Ausbildung", "kostet") mindestens eine `source_id`.
6. **Erfundene Quellen**: jede `source_id` muss tatsächlich vom
   Retriever gefunden worden sein (`context.known_source_ids`).

## Ausführung: `ResponsePlanExecutor`

Enthält **nur** Reihenfolge-/Zustandslogik — keine eigenen ROS2-Action-
Aufrufe (`say_fn`/`gesture_fn` werden injiziert, testbar ohne echten
ROS2-Node). Ablauf je Segment:

```{list-table}
:header-rows: 1
:widths: 30 70

* - `gesture_relation`
  - Ablauf
* - kein `gesture_name`
  - nur sprechen
* - `before_segment`
  - Geste vollständig, dann sprechen
* - `after_segment`
  - sprechen, dann Geste
* - `with_segment_start`
  - Geste in eigenem Thread gestartet, Sprache im Hauptthread, dann auf
    beide warten -- **explizit keine exakte Wort-Synchronisation**
    behauptet
```

Ein fehlgeschlagenes **Sprach**segment bricht den **gesamten** Plan ab.
Ein fehlgeschlagenes **Geste**nsegment markiert nur dieses Segment als
`failed` — die Sprache läuft weiter (Fallback-Prinzip: "Fehler im
Gestenplayer: Sprache fortsetzen, wenn sicher"). Verhindert
Doppelstarts (`is_busy()`) und behält die Halbduplex-Sperre bis zum
tatsächlichen Ende plus Nachlaufzeit.

## Der `RunDialogue`-Action-Server

Ablauf je Sitzung: Personenkontext laden (nur mit Einwilligung) → auf
Frage warten (Transkript-Topic + hartes Stopp-Wort,
`question_timeout_s`) → Pipeline (LLM1 → Retriever → LLM2 → LLM3 →
Validator) → Executor → bei validiertem Gedächtnis-Vorschlag und
bekannter, einwilligender Person: `WriteMemorySummary` → zurück zum
Frage-Warten.

Abbruchbedingungen: Sitzungs-Timeout, Personenverlust
(`MAX_TRACK_AGE_S=2.0s`), Safety-Event, explizites `Action::cancel` --
**keine** dieser Bedingungen setzt je eine Bewegungsfreigabe.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Live Ende-zu-Ende geprüft (zwei Szenarien: bekannte
Person mit Einwilligung, unbekannte Person ohne Einwilligung — beide bis
`WAITING_FOR_FOLLOWUP` durchgelaufen). Nur `MockLLMProvider` wurde
tatsächlich durchlaufen. {{ unverified }} `AnythingLLMProvider`/
`OpenAICompatibleProvider` gegen einen echten Endpunkt.
{{ hwverificationrequired }} für die Ausführung auf echtem Pepper (Say/
PlayGesture-Actions gegen echte Hardware).

## Nächster Schritt

[Personengedächtnis](person-memory.md).
