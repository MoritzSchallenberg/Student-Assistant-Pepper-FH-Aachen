# Entwicklungsauftrag 04-B: KI:connect, Gesten-Vektordatenbank, dynamische Interaktion, Personen-Lebenszyklus, Kopf-Mikrofon

Branch: `order-04b-kiconnect-gesture-memory-lifecycle-audio` (von
`order-03-llm-memory-kinematic-gestures`, Abschluss-Commit `a3d143b`).

## Vorgeschichte: Übernahme geprüfter Commits von einem anderen Branch

Vor AP5A wurden -- nach ausdrücklicher Nutzergenehmigung und Prüfung
durch zwei Recherche-Durchläufe -- 9 Commits vom Branch
`order-04-safe-integration-gesture-vector-head-audio` (entstanden in
einer anderen Sitzung, direkt von `a3d143b` abgeleitet über den
Zwischen-Branch `order-15-pepper-developer-tutorial`) einzeln, in
Original-Reihenfolge, per `git cherry-pick` übernommen:

```
baeffb0  Arbeitspaket 15: Pepper Developer Tutorial
0a87801  AP1: Sicherheitsbereinigung und Buildwiederherstellung
8bb06b3  AP2: Pepper-Bridge SSH absichern, reale Statustopics
cdd98d8  AP3: zentrale sichere Startdatei interaction_full_safe.launch.py
dfe5bf3  KIConnect-Provider (LLM 3), Datenschutzfilter und ihre Testsuite
ba28f96  Gesten-Vektordatenbank (neues Paket ihk_pepper_gesture_memory)
0dd49c5  "Mhm"-/Denksequenz: ACKNOWLEDGING + WAITING_FOR_RESPONSE
2235411  AP0: Sicherheitsbereinigung -- Exporttest + absolute Entwicklerpfade entfernt
a302e6d  AP2/AP3: Bridge-/Supervisor-/Motion-Guard-Topicfehler, fail-closed Defaults, Latch-Bug behoben
```

Vorher: nicht-destruktiver Sicherungsbranch `order-04b-pre-cherry-pick-backup`
angelegt. Alle 9 Commits wendeten sich **ohne einen einzigen Konflikt**
an. Nach jeder logischen Gruppe (4 + 3 + 2) wurde neu gebaut und die
volle Regression gefahren -- durchgehend grün. Zwei danach identifizierte
Lücken wurden in einem eigenen Folgekommentar behoben (nicht Teil der
übernommenen Commits): der KI:connect-Provider erbte über die geteilte
`ProviderConfig.from_env()` denselben Token-Fallback wie alle anderen
Provider (`ANYTHINGLLM_API_TOKEN`) -- behoben durch eine neue
`ProviderConfig.from_env_dedicated_token()`, die dieser Provider jetzt
exklusiv nutzt; `interaction_full_safe.launch.py` hatte keinen
automatisierten Test -- 16 neue Struktur-/Verhaltenstests ergänzt.

Ergebnis vor AP5A: **526/526 Python-Tests** (3 bewusst übersprungen), BT.CPP
unverändert **17/0/0/3**.

## AP5A: Gesten-Vektordatenbank vollständig in die LLM-Pipeline integrieren

### 1. Ausgangslücke (bestätigt)

`run_dialogue_action_server.py::_run_pipeline()` enthielt tatsächlich
`allowed_gesture_names = []` -- der vorhandene `gesture_memory_node`
(aus der Commit-Übernahme) bot `/search_gestures` bereits an, wurde
aber vom Dialogserver nie aufgerufen. Bestätigt durch Code-Lektüre vor
jeder Änderung.

### 2. Datenflusskette (jetzt implementiert)

```
Nutzerfrage
→ LLM 1 (Knowledge Planner, unveraendert)
→ AnswerBrief (Retriever, unveraendert)
→ _search_gestures(): echter /search_gestures-Client
→ database_candidates (harte Filter bereits serverseitig angewendet,
  zusaetzlich clientseitig defensiv gegen system_only/nicht-LLM-waehlbar gefiltert)
→ LLM 2 waehlt NUR aus database_candidates (allowed_gesture_names)
→ llm2_selected_gestures (== was LLM 2 tatsaechlich validiert ausgewaehlt hat)
→ LLM 3 bekommt NUR llm2_selected_gestures als allowed_gesture_names
  (NICHT die volle database_candidates-Menge -- der zentrale Fix)
→ ResponsePlanValidator mit vollstaendig fail-closed aufgebautem PlanContext
→ final_execution_allowlist == {seg.gesture_name fuer validierte Segmente}
→ ResponsePlanExecutor: Say-Action immer, PlayGesture-Action nur nach
  zusaetzlichem Recheck unmittelbar vor dem Aufruf
```

### 3. Gestensuche im Dialogserver

`_search_gestures(query, interaction_state, exclude_recent)`: Suchtext
NUR aus `knowledge_plan.normalized_intent` + Frage + ersten 2
`AnswerBrief`-Fakten (keine Namen/IDs/Personenakten). Nutzt die echten
aktuellen `nav2_moving`/`mapping_active`-Werte (keine Platzhalter), damit
LLM 2 gar nicht erst Kandidaten angeboten bekommt, die ohnehin gesperrt
wären. Bei deaktiviertem Service (`gesture_search.enabled=false`),
fehlendem Server, Zeitüberschreitung (`service_timeout_s`, Default
0.75s) oder einem Fehler: leere Liste, Antwort wird trotzdem gesprochen.

Neue Node-Parameter (dotted, exakt wie im Auftrag benannt):
`gesture_search.enabled` (true), `gesture_search.service_timeout_s`
(0.75), `gesture_search.top_k` (5), `gesture_search.max_duration_s`
(6.0), `gesture_search.minimum_tested_status_development`
(dry_run_validated), `gesture_search.recent_gesture_window` (3).

### 4. Fail-closed Laufzeitdaten

Neue Abonnements: `/nav2_moving`, `/mapping_active`,
`/pepper_bridge/gesture_in_progress`, `/pepper_bridge/connection_state`
(alle über `ihk_pepper_dialog/safety_topics.py` -- eine dritte,
bewusste, byte-inhaltsgleiche Kopie von
`ihk_pepper_bridge`/`ihk_pepper_interaction`s Version, siehe
`test_safety_topics_consistency.py`, jetzt 3-fach geprüft). `/safety_state`
bekam eine Aktualitätsprüfung ergänzt (vorher nur `is None`-Prüfung,
kein Alterslimit).

Jedes Signal nutzt `safety_topics.FreshBool` mit denselben
Initialwerten wie `motion_guard_node.py`/`supervisor_node.py`
(Aktivitäts-/Gefahrensignale starten `True`, Erreichbarkeits-/
Validitätssignale `False`). `_runtime_gesture_context()` löst ein
fehlendes/veraltetes Signal IMMER in die sichere Richtung auf:
`nav2_moving`/`mapping_active`/`gesture_in_progress` → `True` (sperrt),
`pepper_reachable` → `False` (sperrt). `PlanContext` wird bei jedem
`_run_pipeline()`-Durchlauf vollständig aus diesen berechneten Werten
neu aufgebaut -- die Dataclass-Defaults selbst wurden NICHT verändert
(andere, bereits bestehende Aufrufer/Tests verlassen sich darauf), aber
der einzige produktive Aufrufer verlässt sich nie mehr stillschweigend
darauf.

### 5. Kandidatenmetadaten

`GestureCandidate.msg` bekam `bool affects_head` (vorher fehlend, obwohl
`GestureIndexEntry`/die SQLite-Datenbank es bereits intern führten --
nur die ROS2-Schnittstelle hatte das Feld nicht). `gesture_memory_node.py`
gibt es jetzt weiter. LLM 2 bekommt über das neue
`GesturePlanRequest.gesture_options: list[GestureOption]`-Feld
ausschließlich Name/Beschreibung/Dauer/Ähnlichkeit/erlaubte Zustände --
kein Gelenk-/Trajektorien-/Befehlsfeld existiert in `GestureOption`
überhaupt (Struktur-Ausschluss, kein nachträglicher Filter).
`allowed_gesture_names` bleibt zusätzlich als deterministische
Validierungsgrundlage bestehen (unveränderter Vertrag in
`GesturePlanResponse.validate()`).

### 6. Allowlist-Kette (drei Mengen, siehe Datenflusskette oben)

Alle 7 im Auftrag genannten Regeln sind erfüllt: LLM 2 wählt nur aus
`database_candidates` (per `run_gesture_planner()`s bestehender
`validate()`-Aufruf erzwungen); Systemgesten werden datenbankseitig
(`include_system_only=false`) UND clientseitig nie angeboten; LLM 3
bekommt nur `llm2_selected_gestures`; ein nicht ausgewählter
Datenbankkandidat kann nicht nachträglich verwendet werden (vom
`ResponsePlanValidator` gegen `allowed_gesture_names ==
llm2_selected_gestures` geprüft, ein Verstoß lässt den ganzen Plan
scheitern → sicherer Fallback ohne Geste); die endgültige Allowlist ist
die Menge tatsächlich validierter Gesten-Segmente; eine unbekannte
Geste verwirft nur den Gestenteil (nie den ganzen Plan, sofern
Safety/TTS ok sind); leere LLM-2-Auswahl → Pepper spricht ohne Geste.

### 7. Wiederholungsschutz

Pro Sitzung lokale Liste `recent_gestures` (nicht Node-weit -- Variable
in `_execute()`, zurückgesetzt bei jeder neuen `RunDialogue`-Sitzung),
gefüllt mit tatsächlich erfolgreich ausgeführten thematischen Gesten
(`_successfully_executed_gesture_names()`, verknüpft
`SegmentExecutionResult` über `segment_id` mit dem ursprünglichen
`ResponsePlan`). Auf `gesture_search.recent_gesture_window` Einträge
begrenzt, geht als `exclude_recent` in jede Suche ein. Systemgesten
("Mhm"/Denkschleife) laufen über separate Methoden und aktualisieren
diese Liste nie.

### 8. Erneute Prüfung unmittelbar vor Ausführung

`_recheck_before_gesture()`, aufgerufen von `_gesture_and_wait()` VOR
jedem `PlayGesture`-Versuch: SafetyState (aktuell + frisch), Pepper
erreichbar, keine andere Geste aktiv, Nav2 fährt nicht -- diese vier
gelten für JEDE Geste, auch Systemgesten. Bei thematischen Gesten
zusätzlich: noch in `final_execution_allowlist`, Interaktionszustand
weiterhin erlaubt, Mapping blockiert keine Kopfgeste. Bei Systemgesten
(kein Dialog-Turn-Kontext, `_current_gesture_recheck_context is None`):
Mapping blockiert trotzdem (`SYSTEM_GESTURES_AFFECTING_HEAD`, da beide
den Kopf bewegen). **Ausdrücklich nur eine zusätzliche Schutzschicht --
ersetzt nicht den späteren zentralen Aktuator-Arbiter (AP5B).**

### 9. Tests

**59 neue Tests** in 3 neuen Dateien + Ergänzungen an 2 bestehenden:

- `test_gesture_pipeline_wiring.py` (31): Suchservice-Verhalten
  (Erfolg/Timeout/Fehler/Fehlschlag/deaktiviert/system_only-Ausschluss),
  vollständige Allowlist-Kette (LLM 2 wählt gültig/erfindet Namen, LLM 3
  darf nicht-gewähltes verwenden, leere Kandidaten, Prompt-Injection),
  fail-closed Laufzeitsignale (jedes der 5 Signale einzeln veraltet/fehlend),
  Wiederholungsschutz, Recheck vor Ausführung (inkl. Zustandsänderung
  zwischen Planung und Ausführung), zwei Offline-End-zu-Ende-Tests
  (voller Datenfluss bis Say-/PlayGesture-Mock; Gestensuche fällt aus →
  nur Say-Mock).
- `test_gesture_memory_node_handler.py` (4): `affects_head` erreicht die
  ROS-Antwort korrekt (true/false), Suchfehler crasht den Handler nicht,
  Ergebnis wird auch auf dem Introspektions-Topic veröffentlicht.
- `test_gesture_index_db.py` (+1): `affects_head` wird für eine echte
  Kopf- (`agree_nod`) und Nicht-Kopf-Geste (`wave_right`) korrekt
  persistiert/zurückgegeben.
- `test_interaction_full_safe_launch.py` (+2, jetzt 22): `gesture_memory_node`
  läuft in jedem Modus exakt dann, wenn auch `run_dialogue_action_server`
  läuft; `production_mode`-Parameter löst korrekt nach Modus auf.
- `test_dialogue_thinking_loop.py` (unverändert 10, Signaturen an
  `recent_gestures`-Parameter angepasst): keine Verhaltensänderung.

Gesamttestzahl: **568/568 bestanden, 3 bewusst übersprungen**
(KI:connect-Livetest ohne echtes Token). BT.CPP unverändert **17/0/0/3**.

### 10. Launch-Integration

`gesture_memory_node` teilt sich in `interaction_full_safe.launch.py`
exakt dieselbe Bedingung wie `run_dialogue_action_server` (beide `mode
!= pepper_gesture_test`) -- durch Test bestätigt für alle 5 relevanten
Modi. Keine expliziten `gesture_search.*`-Parameter im Launchfile nötig:
die Node-eigenen Defaults entsprechen bereits der im Auftrag
vorgegebenen Beispielkonfiguration (dokumentiert als Kommentar an der
`run_dialogue_action_server`-Node-Deklaration). `production_mode` für
`gesture_memory_node` bleibt korrekt an `mode == "production"` gebunden.
`dialog_manager_node` wird -- wie seit AP2/AP3 der Fall -- in dieser
Datei nie referenziert.

### 11. Dokumentation

Aktualisiert: `docs/LLM_PIPELINE_DESIGN.md` (Drei-Mengen-Allowlist-Kette),
`docs/LLM_RUNTIME_ARCHITECTURE.md` (Fail-closed Laufzeitsignale,
Recheck-Mechanismus), `docs/RESPONSE_PLAN_EXECUTION.md` (Recheck in
`_gesture_and_wait()`). Kein Nutzertext/keine Personeninformation/kein
vollständiger externer Prompt in normalen Logs -- Suchanfragen werden
nur aus bereits pseudonymisierten/aggregierten Feldern gebaut, Logging
bleibt auf Zähler/Kurzstatus beschränkt (`self.get_logger().debug(...)`
mit Kandidatenzahlen, nie mit Rohtext).

### Ehrlicher Stand / verbleibende Punkte

- Der gesamte neue Datenfluss ist ausschließlich offline getestet (Mock-
  LLM-Provider, Fake-Service-Client) -- **kein Test lief gegen einen
  echten laufenden `gesture_memory_node`-Prozess** in dieser Sitzung.
- **Der zentrale Aktuator-Arbiter (AP5B) fehlt weiterhin.** Der Recheck
  in Abschnitt 8 ist eine zusätzliche, lokale Schutzschicht in
  `run_dialogue_action_server.py` selbst -- kein systemweit verwalteter
  Ressourcen-Arbiter, keine echte Cancel-Weiterleitung an eine zentrale
  Instanz. `QicliTrajectoryTransport.cancel()` bleibt (aus Auftrag 3) ein
  Best-Effort ohne echtes Mid-Trajectory-Abbrechen.
- Keine Livebewegung, keine neue Kinematik, kein ReSpeaker, kein echter
  KI:connect-Aufruf, kein `navigation_live.launch.py`, kein echter
  `/cmd_vel`, kein Push auf `main`, kein Force-Push -- alle Grenzen aus
  Abschnitt 12 eingehalten.
- Working Tree nach Abschluss dieses Arbeitspakets sauber, ein einzelner
  klar abgegrenzter Commit für AP5A (siehe Commit-Historie).

Als Nächstes ausdrücklich vorgesehen: **AP5B** (zentraler Aktuator-Arbiter,
echte Action-Cancellation), **AP6** (ReSpeaker Core v2.0, DoA,
Beamforming, Wakeword), **AP7** (vollständiger
Personen-Interaktionslebenszyklus).
