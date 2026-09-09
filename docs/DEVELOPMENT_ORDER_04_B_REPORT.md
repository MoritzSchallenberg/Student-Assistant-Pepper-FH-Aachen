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
