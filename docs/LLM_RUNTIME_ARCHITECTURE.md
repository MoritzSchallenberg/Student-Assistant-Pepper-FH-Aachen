# LLM-Laufzeit-Architektur (RunDialogue)

Stand: 2026-09-04. Entwicklungsauftrag 3, AP11.
Implementierung: `ihk_pepper_dialog/run_dialogue_action_server.py`,
`ihk_pepper_behavior_tree` (`RunDialogueViaBT`, `IsConversationReady`,
`trees/pepper_main.xml::DialogueSubtree`).
Siehe auch `docs/LLM_PIPELINE_DESIGN.md` (Verträge),
`docs/LLM_PROVIDER_CONFIGURATION.md` (Provider-Konfiguration),
`docs/RESPONSE_PLAN_EXECUTION.md` (Executor), `docs/PERSON_MEMORY_RUNTIME.md`.

## Einstieg: Behavior Tree

`trees/pepper_main.xml`s Root-`ReactiveFallback` prüft `DialogueSubtree`
zwischen `GreetAndApproachSubtree` und `InteractionSubtree`:

```xml
<BehaviorTree ID="DialogueSubtree">
  <Sequence name="Dialogue">
    <IsConversationReady/>
    <RunDialogueViaBT session_id="{target_track_id}"/>
  </Sequence>
</BehaviorTree>
```

`IsConversationReady` ist die bestehende `InteractionStateCondition`
ein fünftes Mal registriert (`INTERACTION_STATE_CONVERSATION_READY = 7`).
`RunDialogueViaBT` (`StatefulActionNode`, Muster wie
`ApproachSelectedPerson`) startet die `RunDialogue`-Action, deren
`onHalted()` bei Präemption (Safety/`ReactiveFallback`) die laufende
Action wirklich abbricht -- erteilt dabei nie eine Bewegungsfreigabe.

## Ablauf innerhalb einer `RunDialogue`-Sitzung

```
Ziel uebernehmen (session_id = Track-ID als String)
  -> Personenkontext laden (GetPersonContext-Service, nur mit Consent nutzbar)
  -> Schleife:
       - Cancel/Sitzungs-Timeout/Personenverlust/Safety-Event pruefen
       - auf Frage warten (Transkript-Topic + hartes Stopp-Wort, question_timeout_s)
       - Pipeline: LLM1 (Knowledge Planner) -> Retriever -> LLM2 (Gesture
         Planner) -> LLM3 (Response Composer) -> ResponsePlanValidator
       - bei ungueltigem, NICHT sicherheitsrelevantem Ergebnis: sicherer
         Fallback-Plan direkt aus answer_brief.facts
       - bei safety_ok=False: Runde komplett uebersprungen (Sprache UND
         Geste gemeinsam abgebrochen)
       - ResponsePlanExecutor.execute(plan)
       - bei validiertem memory_summary_candidate UND bekannter,
         einwilligender Person: WriteMemorySummary-Service
       - Feedback WAITING_FOR_FOLLOWUP, zurueck zum Frage-Warten
```

## Abbruchbedingungen (keine setzt je eine Bewegungsfreigabe)

| Bedingung | Prüfung |
|---|---|
| Sitzungs-Timeout | `session_timeout_s` (Default 180s) |
| Frage-Timeout | `question_timeout_s` (Default 20s) |
| Personenverlust | `_track_alive`, `MAX_TRACK_AGE_S = 2.0s` (Muster wie `person_approach_node.py::_validate_target`) |
| Safety-Event | `_safety_ok`: kein `emergency_stop`, kein `bumper_active` |
| Stopp-Wort | bestehendes `ihk_pepper_audio/cancel_words.py::is_hard_stop` |
| Explizites Cancel | `Action::cancel` (BT-Präemption oder direkter Client-Cancel) |

## Konfiguration (Node-Parameter)

`knowledge_llm_provider`/`gesture_llm_provider`/`response_llm_provider`
(siehe `docs/LLM_PROVIDER_CONFIGURATION.md`), `session_timeout_s` (180.0),
`question_timeout_s` (20.0), `post_speech_pause_s`.

## Wichtige Implementierungsdetails

- `FaqCache`/`sentence-transformers` werden in `main()` **vor**
  `rclpy.init()` geladen (identische Reihenfolge wie
  `dialog_manager_node.py` -- sonst `RCLError: rcl node's context is
  invalid`).
- `_say_and_wait`/`_gesture_and_wait`/`_send_goal_and_wait` reimplementieren
  das blockierende `presentation_manager_node.py::_say_and_wait()`-Muster
  lokal (kein Cross-Package-Import).
- `MultiThreadedExecutor` + `ReentrantCallbackGroup` (wie
  `presentation_manager_node.py`) -- notwendig, damit die blockierenden
  Warte-Aufrufe innerhalb der Action selbst auf einem eigenen Thread
  laufen, ohne den Node insgesamt zu blockieren.

## Live-E2E-Nachweis (dieser Session)

`ihk_pepper_tests/test/manual_dialogue_e2e_check.py` (zwei Szenarien,
`known_person`/`unknown_person`) -- beide sauber bis
`WAITING_FOR_FOLLOWUP` durchgelaufen, siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md` AP11 für die vollständigen
Log-/SQLite-Nachweise.

## Gesten-Vektordatenbank verdrahtet (Entwicklungsauftrag 04-B, AP5A)

`_run_pipeline()` ruft nach LLM1+Retriever `_search_gestures()` auf
(echter Client für `/search_gestures`, siehe `docs/PERSON_MEMORY_RUNTIME.md`
für die Datenbank selbst). Suchanfrage NUR aus bereits geprüften Daten
(`normalized_intent`, Frage, erste 2 `AnswerBrief`-Fakten) -- keine
Namen/IDs. Fällt der Service aus, ist deaktiviert oder überschreitet
`gesture_search.service_timeout_s` (Default 0.75s): leere
Kandidatenliste, die Antwort wird trotzdem gesprochen, nur ohne Geste.

**Fail-closed Laufzeitsignale** (neue Abonnements
`/nav2_moving`, `/mapping_active`, `/pepper_bridge/gesture_in_progress`,
`/pepper_bridge/connection_state`, dazu `/safety_state` jetzt mit
Aktualitätsprüfung): jedes Signal nutzt `safety_topics.FreshBool`
(dieselbe Klasse wie `motion_guard_node.py`/`supervisor_node.py`, hier
als dritte bewusste Kopie in `ihk_pepper_dialog/safety_topics.py`, siehe
`test_safety_topics_consistency.py`). Ein fehlendes/veraltetes Signal
löst sich IMMER in die sichere Richtung auf
(`_runtime_gesture_context()`): `nav2_moving`/`mapping_active`/
`gesture_in_progress` → `True` (sperrt), `pepper_reachable` → `False`
(sperrt). `PlanContext` wird bei JEDEM Durchlauf vollständig aus diesen
Werten aufgebaut -- nie über den Dataclass-Default.

**Drei-Mengen-Allowlist-Kette** (siehe `docs/LLM_PIPELINE_DESIGN.md`):
`database_candidates` → `llm2_selected_gestures` → validierte
`final_execution_allowlist`. **Wiederholungsschutz**: eine pro Sitzung
lokale Liste (`recent_gestures`, Fenstergröße
`gesture_search.recent_gesture_window`, Default 3) geht als
`exclude_recent` in jede Suche ein -- nur erfolgreich ausgeführte,
thematische (nicht System-)Gesten zählen.

**Unmittelbarer Recheck vor jeder Ausführung** (`_recheck_before_gesture()`,
Abschnitt 8 des Auftrags): SafetyState/Erreichbarkeit/Nav2/laufende
Geste erneut geprüft, plus (bei thematischen Gesten) erneuter Abgleich
gegen `final_execution_allowlist`/erlaubte Interaktionszustände, plus
(bei Kopfgesten, auch Systemgesten) Mapping-Sperre. **Zusätzliche
Schutzschicht -- ersetzt NICHT den späteren zentralen Aktuator-Arbiter
(AP5B).**

## Bekannte, offene Punkte

- Mehrere Gesten-YAMLs referenzierten bis AP13 den ungültigen
  `InteractionState`-Wert `SPEAKING` -- behoben (siehe
  `docs/GESTURE_AUTHORING.md`).
- `mapping_active`/`current_interaction_state` werden über den
  `PlanContext` an den Validator/Executor durchgereicht, aber nicht aus
  einer live laufenden Navigation erprobt (`navigation_live.launch.py`
  wird in diesem Auftrag nicht gestartet).
- Der Recheck vor jeder Gestenausführung (AP5A, Abschnitt 8) ist eine
  zusätzliche Schutzschicht ohne echten zentralen Ressourcen-Arbiter --
  folgt in AP5B.
- `_search_gestures()`/der gesamte Gesten-Datenfluss ist nur offline
  (Mock-Provider, Fake-Service) getestet, nicht gegen einen echten
  `gesture_memory_node`-Prozess in dieser Session.
