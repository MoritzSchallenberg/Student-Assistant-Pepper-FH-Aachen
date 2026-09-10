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

## AP5B: Zentraler Aktuator-Arbiter und nachweisbare Action-Cancellation

Umgesetzt in 6 aufeinander aufbauenden Commits, jeweils nach betroffenen
Tests gebaut. Details je Bereich stehen in eigenen Dokumenten (siehe
Verweise unten); dieser Abschnitt fasst zusammen, was gebaut wurde und
was ehrlich offen bleibt.

### 1. Bestandsaufnahme/Baseline

Baseline vor AP5B: 661 Python-Tests grün, BT.CPP 17/0/0/3 (bereits reine
Lint-/Stil-Prüfungen, kein funktionaler gtest-Harness -- siehe unten).
`apps/web/pepper/qicli.py::say()` wurde bei der Bestandsaufnahme als
real verwundbar identifiziert: der Text wurde per f-String direkt in
literale doppelte Anführungszeichen eines Shellbefehls eingebettet
(Shell-Injection). Fähigkeitstest für Mid-Trajectory-Cancel: `qicli`
ruft NAOqi ausschließlich über synchrone SSH-Shell-Befehle auf, es gibt
kein async Task-Handle -- siehe `docs/ACTION_CANCELLATION.md`,
Abschnitt "Fähigkeitstest" für die vollständige A/B/C-Bewertung. Ergebnis:
Option C (ehrliches Best-Effort + `hwverificationrequired`-Markierung)
umgesetzt, wie vom Auftrag für genau diesen Fall vorgesehen.

### 2. Commit 1/6: Aktuator-Arbiter-Kernlogik

Neues Modul `ihk_pepper_interaction/actuator_arbiter.py` (reine,
ROS-freie Zustandsmaschine, injizierbare Zeitfunktion wie
`CircuitBreaker`/`FreshBool`) + `resource_derivation.py` +
`actuator_arbiter_node.py` (ROS2-Wrapper: 4 Services, 3 Topics,
fail-closed bis zum ersten `SafetyState`). 7 neue Interfaces
(`ActuatorLease.msg`, `ActuatorResourceState.msg`, `ActuatorState.msg`,
`AcquireActuatorLease.srv`, `RenewActuatorLease.srv`,
`ReleaseActuatorLease.srv`, `CancelActuation.srv`). Ressourcen,
Prioritäten, Konflikt-/Präemptionsregeln, serverseitiges
Vertrauensmodell: vollständig in `docs/ACTUATOR_ARBITER.md`
dokumentiert. 66 neue Tests.

### 3. Commit 2/6: Bounded Cancellation in Transport/Bridge

`motion_transport.py`: neues `CancelResult`-Dataclass ersetzt das
bisherige unbegrenzte `cancel() -> None` (bestätigter Fund: konnte bei
einer laufenden synchronen Trajektorie beliebig lange blockieren).
`pepper_client.py`: neue `PepperInterruptChannel`-Klasse (zweite,
unabhängige SSH-Verbindung ausschließlich für
`stop_speech()`/`stop_motion()`/`send_hold_position()`).
`apps/web/pepper/qicli.py`: Shell-Injection in `say()` behoben
(`shlex.quote()`), neue `say_text_only()` (kein automatisches
`ALAnimatedSpeech`-Körperspiel). Neues `ihk_pepper_bridge/tts_guard.py`
als zusätzliche, unabhängige TTS-Text-Validierung an der Bridge-Grenze.
`GestureCatalog.play()` bekam optionale `cancel_event`/
`interrupt_channel`-Parameter (rückwärtskompatibel). `bridge_node.py`:
`_execute_say()`/`_execute_gesture()` laufen jetzt im
Hintergrundthread mit begrenztem Polling, erwerben zuerst eine Lease
vom Arbiter. Volle Details: `docs/GESTURE_TRANSPORT.md`,
`docs/ACTION_CANCELLATION.md`. Viele neue Tests über
`test_motion_transport.py`, `test_qicli.py`, `test_tts_guard.py`
(neu, 15), `test_gesture_catalog_cancel.py` (neu, 6),
`test_bridge_node_actuator_arbiter.py` (neu, 13).

### 4. Commit 3/6: Cancel-Weiterleitung durch Dialog, Behavior Tree, Presentation Manager

`response_plan_executor.py`: neuer `cancel_active_fn`-Hook, von
`cancel()` sofort zusätzlich zum bestehenden Flag aufgerufen.
`run_dialogue_action_server.py`: `_send_goal_and_wait()` bricht bei
eigenem Timeout jetzt aktiv ab (begrenzte 2.0s-Bestätigung); neue
`_cancel_active_actions()`; `executor.execute()` läuft im
Hintergrundthread mit 0.1s-Cancel-Poll-Schleife. `bt_nodes.hpp/.cpp`:
neue, ROS-unabhängige `waitForBoundedCancelConfirmation()` --
`onHalted()` aller 5 Action-Knoten wartet jetzt begrenzt (250ms) auf
Cancel-Bestätigung statt komplett ohne Feedback abzubrechen.
`presentation_manager_node.py`: `_cancel_callback()` bricht das aktive
Say-Ziel jetzt sofort ab, statt erst an der nächsten `_check_cancel()`-
Stelle. Volle Details: `docs/RESPONSE_PLAN_EXECUTION.md`,
`docs/BEHAVIOR_TREE.md`, `docs/ACTION_CANCELLATION.md`. Neue Tests:
`test_response_plan_executor.py` (+2), `test_run_dialogue_cancellation.py`
(neu, 7), `test_presentation_manager_cancel.py` (neu, 5),
`test_bt_cancel_confirmation.cpp` (neu, 3 gtest -- BT.CPP damit auf
23/0/0/4, vorher 17/0/0/3).

### 5. Commit 4/6: BASE-Lease-Integration -- Navigation und Motion Guard

`motion_guard.py`: neues, pflichtiges `base_lease_valid`-Feld,
zusätzliche Prüfung direkt nach `safety_allow_motion` -- fehlt/ist
veraltet die Lease, wird jeder von Null verschiedene Fahrbefehl
blockiert (ein Stopp-Befehl kommt trotzdem immer durch, siehe
`docs/ACTUATOR_ARBITER.md`). `motion_guard_node.py`: neues fail-closed
`FreshBool` für `/actuator_arbiter/base_lease_valid` (neue Konstante in
allen 3 Kopien von `safety_topics.py` identisch ergänzt).
`person_approach_node.py::_drive_to_pose()`: erwirbt die BASE-Lease VOR
jedem Nav2-Ziel, erneuert sie periodisch während längerer Fahrten, gibt
sie in jedem Ausstiegspfad frei. Bumper/Not-Halt widerrufen sie bereits
generisch über `emergency_revoke_all()` (keine Änderung nötig). Neue
Tests: `test_motion_guard.py` (+2), `test_motion_guard_freshness.py`
(+3), `test_person_approach_base_lease.py` (neu, 12, inkl.
End-zu-Ende-Test von `_drive_to_pose()` gegen ein Fake-Nav2).

### 6. Commit 5/6: Legacy-qicli-Umgehungspfade schließen/kenntlich machen

Neuer sicherer Default `PEPPER_WEB_HARDWARE_TEST_ENABLED=false`.
`apps/web/app.py`: neuer `_hardware_test_guard()` -- `/execute` (inkl.
der echten Bewegung `moveTo`), `/al/<enable>`, `/logo`, `/say/<text>`
geben ohne explizite Freigabe sofort 403 zurück, ohne qicli je zu
erreichen. `vision/mimic_arms.py` (bewegt Arme über rohe
`ALMotion.angleInterpolation`-Shellbefehle, komplett an Motion
Guard/Arbiter/Gestenkatalog vorbei -- die gefährlichste der drei
Dateien): `main()` bricht jetzt vor `rclpy.init()` ab, wenn der
Schalter nicht gesetzt ist. War strukturell bereits nie automatisch
gestartet, bleibt das auch. `apps/web/stt/listen_loop.py` (reine
Audioaufnahme, kein `say()`/`moveTo()`): kein harter Block, aber klar
als manuelles Werkzeug mit eigener, von der Bridge unabhängiger
SSH-Verbindung gekennzeichnet. Neue Tests: `apps/web/test_app.py` (8),
`vision/test_mimic_arms.py` (2).

### 7. Commit 6/6: verbleibende Tests, Dokumentation, ehrlicher Abschluss

Neue/aktualisierte Dokumente: `docs/ACTUATOR_ARBITER.md` (neu),
`docs/ACTION_CANCELLATION.md` (neu), `docs/BEHAVIOR_TREE.md` (neu),
`docs/GESTURE_TRANSPORT.md` (Cancel-Architektur aktualisiert),
`docs/RESPONSE_PLAN_EXECUTION.md` (Cancel-Weiterleitung ergänzt), dieser
Abschnitt.

### Testzusammenfassung

- **Python**: 692 Tests grün, 3 übersprungen (vor AP5B: 661) -- 31 neue
  Tests über die Commits 1-5 (66 in Commit 1, weitere in Commit 2, +21
  in Commit 3, +17 in Commit 4, +10 in Commit 5 -- Netto-Zuwachs 692-661
  je nach Zwischenständen, siehe Commit-Historie für die exakten
  Einzelzahlen je Commit).
- **BT.CPP**: 23 Tests, 0 Fehler, 0 Fehlschläge, 4 übersprungen (vorher
  17/0/0/3) -- **wichtiger ehrlicher Hinweis**: die "17" waren
  ausschließlich Lint-/Stilprüfungen (cppcheck/cpplint-Kern/flake8/
  lint_cmake/pep257/uncrustify/xmllint) über `ament_lint_auto`, KEIN
  funktionaler gtest-Harness. AP5B hat mit `test_bt_cancel_confirmation.cpp`
  (3 Tests, `ament_add_gtest`) den ERSTEN echten funktionalen Test für
  dieses Paket ergänzt -- ein vollständiger Mock-Action-Server-Harness
  für die übrigen BT-Knoten existiert weiterhin nicht.
- **apps/web**: 20 Tests grün (8 neu für `app.py`, 12 bereits vorhanden
  für `qicli.py`, davon 6 neu in Commit 2).
- **vision**: 2 neue Tests für `mimic_arms.py`.
- Harter Grep-Test `/cmd_vel` über alle in AP5B geänderten/neuen Dateien:
  kein Treffer.

### Ehrlicher Stand / verbleibende Punkte (gegen Abschnitt 21/22 des Auftrags)

- **Kein echter Pepper in dieser Session erreichbar** -- alle vier
  Hardware-Testphasen (A-D, Auftrag-Abschnitt 16) sind NICHT
  durchgeführt worden. Jeder Cancel-/Bewegungspfad bleibt durchgängig
  `hwverificationrequired` markiert, nirgends wird ein "bestätigter
  Hardware-Abbruch" behauptet, ohne dass echte Hardware das verifiziert
  hätte.
- **Kein echter Mid-Trajectory-Abbruch implementiert** (Fähigkeitstest-
  Ergebnis Option C, siehe oben) -- die begrenzte Bestätigung/der
  zweite SSH-Kanal verkürzen die Reaktionszeit, verwandeln
  `QicliTrajectoryTransport.cancel()` aber nicht in einen echten
  Hardware-Abbruch. Das ist eine bewusste, ehrliche Grenze, keine
  vergessene Aufgabe.
- **`LocalPepperQiHelperTransport`** (Option B, persistenter
  qi-Helper-Prozess) bleibt ein dokumentierter, nicht implementierter
  Platzhalter -- nicht umgesetzt, da nicht ohne echten Pepper
  verifizierbar und ein zusätzliches Sicherheitsrisiko (persistenter
  Fremdprozess auf Pepper) ohne verifizierten Nutzen.
- **BT.CPP-Testabdeckung bleibt lückenhaft**: nur die neue,
  ROS-unabhängige Hilfsfunktion ist per gtest getestet, nicht die
  Knoten selbst gegen einen echten/gemockten Action-Server.
- Keine Livebewegung, kein neuer `/cmd_vel`-Zugriff, kein
  `navigation_live.launch.py`, kein Push auf `main`, kein Force-Push --
  alle Grenzen aus Abschnitt 21 eingehalten.
- Working Tree nach Abschluss dieses Arbeitspakets sauber, 6 klar
  abgegrenzte Commits (siehe Commit-Historie).

Als Nächstes ausdrücklich vorgesehen: **AP6** (ReSpeaker Core v2.0, DoA,
Beamforming, Wakeword) -- laut Auftrag ausdrücklich erst NACH einem
abgeschlossenen AP5B ("Dieses Arbeitspaket ist die zwingende
Sicherheitsgrundlage für AP6").

## AP6: ReSpeaker Core v2.0, gerichtetes Hören und audiovisuelle Gesprächseröffnung

Umgesetzt in 7 Commits auf demselben Branch
(`order-04b-kiconnect-gesture-memory-lifecycle-audio`), direkt auf dem
AP5B-Abschluss-Commit (`5eab935`) aufbauend -- Baseline vor AP6 erneut
verifiziert (Branch/Commit/working tree sauber, 692/692 Python-Tests,
BT.CPP 23/0/0/4).

### Commit 1/7: audit ReSpeaker hardware and define audio contracts

Kein ReSpeaker Core v2.0 in dieser Session erreichbar -- die geforderte
Hardware-/Transportanalyse (Abschnitt 4) ist ein ehrlicher,
literaturbasierter Befund (`docs/RESPEAKER_TRANSPORT.md`), keine
Live-Sondierung. Neue ROS2-Schnittstellen: `SoundDirection.msg`
(bewusst ohne Elevationsfeld), `WakewordEvent.msg`, `AudioFocusState.msg`,
`SetHeadPose.action`, `OrientToSound.action`. Neue Vertragsmodule
(`ihk_pepper_audio/respeaker_transport.py`, `directional_audio.py`,
`ssh_hardening.py`) mit den abstrakten Basen + sofort funktionsfähigen
Referenzimplementierungen (`MockPcmTransport`, `PassthroughTestBackend`).
26 neue Tests.

### Commit 2/7: add ReSpeaker multichannel source and transports

Die drei konkreten Transporte (`LocalAlsaTransport`/`SshPcmTransport`/
`NetworkPcmTransport`) implementiert -- alle drei
`hwverificationrequired`. Neue `ReSpeakerCoreV2Source(AudioSource)`:
validiert Kanalzahl fail-closed, erkennt Paketverluste, verwirft
veraltete Frames, hält den Mono-Puffer begrenzt, veröffentlicht
Diagnosedaten als Attribute. Bestätigter Fund behoben:
`PepperPulseAudioSource.connect()` verwendete `paramiko.AutoAddPolicy()`
-- auf dieselbe Härtung wie `qicli.py` (Entwicklungsauftrag 4)
umgestellt. 26 neue Tests.

### Commit 3/7: implement wakeword, DoA and directional audio backend

Neue `GccPhatDelayAndSumBackend` -- Standard-GCC-PHAT zwischen zwei
konfigurierten Mikrofonkanälen (Richtung) + einfaches Delay-and-Sum
(Mono-Signal), ehrlich als Zwei-Mikrofon-Halbebenen-Näherung
dokumentiert. Neues `wakeword_gate.py::WakewordGate` (Mindestkonfidenz/
Cooldown/Gesprächszustand). **Bestätigter Fund behoben**: das bisherige
`_session_active`-Flag in `audio_node.py` war ein EWIGER Ratchet --
einmal per Wakeword gesetzt, nie zurückgesetzt (jede folgende Äußerung
wäre für den Rest des Prozesslaufs transkribiert worden). Ersetzt durch
eine begrenzte Sitzungsdauer (`session_active_timeout_s`) UND ein neues
Abonnement von `/interaction_state` als zentrale Wahrheitsquelle für den
Gesprächszustand (fail-closed bei fehlenden/veralteten Daten). 34 neue
Tests.

### Commit 4/7: add safe sound-oriented head action with HEAD lease

Neue `SetHeadPose`-Action (`bridge_node.py`) -- sicherer Hardware-
Grenzpunkt, ausschließlich `HeadYaw`/`HeadPitch`, erwirbt eine
`HEAD`-Lease (`PRIORITY_ATTRACT`), klemmt auf konservative operative
Grenzen (enger als die vollen Gelenkgrenzen), verwirft Bewegungen auf
Basis veralteter Quelldaten, bricht bei Cancel über den bestehenden
Interrupt-Kanal ab. Neuer Node `orient_to_sound_node.py`
(`ihk_pepper_interaction`) -- semantische Schicht, berechnet ein
sicheres Kopfziel, prüft VOR jedem Versuch alle Sicherheitsvorbedingungen
(Gesprächszustand, Mapping, Nav2, Pepper-Verbindung, SafetyState/
Not-Halt/Bumper), HeadPitch wird NIE aus der Schallrichtung berechnet
(keine Elevation verfügbar). 31 neue Tests.

### Commit 5/7: implement audio-visual person association

Neues `audiovisual_association.py` (reine Logik) + Node +
`AssociatePersonWithSound`-Service: ordnet eine Schallrichtung genau
EINER RealSense-Person zu oder KEINER bei Mehrdeutigkeit -- keine
Gesichtserkennung zum Auflösen von Mehrdeutigkeit. Ehrlich dokumentiert:
Keepout-Zonen-Prüfung im Funktionsvertrag vorbereitet, im ROS-Wrapper
NICHT verdrahtet (fehlende Map-Frame-Transformation der Tracks). 19 neue
Tests.

### Commit 6/7: integrate wakeword greeting subtree and conversation focus

`GreetAndApproachSubtree` wählt keine Person mehr selbstständig
(`SelectStablePerson` entfernt) -- `target_track_id` kommt von
`FindPersonNearSoundRay`. Fünf neue BT-Knoten
(`WaitForFreshWakeword`/`IsHeadOrientationAllowed`/`OrientHeadToSound`/
`FindPersonNearSoundRay`/`IsUnsolicitedAttractAllowed`), eine
Wiederverwendung (`IsConversationInactive` = bestehende
`InteractionStateCondition` unter neuem Namen). Das bisherige ungefragte
Winken in `IdleAttractSubtree` ist per Default gesperrt
(`allow_unsolicited_attract=false`). Neues `audio_focus.py` --
vollständige, reine Zustandsmaschine für den Gesprächsfokus
(`IDLE_WIDE` → ... → `CONVERSATION_FOCUS`/`PEPPER_SPEAKING` →
`RETURNING_TO_IDLE`, plus `AUDIO_DEGRADED` bei Zielverlust). Ehrlich
dokumentiert: der Übergang zu `CONVERSATION_FOCUS` ist im Node
vereinfacht (reagiert auf `CONVERSATION_READY`, kennt aber noch nicht
die konkrete `track_id`/Richtung aus `FindPersonNearSoundRay`). 19 neue
Tests, BT.CPP unverändert 23/0/0/4 (kein neuer funktionaler gtest für
die fünf neuen Knoten -- derselbe, bereits in AP5B dokumentierte
Mock-Action-Server-Harness-Mangel).

### Commit 7/7: add launch modes, tests, Ansible config and documentation

Vier neue Launch-Modi in `interaction_full_safe.launch.py`
(`respeaker_offline_test`/`respeaker_hardware_test`/`audio_visual_test`/
`respeaker_head_test`) -- `respeaker_head_test` als einziger mit echter
Kopfbewegung (`bridge_dry_run=False`), hinter einer eigenen expliziten
Bestätigung (`i_confirm_head_test_supervised`) gesperrt, analog zum
bestehenden `production`-Muster. **Bestätigter, unabhängiger Fund
behoben**: `actuator_arbiter_node` wurde von KEINEM Launch-Modus
gestartet (seit AP5B!) -- ohne ihn hätten Say/PlayGesture/SetHeadPose
in JEDEM bisherigen Modus mit "actuator_arbiter nicht erreichbar"
fehlschlagen müssen. Jetzt in jedem Modus gestartet. Neue
Ansible-Rolle `respeaker_audio` (NUC-Pakete + Konfigurationsvorlage,
optionaler Capture-Dienst als Vorlage vorbereitet, NICHT automatisch
auf den ReSpeaker ausgerollt -- kein eigener Inventar-Host definiert).
6 neue Dokumente (`docs/RESPEAKER_CORE_V2_INTEGRATION.md`,
`docs/AUDIO_FOCUS_AND_BEAMFORMING.md`,
`docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md`,
`docs/RESPEAKER_CALIBRATION.md`, `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`,
dieser Abschnitt), aktualisiert (`README.md`, `docs/CAPABILITIES.md`,
`docs/STATUS.md`, `docs/BEHAVIOR_TREE.md`, `docs/ACTUATOR_ARBITER.md`,
`docs/ACTION_CANCELLATION.md`). 23 neue Tests
(`test_interaction_full_safe_launch.py`).

### Testzusammenfassung

- **Python**: 870 Tests grün, 3 übersprungen (vor AP6: 692) -- **+178
  neue Tests** über die 7 Commits.
- **BT.CPP**: unverändert 23 Tests, 0 Fehler, 0 Fehlschläge, 4
  übersprungen -- keine Regression, aber auch kein neuer funktionaler
  Test für die fünf neuen BT-Knoten (gleicher, in AP5B bereits
  dokumentierter Mock-Action-Server-Harness-Mangel).
- Harter Grep-Test `/cmd_vel` über alle in AP6 geänderten/neuen Dateien:
  kein Treffer. `navigation_live.launch.py` wurde zu keinem Zeitpunkt
  gestartet, kein echter `ros2 launch`-Prozessstart in dieser Session.

### Gewählter ReSpeaker-Transport/erkannter ALSA-Gerätename/Kanalreihenfolge

**Keiner verifiziert.** `respeaker_transport_kind` bleibt Standard
`mock`. Der Gerätename `seeed-8mic-voicecard` und die Kanalzuordnung
(`microphone_channels=[0,1,2,3,4,5]`, `loopback_channels=[6,7]`) sind
literaturbasierte Vorlagen aus verwandten Seeed-ReSpeaker-Produkten
(4-/6-Mic-Array-HATs), NICHT am Core v2.0 selbst nachgemessen -- siehe
`docs/RESPEAKER_TRANSPORT.md`, Abschnitt "Was noch zu verifizieren ist".

### Verwendetes Wakeword-Modell/DoA-Backend

Kein Wakeword-Modell trainiert/mitgeliefert in dieser Session --
`WakewordDetector` (openWakeWord, aus Entwicklungsauftrag 3) bleibt ohne
konfiguriertes Modell deaktiviert (`enabled=False`, fail-closed,
unverändertes Verhalten). Produktiv vorgesehenes DoA-Backend:
`GccPhatDelayAndSumBackend` (CPU-Fallback). `PassthroughTestBackend` für
reine Verdrahtungstests ohne jede Richtungsbehauptung.

### Ehrlicher Stand / bekannte Lücken

- **Die TF-Transformation der Schallrichtung (`respeaker_link` →
  `base_link`) ist NICHT implementiert** (Auftrag Abschnitt 11) -- der
  vom `DirectionalAudioBackend` gelieferte Rohwinkel wird unverändert
  als "bereits in `base_link`" weitergereicht. Das ist die wichtigste
  offene Lücke dieses Arbeitspakets, siehe
  `docs/RESPEAKER_CORE_V2_INTEGRATION.md`, Abschnitt TF, für den
  empfohlenen nächsten Schritt. Blockiert Hardwareabnahme-Phase B/E
  vollständig.
- Die GCC-PHAT-Konfidenzformel ist ausdrücklich NICHT kalibriert (siehe
  `docs/RESPEAKER_CALIBRATION.md`).
- Die Keepout-Zonen-Prüfung in der audiovisuellen Zuordnung ist
  vorbereitet, aber nicht verdrahtet (siehe
  `docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md`).
- `audio_focus_node.py`s Übergang zu `CONVERSATION_FOCUS` ist
  vereinfacht (siehe `docs/AUDIO_FOCUS_AND_BEAMFORMING.md`).
- GCC-PHAT liefert nur eine Zwei-Mikrofon-Halbebenen-Schätzung, keine
  volle 360-Grad-Auflösung über alle Kanäle.
- Kein AEC implementiert (Auftrag erlaubt das ausdrücklich -- Halbduplex
  bleibt verpflichtend, `allow_barge_in` bleibt `false`).
- Kein Wakeword-Modell/keine ReSpeaker-Hardware/kein Pepper-Kopf real
  getestet -- alle fünf Hardwaretestphasen (A-E) NICHT durchgeführt,
  siehe `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`.
- Keine Livebewegung, kein `/cmd_vel`, kein `navigation_live.launch.py`,
  kein Push auf `main`, kein Force-Push.
- Working Tree nach Abschluss dieses Arbeitspakets sauber, 7 klar
  abgegrenzte Commits.

### Empfehlung für das nächste Arbeitspaket

Vor jeder weiteren Hardwarearbeit an AP6 selbst: die TF-Transformation
(`respeaker_link` → `base_link`) implementieren -- ohne sie bleiben die
Hardwaretestphasen B und E strukturell blockiert. Danach: die
Kalibrierung nach `docs/RESPEAKER_CALIBRATION.md` an echter Hardware
durchführen (Phase A), sobald ein ReSpeaker Core v2.0 verfügbar ist.
Unabhängig davon aus dem ursprünglichen Gesamtplan weiterhin offen:
AP13 (ID-Trennung + echte Retriever-Anbindung verifizieren), AP8
(weitere kinematisch entwickelte Gesten), AP14 (Emotion-Gating). Die
endgültige Priorisierung bleibt beim Auftraggeber.

## AP6.1: Frame-korrekte Audiofusion und echte personengebundene Gesprächsfokussierung

Nachfolgeauftrag zu AP6 -- benennt 7 in AP6 selbst als offen
dokumentierte, jetzt vom Auftraggeber **bestätigte** Lücken (Auftrag
Abschnitt 3) und verlangt sie geschlossen, bevor AP7/weitere Gesten/
Hardware-Phase B-E begonnen werden. Umgesetzt in 7 Commits auf
demselben Branch (`order-04b-kiconnect-gesture-memory-lifecycle-audio`),
direkt auf dem AP6-Abschluss-Commit (`23c5c3b`) aufbauend -- Baseline
davor erneut verifiziert (Branch/Commit/working tree sauber, 870/870
Python-Tests, BT.CPP 23/0/0/4).

### Commit 1/7 (`ff7ae69`): preserve audio timestamps and enforce fail-closed activation

Bestätigter Fund 3.2 (teilweise) behoben: `_publish_sound_direction_if_available()`
vergab bislang für jede Probe den Empfangszeitpunkt statt eines
eigenen, echten Zeitstempels; `WaitForFreshWakeword` überschrieb den
echten `WakewordEvent.header.stamp` zusätzlich mit dem BT-Tick-
Zeitpunkt (zweite Hälfte dieses Funds erst in Commit 6 behoben, siehe
dort). Neuer `direction_sample_buffer.py::DirectionSampleBuffer` --
zeitfensterbasierte, konfidenzgewichtete Zirkularmittelung (`atan2`)
ersetzt eine einzelne globale "letzte Richtung"-Variable.

Bestätigter Fund 3.4 behoben: `audio_node.py::_session_active()` hatte
`if not self.wakeword.enabled: return True` -- ohne geladenes
Wakeword-Modell wurde DAUERHAFT transkribiert, statt nie. Ersetzt durch
einen expliziten `activation_mode`-Zustand
(`wakeword_required`/`push_to_talk`/`continuous_development`),
`continuous_development` in `production_mode=true` beim Start hart
gesperrt (`RuntimeError`). 25 neue Tests (14
`test_direction_sample_buffer.py`, 11 `test_audio_node_wakeword.py`
neu/geändert). **889/889 Python-Tests, BT.CPP unverändert 23/0/0/4.**

### Commit 2/7 (`f752edb`): add dynamic head-mounted sensor frames

Zweiter, unabhängig gefundener Fund (analog zum
`actuator_arbiter_node`-Launch-Fund aus AP6): `robot_state_publisher`
wurde in `autonomy_ws` nie gestartet, kein Node hat je `/joint_states`
publiziert -- `camera_pose_gate_node.py`/`head_pose_gate.py` konsumieren
das seit Entwicklungsauftrag 1 fail-closed, `head_navigation_pose_valid`
war dadurch vermutlich immer `False`. Neues
`pepper_robot_state.launch.py` (startet `robot_state_publisher` mit
Peppers echtem URDF aus dem SEPARATEN Workspace `ros2/robot_model` --
bewusst wiederverwendet statt eine zweite Kinematik-Quelle anzulegen),
`bridge_node.py::_publish_joint_states()` (neuer `/joint_states`-
Publisher, `HeadYaw`/`HeadPitch`, fail-closed). `realsense_extrinsics.yaml`s
`parent_frame` von `base_link` auf `Head` umgestellt (die Kamera sitzt
tatsächlich am beweglichen Kopf), neues `respeaker_extrinsics.yaml`/
`respeaker_static_tf.launch.py` analog. Die bestehende Navigationssperre
bei abweichender Kopfpose bleibt ausdrücklich bestehen -- kein
automatisches Freischalten der Navigation für Kopfbewegungen. 25 neue
Tests. **914/917 Python-Tests (3 unverändert übersprungen), BT.CPP
unverändert 23/0/0/4.**

### Commit 3/7 (`78c931d`): transform sound rays from ReSpeaker to base frame

Bestätigter Fund 3.1 behoben: der von `audio_node.py` geschätzte Winkel
ist relativ zum Mikrofonarray selbst, wurde aber unverändert als
bereits-in-`base_link`-Winkel weitergereicht. Strikte RAW/kanonische
Topic-Trennung: `audio_node.py` publiziert seither NUR
`/audio/sound_direction_raw` + `/audio/wakeword_event_raw` (immer
`frame_id=respeaker_link`). Neuer `sound_direction_transform_node.py`
ist der EINZIGE Publisher der kanonischen Topics
`/audio/sound_direction` + `/audio/wakeword_event`
(`frame_id=base_link`) -- reine VEKTOR-Transformation
(`tf2_geometry_msgs.do_transform_vector3`, keine Translation) zum
ORIGINALEN Messzeitpunkt. Fail-closed bei leerem/unbekanntem Frame,
fehlender/veralteter/zukünftiger TF, invalider Quaternion,
nicht-endlichem Ergebnis, zu altem Original-Messzeitpunkt. 24 neue
Tests (14 `test_sound_ray_transform.py`, 10
`test_sound_direction_transform_node.py`). **938/941 Python-Tests (3
übersprungen), BT.CPP unverändert 23/0/0/4.**

### Commit 4/7 (`3cf7957`): publish frame-validated audiovisual targets

Zwei bestätigte Funde behoben: (3.5) das Zuordnungsergebnis von
`audiovisual_association_node.py` lag bislang nur im
Service-Antwortformat auf dem BT-Blackboard -- `audio_focus_node.py`
bekam es nie mit. (11) `has_3d_position=True` allein wurde als
ausreichend behandelt, ohne `frame_id`/`source_camera` zu prüfen. Neues
`AudioVisualTarget.msg`, veröffentlicht auf `/audio/visual_target` für
JEDEN Zuordnungsversuch (auch Ablehnungen). `AssociatePersonWithSound.srv`
um ein `event_id`-Feld erweitert, `FindPersonNearSoundRay` (C++)
bekommt einen neuen `wakeword_event_id`-Input-Port.
`audiovisual_association.py` verwirft Tracks in einem anderen
Frame/von einer anderen Kamera jetzt fail-closed
(`required_frame_id`/`required_source_camera`). 10 neue Tests. **948/951
Python-Tests (3 übersprungen), BT.CPP unverändert 23/0/0/4.**

### Commit 5/7 (`1a6da08`): steer conversation audio toward confirmed person

Zwei bestätigte Funde behoben (3.6/3.7): `audio_focus_node.py` steuerte
nie ein Backend tatsächlich an (`selected_track_id` blieb immer `-1`,
Übergang lief über einen `/interaction_state`-Behelf); die
front/back-mehrdeutige GCC-PHAT-Schätzung galt nirgends als unsicher.
`audio_focus_node.py` abonniert jetzt `/audio/visual_target` (echte
Bestätigung) und, während eines bestätigten Fokus,
`/perception_node/person_tracks` (NUR Updates für denselben `track_id`
-- ein anderer/lauterer Sprecher kann nie selbst zum neuen Fokus
werden). Neue `transform_person_position_to_azimuth()` (echte
Punkt-Transformation, Translation UND Rotation) transformiert die
bestätigte Personenposition nach `respeaker_link`.
`SteerableDirectionalAudioBackend`-Schnittstelle (neu) +
`MicrophoneGeometry`: `GccPhatDelayAndSumBackend` implementiert echtes,
geometriebasiertes Delay-and-Sum-Steering auf ein festes,
bestätigtes Ziel (die DoA-Messung selbst bleibt davon unabhängig).
Neues Klassenattribut `provides_unambiguous_direction` (Default
`False`) -- `audio_node.py` setzt `direction_valid` zurück, wenn die
aktive Quelle mehrdeutig ist, außer ein Parameter
`allow_ambiguous_direction_for_head_orientation` (in `production_mode`
hart gesperrt) erlaubt es explizit. 27 neue Tests. **975/978
Python-Tests (3 übersprungen), BT.CPP unverändert 23/0/0/4.**

### Commit 6/7 (`eb33d54`): make wakeword events exactly-once in behavior tree

Bestätigter Fund 3.2 (zweite Hälfte) behoben: `WaitForFreshWakeword`
(C++) gab `measured_at_sec` bislang als `system_clock::now()` aus, nie
den echten Original-Messzeitpunkt -- UND es gab keine
Exactly-once-Sicherung (derselbe `event_id` hätte bei einem erneuten
BT-Tick ein zweites Mal `SUCCESS` auslösen können). Jetzt: akzeptiert
nur Nachrichten mit `frame_id==wakeword_base_frame` (neuer Knoten-
Parameter, Default `base_link`), begrenzter Cache verbrauchter
`event_id`s (FIFO, max. 64), `measured_at_sec` ist der echte
Original-Zeitstempel. Keine neuen Python-Tests (reine C++-/XML-
Änderung) -- **ehrlich dokumentierter Test-Gap**: dieses Projekt deckt
BT-Aktionsknoten dieser Art konsequent nur über Python-ROS-Wrapper-Tests
+ XML-Strukturprüfung ab, kein dediziertes gtest für
`WaitForFreshWakeword` selbst (verifiziert nur durch Code-Review +
grüne Gesamt-BT.CPP-Suite). **975/978 Python-Tests unverändert, BT.CPP
unverändert 23/0/0/4.**

### Commit 7/7 (dieser Commit): add launch validation, regression tests and report

Bestätigter Fund behoben: `audio_node`s `production_mode`-Parameter
wurde in `interaction_full_safe.launch.py` NIE gesetzt (blieb immer
beim Node-internen Default `false`, auch in `mode=production`) -- die
in Commit 1/5 eingeführten Start-Guards hätten in der echten
Produktions-Launch dadurch nie gegriffen. Jetzt nach demselben Muster
wie `gesture_memory_node` verdrahtet. Neue Tests: `test_half_duplex.py`
(7, bisher UNGETESTETES Modul -- die strukturelle Sicherung dafür, dass
Peppers eigene Sprache nie selbst ein Wakeword auslöst), 3 neue
Launch-Struktur-Tests (genau ein `audio_node`/
`sound_direction_transform_node`, Transform-Node läuft in jedem Modus
wie `audio_node`, `production_mode`-Verdrahtung).

### Baseline/Endstand (gemessen)

| | Python-Tests | BT.CPP |
|---|---|---|
| Vor AP6.1 | 870/870 | 23/0/0/4 |
| Nach AP6.1 | 985/988 (3 unverändert übersprungen) | 23/0/0/4 (unverändert -- siehe Commit 6 für den Grund) |

### Raw-/kanonische Topics (Abschnitt 4/12)

| Topic | frame_id | Publisher |
|---|---|---|
| `/audio/sound_direction_raw` | `respeaker_link` | `audio_node.py` (einzig) |
| `/audio/wakeword_event_raw` | `respeaker_link` | `audio_node.py` (einzig) |
| `/audio/sound_direction` (kanonisch) | `base_link` | `sound_direction_transform_node.py` (einzig) |
| `/audio/wakeword_event` (kanonisch) | `base_link` | `sound_direction_transform_node.py` (einzig) |
| `/audio/visual_target` | -- (kein Frame-Feld, Winkel bereits `base_link`-relativ) | `audiovisual_association_node.py` (einzig) |
| `/audio/focus_state` | -- (`target_azimuth_rad` ist `respeaker_link`-relativ) | `audio_focus_node.py` (einzig) |

### Volle TF-Kette (dynamisch, Abschnitt 6)

```
map -> odom -> base_link -> torso -> Neck -> Head
                                        |
                                        +-> realsense_mount_link -> camera_link (RealSense-Treiber ab hier)
                                        +-> respeaker_link (ReSpeaker-Mikrofonarray)
```

`base_link -> torso` fest (URDF), `torso -> Neck` trägt `HeadYaw`,
`Neck -> Head` trägt `HeadPitch` (aus `pepper_description`, separater
Workspace `ros2/robot_model` -- Sourcing-Voraussetzung dokumentiert in
`pepper_robot_state.launch.py`). `Head -> realsense_mount_link`/
`Head -> respeaker_link` starr (Montagepunkte, Werte Platzhalter).
`map -> odom` aus RTAB-Map-Lokalisierung (AP5), `odom -> base_link` aus
RTAB-Map-Odometrie (AP4) -- unverändert seit Auftrag 2.

### Timestamp-Erhaltung -- Nachweis

`audio_node.py::_try_wakeword_activation()` verwendet
`direction_sample.ros_stamp_ns` (den ECHTEN Messzeitpunkt aus dem
Puffer) für `WakewordEvent.header.stamp`, niemals
`self.get_clock().now()` im Erfolgsfall (siehe
`test_handle_utterance_carries_direction_sample_into_event`).
`sound_direction_transform_node.py` übernimmt `msg.header.stamp`
unverändert in die kanonische Ausgabe (siehe
`test_canonical_output_preserves_original_timestamp`). `WaitForFreshWakeword`
(C++) berechnet `measured_at_sec` seit Commit 6 aus
`header.stamp.sec`/`.nanosec`, nicht mehr aus `system_clock::now()`.

### Fehlende TF / fehlendes Wakeword-Modell -- Verhalten

Fehlende/veraltete/zukünftige TF: `transform_direction()`/
`transform_person_position_to_azimuth()` geben `valid=False`/`None`
zurück, NIE einen erfundenen Winkel (siehe `test_sound_ray_transform.py`/
`test_audio_focus_node.py`). Fehlendes Wakeword-Modell:
`activation_mode=wakeword_required` ohne geladenes Modell verarbeitet
NIE eine Äußerung (siehe `test_wakeword_required_without_model_never_processes`,
AP6.1 Commit 1) -- kein Fail-Open mehr.

### Exactly-once-Verarbeitung / echte Track-ID-Weitergabe / echtes Steering

Siehe Commits 6, 4 bzw. 5 oben für die jeweilige Implementierung und
Testabdeckung. Kurzfassung: ein `event_id` löst höchstens einen
Ausrichtungsversuch aus (begrenzter Cache in `WaitForFreshWakeword`);
`audio_focus_node.py`s `selected_track_id` ist seit Commit 4/5 der
ECHTE, von `audiovisual_association_node.py` bestätigte Track (nicht
mehr immer `-1`); `GccPhatDelayAndSumBackend` steuert das
Ausgangssignal seit Commit 5 tatsächlich auf ein bestätigtes Ziel,
sofern eine Kanalgeometrie konfiguriert ist (Default: keine, daher
unverändertes altes Verhalten).

### Front/Back-Ambiguität -- Status

Weiterhin ungelöst (Auftrag erlaubt das, verlangt nur die Kennzeichnung):
`GccPhatDelayAndSumBackend.provides_unambiguous_direction = False`.
`audio_node.py` verweigert eine darauf gestützte Kopfbewegung per
Default (`allow_ambiguous_direction_for_head_orientation=false`), in
`production_mode=true` unübersteuerbar gesperrt. Für eine echte
360-Grad-Auflösung bräuchte es mehrere kombinierte Mikrofonpaare
(nicht implementiert) oder die Herstellerbibliothek
(`ReSpeakerVendorBackend`, weiterhin `NotImplementedError`).

### Ehrlicher Stand / bekannte Lücken

- Alle fünf Hardwaretestphasen (A-E) weiterhin NICHT durchgeführt --
  kein ReSpeaker Core v2.0/RealSense/Pepper-Kopf in dieser Session real
  angesprochen, siehe `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`.
- `respeaker_extrinsics.yaml`/`realsense_extrinsics.yaml` bleiben
  Platzhalter (`is_calibrated: false`) -- keine echte Vermessung.
  `respeaker_mic_geometry_channels`/`_x_m`/`_y_m` bleiben in jeder
  Launch-Konfiguration leer -- echtes Beamforming-Steering nur gegen
  synthetische Testsignale verifiziert, nicht gegen echte Hardware.
- Front/back-Mehrdeutigkeit der Zwei-Mikrofon-Schätzung bleibt bestehen
  (siehe oben) -- eine korrekte TF-Kette macht eine mehrdeutige Messung
  nicht eindeutig.
- Die Keepout-Zonen-Prüfung in der audiovisuellen Zuordnung bleibt
  unverdrahtet (unverändert seit AP6, siehe
  `docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md`).
- `WaitForFreshWakeword`s Exactly-once-/Frame-Gate-Logik ist NICHT per
  gtest abgedeckt (siehe Commit 6 oben).
- Kein AEC implementiert (unverändert seit AP6, Auftrag erlaubt das
  ausdrücklich).
- Kein `/cmd_vel`-Zugriff, keine Nav2-Live-Fahrt, kein
  `navigation_live.launch.py` in irgendeinem Commit dieses
  Arbeitspakets -- durchgängig per Grep gegen jeden geänderten/neuen
  Code geprüft.
- Working Tree nach Abschluss dieses Arbeitspakets sauber, 7 klar
  abgegrenzte Commits, kein Push/PR ohne expliziten Wunsch.

### Empfehlung für AP7

Alle 7 in Auftrag AP6.1 benannten bestätigten Lücken sind geschlossen.
Vor AP7 (weitere Gesten) oder Hardware-Phase B-E: eine echte
ReSpeaker-Core-v2.0-Einheit + Pepper-Kopfzugriff beschaffen, um Phase A
(Kalibrierung nach `docs/RESPEAKER_CALIBRATION.md`) tatsächlich
durchzuführen -- ohne echte Extrinsics/Kanalgeometrie bleibt jede
TF-Transformation/jedes Steering nur gegen synthetische Daten
verifiziert. Unabhängig von Hardware: ein dediziertes C++-Testgerüst
für `WaitForFreshWakeword` (exactly-once, frame_id-Gate) wäre die
naheliegende nächste Verbesserung der Testabdeckung selbst. Aus dem
ursprünglichen Gesamtplan weiterhin offen: AP13 (ID-Trennung + echte
Retriever-Anbindung verifizieren), AP8 (weitere kinematisch entwickelte
Gesten), AP14 (Emotion-Gating). Die endgültige Priorisierung bleibt
beim Auftraggeber.

## AP7: Rollen, Codewörter, Gruppengespräche, sicheres Personenfolgen und vollständiger Interaktionslebenszyklus

Umgesetzt in 11 Commits auf demselben Branch
(`order-04b-kiconnect-gesture-memory-lifecycle-audio`), direkt auf dem
AP6.1-Abschluss-Commit (`f20abe4`) aufbauend -- Baseline davor
verifiziert (985/988 Python-Tests, BT.CPP 23/0/0/4). Größtes
Arbeitspaket bisher:
neuer Rollenbegriff (STUDENT/EMPLOYEE/ADMIN, ausschließlich per
lokalem `peoplectl`-CLI setzbar), strikt getrennte transiente/
einwilligungsgebundene Gesichtsidentität, ein deterministischer
Codewort-/Autorisierungs-Router, stabile Mehrpersonen-Gruppenverfolgung
mit sicherer Beobachtungspose und gruppenbewusster Richtmikrofonie,
eine ECHTE autorisierte `FollowPerson`-Implementierung (ersetzt den
bisherigen, nie fahrenden Stub), Ursprungspose-Erfassung +
`ReturnToOrigin`, und die Einbettung all dessen in den Behavior Tree.

### Commit 1/11 (`fc935b0`): define roles, commands, groups and lifecycle contracts

Neue Nachrichten (`PersonIdentity(Array)`, `InteractionCommand`,
`AuthorizationGrant`, `ConversationGroup(Array)`,
`InteractionLifecycleState` -- 16 Zustände IDLE..ERROR), neue Action
`ReturnToOrigin`, `FollowPerson.action` um `authorization_grant_id`/
`session_id`/`desired_follow_distance_m`/`max_duration_s`/
`max_track_loss_timeout_s`/`return_to_origin_after_end` erweitert.
Neue reine Python-Module: `ihk_pepper_interaction/roles.py`
(`ROLE_STUDENT/EMPLOYEE/ADMIN`, `role_at_least()`, fail-closed auf
STUDENT), `authorization_policy.py` (`POLICY_DISABLED/
ROLE_PLUS_CONFIRMATION/ROLE_ONLY_DEVELOPMENT`, Letzteres in
`production_mode=true` hart gesperrt), `codeword_config.py`
("Eisenbahn"→interrupt_and_look, "Pepper komm mal mit"→follow_speaker,
Codewörter aus einer festen `VALID_COMMANDS`-Allowlist, niemals frei
aus YAML), `interaction_lifecycle_state.py`. Tests: 49 neue.

### Commit 2/11 (`6e92545`): add audited role storage and local peoplectl management

`identity_registry_db.py` um `role`/`role_assigned_at_iso`/
`role_assigned_by`/`role_valid_until_iso`-Spalten erweitert (idempotente
Migration mit Backup bei vorhandenen Zeilen), `set_role()`/
`revoke_role()`/`get_effective_role()`/`list_all()`/`audit_log_for()`.
Neues `peoplectl.py` (argparse-CLI: `list/show/set-role/revoke-role/
delete`, `--reason` bei jedem Schreibzugriff Pflicht, `--yes` für
`delete`) -- **die einzige Stelle im gesamten System, die eine Rolle
setzen kann**. Kein ROS2-Service, kein LLM-Pfad kann eine Rolle
ändern -- strukturell durchgesetzt (kein Service dafür existiert).
Tests: 18 neue.

### Commit 3/11 (`0a93271`): implement consent-gated face identity backends

Neues Paket `ihk_pepper_identity`: `face_identity_backend.py`
(`FaceIdentityBackend`-ABC mit strikt getrennten `observe_transient()`
vs. `identify_persistent()`, `DisabledIdentityBackend`,
`MockIdentityBackend`, `LocalOnnxIdentityBackend` -- fail-closed bei
fehlendem Modell), `liveness.py` (Tiefenvarianz-Heuristik gegen
Foto-/Bildschirm-Spoofing), `identity_matching.py` (Kosinus-Ähnlichkeit
+ Mehrdeutigkeits-Ablehnung), `persistent_identity_confirmer.py`
(Mehrbild-Bestätigung pro Track), `biometric_template_store.py`
(separater, Fernet-verschlüsselter Speicher, 0600-Rechte,
ausschließlich über `person_id` referenziert -- NIE in der
Identitäts-/Vektordatenbank/LLM-Pipeline). Tests: 48 neue, alle ohne
Skip (echte ONNX-Inferenz selbst bleibt ehrlich ungetestet -- kein
`onnx`-Paket zum Selbstbauen eines Testmodells verfügbar, nur der
fail-closed-Konstruktionspfad + die reinen Geometrie-Hilfsfunktionen
sind abgedeckt).

### Commit 4/11 (`d7a9e69`): add deterministic codeword and privileged command router

`audio_node.py`: Codewörter laufen jetzt durch dieselbe Roh-/kanonische-
Topic-Pipeline wie `WakewordEvent` (`/interaction/command_raw` →
`sound_direction_transform_node.py` → `/interaction/command`).
`_conversation_confirmed_active()` (fail-closed) ergänzt neben dem
bereits bestehenden, bewusst gegenteilig fail-offenen
`_conversation_active_for_gate()` -- behebt einen Bug, bei dem ein
Codewort während eines laufenden Gesprächs die Sitzung nicht verlängerte.
Neu: `command_priority.py` (feste Priorität: Not-Halt >
Stopp-/Abbruch-Codewörter > Codewort-Unterbrechung > privilegierte
Sprachbewegung > Dialogtext), `command_authorization_decision.py`
(prüft `roles.py`s festes Rollen-Tabelle -- bewusst NICHT zusätzlich
das YAML-`required_role`-Feld, um eine sicherheitskritische Grenze
nicht allein YAML-editierbar zu machen), `command_router_node.py`.
Tests: 43 neue.

### Commit 5/11 (`9d633fc`): implement stable conversation group tracking

Neues `ihk_pepper_perception/group_tracking.py`: Single-Linkage-
transitives Clustering (Union-Find) über `person_tracks`, Beitritts-/
Austritts-Hysterese gebunden an den AKTUELLEN Interaktionspartner
(nie eine zufällige vorbeigehende Person). Zwei echte Bugs beim
Testschreiben gefunden und behoben: (1) `_reset()` löschte
Beitritts-Fortschritt auch VOR der ersten Gruppenbildung, (2)
Austritts-Hysterese maß "Zeit seit ERSTMALS vermisst" statt "Zeit seit
ZULETZT gesehen" -- bei unregelmäßigen Update-Intervallen fälschlich
sofort erfüllt. Beide durch dedizierte Regressionstests abgedeckt.
Neuer `group_tracking_node.py` veröffentlicht
`/perception/conversation_groups`. Tests: 31 neue.

### Commit 6/11 (`7d38ca7`): plan safe group observation poses

Neues `ihk_pepper_navigation/group_observation_pose.py`: geschlossene
tangentenbasierte Geometrie (`required_distance = spread_radius /
tan(fov/2)`) statt iterativer Suche. Prüft: zu wenige Mitglieder,
Gruppe zu breit fürs Fahrbudget, Fahrdistanz überschritten,
Mindestabstand zum NÄCHSTEN Mitglied (nicht nur zum Zentrum),
Keepout-Zonen, optionale Costmap. Ein erster Entwurf lehnte
"Rückwärtsfahren relativ zur aktuellen Ausrichtung" fälschlich ab --
ein Test deckte auf, dass das eine gültige, weit entfernte Zielpose
(Rotation-dann-Vorwärtsfahrt, kein echtes Rückwärtsfahren) traf; die
Prüfung wurde vollständig entfernt und die Designentscheidung im
Moduldocstring festgehalten. Tests: 15 neue.

### Commit 7/11 (`d79802b`): connect active group speakers to directional audio focus

Neues `ihk_pepper_audio/group_speaker_selection.py`
(`ActiveSpeakerSelector`, Mehrdeutigkeits-/Bestätigungs-Hysterese).
`audio_focus_node.py` wird gruppenbewusst: GROUP_WIDE (auf
Gruppenzentrum steuern) vs. ACTIVE_SPEAKER (auf den bestätigten aktiven
Sprecher INNERHALB der bestätigten Gruppe steuern). Wichtige
Sicherheitseigenschaft (per Test nachgewiesen): `audio_focus.py`s
`selected_track_id` (Sitzungsidentität) wird NIE geändert -- nur der
an `on_target_track_update()` übergebene Azimut-WERT ändert sich,
womit die bestehende Fremdtrack-Ablehnungsgarantie aus AP6.1 erhalten
bleibt. Tests: 16 neue.

### Commit 8/11 (`6928b6f`): implement authorized dynamic FollowPerson with Nav2 mocks

Ersetzt den bisherigen `FollowPerson`-Stub (fuhr NIE, nur
`sleep(0.5)`-Schleife) durch eine echte Umsetzung.
`authorization_grant_cache.py` (lokaler Cache der von
`command_router_node.py` auf `/authorization/grants` ausgestellten
Berechtigungen, einmalige Verwendung), `follow_person_safety.py` (13
Bedingungen in fester Reihenfolge + Akku-Schwelle + Crowd-Geometrie).
`person_approach_node.py::_execute_follow()`: validiert den
Autorisierungs-Grant, prüft vor JEDEM Fahrsegment erneut alle
Sicherheitsbedingungen, berechnet über das bestehende
`compute_approach_pose()` eine Gesprächs-Zielpose VOR der Person (nie
die Person selbst als Ziel), fährt über die bestehende
`_drive_to_pose()` (BASE-Lease unverändert wiederverwendet), plant NUR
bei relevanter Personenbewegung neu (Positions- UND
Winkeländerungsschwelle), NIE automatische Basisrotation bei
Trackverlust (bewusst nicht Teil dieses Commits, ehrlich offen).
Randfund: vier `package.xml` (`ihk_pepper_bridge`, `ihk_pepper_identity`,
`ihk_pepper_navigation`, `ihk_pepper_person_memory`) enthielten je einen
XML-Kommentar mit `--` (laut XML-Spezifikation in Kommentaren
verboten) -- dieselbe wiederkehrende Falle wie zuvor in BT-XML (Auftrag
1-3), hier erstmals in `package.xml` angetroffen. Colcon stufte die
betroffenen Pakete dadurch stillschweigend als generisches `python`
statt `ament_python` ein (kein Fehler, kein Build-Abbruch -- nur ein
fehlender `AMENT_PREFIX_PATH`-Eintrag), wodurch
`get_package_share_directory()` für diese Pakete fehlschlug und die
GESAMTE pytest-Sammlung abbrach. Alle vier Stellen korrigiert, mit
`xml.etree.ElementTree` über jede `package.xml`/`*.xml` im Repo erneut
geprüft. Tests: 47 neue (4 `command_router_node.py`-Ergänzung, 9
`authorization_grant_cache.py`, 17 `follow_person_safety.py`, 17
`person_approach_node`-FollowPerson-Ausführung).

### Commit 9/11 (`4b68ae3`): capture session origin and implement ReturnToOrigin

Neuer Service `CaptureOrigin.srv` + `origin_session.py`
(`OriginStore` -- ausschließlich im Prozessspeicher, kein Persistieren
über einen Neustart hinaus). `person_approach_node.py`: neue
`_get_robot_pose_in_frame()` (Position + Blickrichtung, ersetzt/erweitert
die bisherige positionsonly Methode), `_on_capture_origin()`-Service
(lehnt während laufender Kartierung ab), `_execute_return_to_origin()`-
Action (validiert Ursprung + Sicherheit VOR und WÄHREND der gesamten
Fahrt, fährt ausschließlich über die bestehende `_drive_to_pose()`).
Zwei neue Invalidierungs-Trigger (`_on_mapping_active()`, erweitertes
`_on_safety_state()`): ein False→True-Übergang bei Kartierung ODER
Lokalisierung verwirft ALLE gespeicherten Urspünge global -- ein
Kartenwechsel/eine Neuinitialisierung macht jede gespeicherte Pose
potenziell ungültig. `return_to_origin_safety.py` (9 Bedingungen,
gleiches Muster wie `follow_person_safety.py`, ohne
personenspezifische Felder, mit `mapping_active`). Tests: 35 neue (9
`origin_session.py`, 10 `return_to_origin_safety.py`, 4
Invalidierungs-Trigger, 12 `_execute_return_to_origin`/
`_on_capture_origin`-Ausführung).

### Commit 10/11 (`5c791ff`): integrate PersonInteractionLifecycleSubtree into the tree

Reiner C++/XML-Commit, keine Python-Änderung. Drei neue BT.CPP-Knoten
(`CaptureOriginPose`, `ReturnToOriginViaBT`, `ClearSession`), exakt nach
bestehenden Vorlagen (`FindPersonNearSoundRay` für den reinen
Service-Aufruf, `ApproachSelectedPerson`/`RunDialogueViaBT` für den
Action-Client mit begrenzter Cancel-Bestätigung). `pepper_main.xml`:
`CaptureOriginPose` NEU vor `ApproachSelectedPerson` in
`GreetAndApproachSubtree` eingefügt; `DialogueSubtree` bekommt nach
`RunDialogueViaBT` einen neuen `EndInteractionSubtree`
(Verabschiedungsgeste `goodbye_wave` → `ReturnToOriginViaBT` →
`ClearSelectedPerson` → `ClearSession` → `SetInteractionState IDLE`),
selbst in einen äußeren Fallback mit `AlwaysSuccessIdle` gehüllt, damit
ein fehlgeschlagenes `ReturnToOriginViaBT` NIE zu einer Endlosschleife
wiederholter Gesprächsversuche mit derselben, bereits verabschiedeten
Person führt. Neuer `PersonInteractionLifecycleSubtree`
(`ReactiveFallback` um `GreetAndApproachSubtree` + `DialogueSubtree`)
ersetzt die bisherigen zwei getrennten Root-Einträge durch einen
benannten -- funktional identisch (verschachtelte Fallbacks verhalten
sich wie flache), macht den vollständigen Lebenszyklus aber als EIN
Konzept sichtbar. `bt_executor_node` manuell 4s laufen lassen: Baum
lädt fehlerfrei, alle drei neuen Knotentypen werden von der Factory
aufgelöst, sauberes Herunterfahren per SIGTERM. `colcon test-result
--all`: weiterhin 23/0/0/4 (unverändert -- gleiche Anzahl geprüfter
Dateien, keine neue gtest-Datei).

### Commit 11/11 (dieser Commit): add launch modes, regression tests and documentation

Vier neue, rein softwarebasierte Testmodi in
`interaction_full_safe.launch.py` (`role_authorization_offline_test`,
`group_interaction_offline_test`, `follow_person_dry_run`,
`interaction_lifecycle_dry_run`) -- alle wie `offline_test`
(`mock_nav2_server`, kein echter Pepper/keine echte Kamera, Bridge
`dry_run`). Neu gestartet: `command_router_node` (überall dort, wo
Audio aktiv ist -- dieselbe Bedingung wie `audio_node`),
`group_tracking_node` (überall dort, wo Perception aktiv ist).
`enable_follow_person:=true` NUR in `follow_person_dry_run`. Alle vier
Modi real per `ros2 launch --show-args` und einem echten, zeitbegrenzten
Start verifiziert (keine unerwarteten Exceptions/Tracebacks; die
einzige geloggte Fehlermeldung ist die bereits vor AP7 bestehende,
umgebungsbedingte `PortAudio library not found`, kein echtes Mikrofon
in dieser Sandbox). 6 neue Tests in
`test_interaction_full_safe_launch.py` (u.a.: `command_router_node`
läuft überall dort, wo `audio_node` läuft; `group_tracking_node`
überall dort, wo `perception_node` läuft;
`enable_follow_person` ist ausschließlich in `follow_person_dry_run`
wahr; keiner der vier neuen Modi erreicht jemals den echten
`nav2_bringup.launch.py`-Einschluss). Dokumentation: neue
`docs/PERSON_ROLES_AND_AUTHORIZATION.md`,
`docs/FACE_IDENTITY_AND_PRIVACY.md`,
`docs/PRIVILEGED_VOICE_COMMANDS.md`, `docs/GROUP_CONVERSATION.md`,
`docs/FOLLOW_PERSON_RUNTIME.md`, `docs/INTERACTION_LIFECYCLE.md`,
`docs/RETURN_TO_ORIGIN.md`, `docs/AP7_HARDWARE_TEST_CHECKLIST.md`;
Ergänzungen in `README.md`, `docs/STATUS.md`, `docs/BEHAVIOR_TREE.md`,
`docs/PERSON_MEMORY_DESIGN.md`, `docs/PERSON_MEMORY_RUNTIME.md`,
`docs/AUDIO_FOCUS_AND_BEAMFORMING.md`, `docs/ACTION_CANCELLATION.md`.

### Testzusammenfassung

| Zeitpunkt | Python-Tests | BT.CPP |
|---|---|---|
| Baseline vor AP7 (`f20abe4`) | 985 passed, 3 skipped | BT.CPP 23/0/0/4 |
| Nach Commit 7/11 | 1205 passed, 3 skipped | unverändert |
| Nach Commit 8/11 | 1255 passed, 3 skipped | unverändert |
| Nach Commit 9/11 | 1291 passed, 3 skipped | unverändert |
| Nach Commit 10/11 | 1291 passed, 3 skipped (reiner C++/XML-Commit) | BT.CPP 23/0/0/4, `bt_executor_node` lädt/tickt/beendet sauber |
| Nach Commit 11/11 (Endstand) | **1297 passed, 3 skipped** | unverändert, 23/0/0/4 |

Netto +312 Tests über alle 11 Commits. Grep auf `/cmd_vel` nach JEDEM
einzelnen Commit gegen ausschließlich die in diesem Commit geänderten/
neuen Dateien durchgeführt -- kein Treffer außer dokumentierenden
Kommentaren/Tests, die die Abwesenheit prüfen. `navigation_live.launch.py`
in keinem Commit berührt/gestartet.

### Ehrlicher Stand / bekannde Lücken (gegen Auftrag Abschnitt 30-32)

**Hardware-unverifiziert (ausschließlich Mock-/Duck-Typing-/Dry-Run-
getestet, wie vom Auftrag ausdrücklich verlangt zu kennzeichnen):**

- **Gesichtserkennung**: `LocalOnnxIdentityBackend`s tatsächliche
  ONNX-Inferenz ist NICHT getestet (kein passendes Testmodell in dieser
  Session baubar, kein `onnx`-Paket verfügbar) -- nur der
  fail-closed-Konstruktionspfad (fehlendes/leeres/ungültiges
  Modell-Argument) und die reinen Geometrie-Hilfsfunktionen sind
  abgedeckt. Es existiert außerdem noch KEIN ROS2-Node, der
  `ihk_pepper_identity` tatsächlich instanziiert und
  `PersonIdentityArray` veröffentlicht -- das Paket ist ein fertiges,
  getestetes Backend OHNE Laufzeit-Anbindung. `command_router_node.py`
  und `group_tracking_node.py` funktionieren strukturell unabhängig
  davon (fail-closed auf "keine Identität bekannt"/STUDENT-Rolle), aber
  das ist noch nicht end-to-end mit echten Gesichtsdaten verifiziert.
- **Bewegung**: `FollowPerson`/`ReturnToOrigin` sind ausschließlich
  gegen Duck-Typing-Fakes (kein echtes Nav2, kein echter Pepper)
  getestet. Kein `enable_follow_person=true`/`enable_person_approach`-
  Lauf gegen echte Hardware in dieser Session.
- **Sprecherzuordnung**: `ActiveSpeakerSelector`/gruppenbewusstes
  Audio-Steering ausschließlich gegen synthetische DOA-/Track-Daten
  getestet (kein echter ReSpeaker, unverändert seit AP6/AP6.1).
- **Rückkehr**: `ReturnToOrigin` ausschließlich gegen einen
  Fake-TF-Buffer/Fake-Nav2-Client getestet, keine echte TF-Kette/kein
  echtes Nav2.

**Bewusst nicht Teil von AP7 (ehrlich offen, siehe Commit-Nachrichten):**

- Kein Kopf-Suchverhalten und keine automatische Basisrotation bei
  Personen-/Gruppenverlust (Auftrag verlangt genau das NICHT
  automatisch) -- FollowPerson bricht bei Trackverlust sauber ab, ohne
  jede Art von Nachsuche.
- Codewort-/Rollen-/Gruppen-Routing ist NICHT in den Behavior Tree
  verdrahtet -- `command_router_node.py`/`group_tracking_node.py`/
  `FollowPerson` bleiben eigenständige, einzeln getestete
  Python-Fähigkeiten außerhalb des Baums. Die volle Abschnitt-23-
  Prioritätskette (Codewort-Unterbrechung vor Follow/Return vor
  laufendem Gespräch) und Abschnitt-24-Gruppenverlust-Behandlung
  (`MonitorParticipants`, `GROUP_LOST`) sind nicht im Baum umgesetzt.
- Kein neuer BT-Knoten ruft `command_router_node`/`group_tracking_node`
  überhaupt auf -- diese laufen als eigenständige ROS2-Nodes parallel
  zum Baum, ohne dass der Baum ihre Ausgaben (Grants, Gruppen) aktuell
  selbst konsumiert (nur `audio_focus_node.py`/`person_approach_node.py`
  tun das bereits direkt).
- `person_id`/`group_id` bleiben in `CaptureOriginPose` leer -- keine
  Rollen-/Gruppen-Bindung der Ursprungspose an eine bestimmte Person.
- Biometrische Vorlagen (`biometric_template_store.py`) sind fertig und
  getestet, aber von KEINEM Laufzeitpfad tatsächlich befüllt (kein
  Identity-Node, siehe oben).

Working Tree nach Abschluss dieses Arbeitspakets sauber, 11 klar
abgegrenzte Commits, kein Push/PR ohne expliziten Wunsch.

### Empfehlung für das nächste Arbeitspaket

Die softwareseitige Rollen-/Codewort-/Gruppen-/Follow-/
Ursprungs-Infrastruktur ist vollständig, einzeln getestet und
launch-integriert -- die größte verbleibende Lücke ist die
BT-seitige ORCHESTRIERUNG (Abschnitt 23/24/25 der vollen
Prioritätskette) sowie ein tatsächlicher Identity-Node, der
`ihk_pepper_identity` mit echten Gesichtsdaten verbindet. Empfohlene
Reihenfolge für das nächste Arbeitspaket: (1) ein `identity_node.py`
in `ihk_pepper_identity`, der `PersonIdentityArray` aus echten
RealSense-Bilddaten veröffentlicht (aktuell nur Bibliothek ohne Node);
(2) `command_router_node`/`group_tracking_node` tatsächlich in den
Behavior Tree einbinden (neue BT-Knoten für Codewort-Konsum,
Gruppenpositionierung, `MonitorParticipants`); (3) die volle
Abschnitt-23-Prioritätskette im Baum nachbilden. Unabhängig von
Hardware: eine echte ReSpeaker-Core-v2.0-Einheit + Pepper mit
freigegebener Bewegung bleibt Voraussetzung für JEDE
Hardware-Verifikation von FollowPerson/ReturnToOrigin/Gesichtserkennung
-- ohne das bleiben alle drei bei "gegen Mocks getestet, nicht
hardware-verifiziert" stehen, wie in diesem Bericht durchgängig
gekennzeichnet. Die endgültige Priorisierung bleibt beim Auftraggeber.
