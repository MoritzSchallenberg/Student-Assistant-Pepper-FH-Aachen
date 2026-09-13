# AP8-R3: verbleibende Sicherheitslücken und Laufzeit-Härtung

Stand: 2026-09-13. Entwicklungsauftrag 04-B, AP8-R3. Ausgangsstand:
Branch `order-04b-kiconnect-gesture-memory-lifecycle-audio`, HEAD
`200a97b`. Siehe auch `docs/DIALOGUE_GESTURE_LIFECYCLE.md` (Abschnitt
10 dokumentiert die vorherigen AP8.9-Nachbesserungen, worauf dieser
Auftrag aufbaut), `docs/ACTION_CANCELLATION.md`,
`docs/AP8_RUNTIME_PERFORMANCE.md` (Benchmarks/Optimierungen, Abschnitt
8/9 dieses Auftrags).

## 1. Bestätigte und geschlossene Softwarelücken

### 1.1 Action-Ausführungsregistry (Abschnitt 3)

**Fund**: `_send_goal_and_wait()`s vorherige Kombination aus Handle-
Attribut + Call-Token-Dict + einem SET von Attributnamen
(`_unconfirmed_action_attrs`) konnte mehrere Ausführungen DESSELBEN
Kanals nicht per Identität unterscheiden -- nur per gemeinsamem
Namen. Reproduziert exakt wie im Auftrag beschrieben: Aufruf A läuft,
Aufruf B desselben Kanals startet, B erreicht sein eigenes Timeout und
wird unbestätigt markiert, As später eintreffendes Ergebnis löscht
(über denselben Attributnamen) Bs Markierung, obwohl B weiterhin kein
terminales Ergebnis hat.

**Fix**: `_ActionExecutionRecord`-Dataclass + eine kleine, unter
`_action_registry_lock` geschützte Registry (`channel -> Record`).
Jede Mutation prüft `self._action_registry.get(channel) is record`
(Objektidentität, nicht Name) -- ein alter/fremder Callback kann
strukturell nur seinen EIGENEN Datensatz verändern. Registrierung
erfolgt atomar VOR dem asynchronen Senden (Prüfen+Reservieren unter
demselben Lock) -- verhindert konkurrierende Ausführungen desselben
Kanals bereits vor dem Start. Ausstehende Goal-Annahme wird
nachverfolgt (`pending_acceptance`); nach einem bereits gestellten
Cancel wird ein verspätet angenommenes Ziel kontrolliert nachträglich
storniert (`cancel_requested`); ein fehlgeschlagener RPC wird als
terminal (mit `terminal_success=False`) gewertet, beweist aber kein
Transportende; doppeltes Result/Cleanup ist idempotent (Ownership-
Prüfung bei jeder Mutation).

**Nicht angetastet**: die parallele Say-/Gesture-Ausführung eines
Segments (`with_segment_start` in `ResponsePlanExecutor`) bleibt
unverändert möglich -- die Registry ist pro KANAL ("say"/"gesture"),
nicht global, zwei verschiedene Kanäle laufen weiterhin unabhängig
parallel.

### 1.2 Monotone Freshness (Abschnitt 4)

**Fund**: `_on_tracks()`/`_track_alive()`/`_on_safety_state()`/
`_safety_ok()`/`_runtime_gesture_context()` verglichen bisher gegen
`time.time()` (Wanduhr). Reproduziert: Empfang bei Wanduhr 100, Prüfung
bei 111 (veraltet, `MAX_TRACK_AGE_S=2.0`), Wanduhr springt auf 99
zurück -- derselbe Track gilt wieder als frisch.

**Fix**: `time.monotonic()` für ALLE rein lokalen Altersvergleiche in
diesen fünf Methoden. Bewusst NICHT global ersetzt:
`safety_topics.FreshBool`/`FreshValue` selbst bleiben unverändert (die
Klassen sind uhr-agnostisch -- nur der Aufrufer legt die Uhr fest;
diese Datei ist eine ABSICHTLICH byte-identische Kopie in drei Paketen,
siehe deren eigener Docstring -- eine Änderung dort wäre eine breitere,
separat zu verifizierende Arbeit außerhalb dieses Dateiumfangs). ROS-
Zeitstempel (`ds.header.stamp`) und Datenbank-Ablaufdaten
(`valid_until_iso`) bleiben bewusst auf Wanduhrzeit (siehe Abschnitt
"Zeitdomänen" unten).

### 1.3 Vertrauenswürdige Personen-ID (Abschnitt 6)

**Fund**: `_load_person_context()`/`_write_memory_summary()` reichten
`session_id` bisher UNMITTELBAR als `person_id` an die Memory-Services
weiter (`req.person_id == req.session_id == session_id`) --
`session_id`/`track_id` sind aber nur für die Dauer der Sichtbarkeit
gültig, niemals eine dauerhafte Personen-ID.

**Fix**: neue `_resolve_persistent_person_id()` nutzt die bestehende,
vertrauenswürdige AP7-Zuordnung (`/identity/person_identities`, von
`identity_frame_processor.py` NUR nach mehrfach bestätigtem
Gesichtsabgleich + Liveness-Prüfung + Einwilligung veröffentlicht,
siehe `PersonIdentity.msg`). Liefert die dauerhafte `person_id` NUR,
wenn `session_id` ein gültiger `track_id` ist, ein FRISCHER
(`PERSON_IDENTITY_MAX_AGE_S=3.0`) Eintrag existiert, UND
`known`+`consent_granted` beide `true` sind. Ohne eine so aufgelöste
`person_id` wird kein persönliches Memory mehr gelesen ODER
geschrieben. Zusätzlicher Recheck unmittelbar vor dem Schreiben selbst
(nicht nur der zu Rundenbeginn geladene `person_context`).

### 1.4 Vollständige Dialog-Unterbrechung (Abschnitt 6)

**Fund**: die drei Wartephasen (Frage-Wartephase, Bestätigung/Pipeline/
Denkschleife, Antwortausführung) prüften jeweils NUR
`goal_handle.is_cancel_requested` -- ein Safety-/Personenverlust
während dieser Phasen wurde erst am nächsten Schleifenanfang bemerkt.
Zusätzlich bestätigt: ein Cancel während der Frage-Wartephase wurde
bisher fälschlich wie ein `QUESTION_TIMEOUT` behandelt
(`goal_handle.succeed()` statt `goal_handle.canceled()`).

**Fix**: neue `_dialogue_abort_requested(goal_handle, track_id)` als
EINE gemeinsame Prüfung (Cancel ODER Safety-Verlust ODER
Personenverlust) statt separater, auseinanderlaufender Kopien in jeder
Phase. `_wait_for_question()` gibt jetzt `"__ABORT__"` zurück (statt
`None`), wenn ein Abbruch (nicht ein echter Timeout) vorliegt -- der
Aufrufer springt dann zur Schleifenspitze zurück, die den TATSÄCHLICHEN
Grund korrekt klassifiziert, statt einen falschen `QUESTION_TIMEOUT`
vorzutäuschen. `_acknowledge_and_run_pipeline()`s Wartezyklus und
`_execute()`s Exec-Wartezyklus nutzen dieselbe Prüfung.

## 2. Zeitdomänen (explizite Trennung, Abschnitt 4)

| Domäne | Uhr | Verwendung |
|---|---|---|
| lokales Empfangsalter/Timeout | `time.monotonic()` | `_track_alive()`, `_safety_ok()`, `_runtime_gesture_context()`, alle internen Deadlines (bereits seit AP8.9) |
| ROS-/Sensorzeitstempel | `self.get_clock().now()` | `DialogueState.header.stamp` -- Mess-/Synchronisationszeit, bewusst unverändert |
| absolute Zeit/dokumentierte Abläufe | `time.time()`/`time.gmtime()` | `WriteMemorySummary.valid_until_iso` -- ein echtes Kalenderdatum, MUSS Wanduhrzeit bleiben |

Keine globale, blinde Ersetzung aller Zeitstempel -- `safety_topics.py`
(cross-package, drei byte-identische Kopien) bleibt bewusst
unverändert.

## 3. Getrennte Bewegungsfreigaben und Parameterhärtung (Abschnitt 5)

Neue, read_only deklarierte Bridge-Parameter `allow_head_motion`/
`allow_arm_motion`/`allow_torso_motion` (Default überall aus, auch in
`mode=production`) -- restriktive Zusatzschicht VOR Lease-Erwerb, prüft
NUR zusätzlich zu bestehenden Status-/Safety-/Kollisions-/Compiler-/
Lease-Prüfungen. Ein Kopf-Test schaltet keine Arm-/Torsobewegung frei;
ein gemischtes Ziel (z.B. Kopf+Arm) braucht ALLE betroffenen
Freigaben. Basisbewegung erhält durch diese drei Parameter strukturell
KEINE Freigabe (bleibt beim bestehenden `motion_capable`/
`enable_live_motion`-Zwei-Schlüssel-System). Wirkungslos für
`offline_mock`/`offline_preview` (dieselbe Ausnahme wie bei
`GestureExecutionPolicy.authorize()` -- Offline-Profile berühren
strukturell nie Hardware).

`dry_run`/`execution_profile` UND die drei neuen Freigaben sind jetzt
alle `ParameterDescriptor(read_only=True)` -- rclpy selbst lehnt jeden
nachträglichen `set_parameters()`-Versuch ab (echter rclpy-Node-Test
beweist das). "Ein Bestätigungsflag allein ersetzt keine
Ressourcenfreigabe": `interaction_full_safe.launch.py`s
`i_confirm_gesture_test_supervised`/`i_confirm_hardware_acceptance_complete`
geben WEDER allein irgendeine Bewegungsfreigabe -- drei neue,
eigenständige Launch-Argumente (Default überall `"false"`) müssen
zusätzlich explizit gesetzt werden.

## 4. Funktionale Nachweise (Abschnitt 7)

| Anforderung | Test |
|---|---|
| Altes Result A entfernt keine Unbestätigt-Sperre von B | `test_run_dialogue_cancellation.py::test_an_old_records_late_result_never_touches_a_newer_records_state` |
| Alte verspätete Goal-Acceptance verändert keine neue Ausführung | `test_run_dialogue_cancellation.py::test_an_old_records_late_acceptance_never_touches_a_newer_records_state` |
| Gleichzeitige Registrierung startet höchstens ein Ziel | `test_run_dialogue_cancellation.py::test_concurrent_registration_for_the_same_channel_starts_at_most_one_goal` (echte Threads + Barrier) |
| Wanduhrsprung macht veraltete Daten nicht wieder frisch | `test_ap8_dialogue_lifecycle_offline_e2e.py::test_scenario_i_track_alive_uses_monotonic_time_not_wall_clock` |
| Kopf-Test verweigert Arm-/Torso-Anfragen | `test_bridge_node_actuator_arbiter.py::test_head_permission_alone_does_not_unlock_an_arm_gesture` |
| Gemischte Geste verlangt alle Ressourcenfreigaben | `test_bridge_node_actuator_arbiter.py::test_mixed_head_and_arm_gesture_requires_both_permissions` |
| Parameteränderung kann Offline-Isolation nicht aufheben | `test_bridge_node_read_only_safety_parameters.py` (echter rclpy-Node) |
| Personenverlust während Pipeline storniert aktive Systemgesten | `test_ap8_dialogue_lifecycle_offline_e2e.py::test_scenario_i_person_lost_during_pipeline_aborts_active_system_gestures_promptly` |
| Safety-Verlust während Antwort verhindert weitere Segmente | `_execute()`s Exec-Wartezyklus nutzt dieselbe `_dialogue_abort_requested()` -- kein dedizierter Test wegen des Aufwands, eine volle `_execute()`-Instanz nachzubilden (siehe `docs/DIALOGUE_GESTURE_LIFECYCLE.md`, "bewusste Scoping-Entscheidung") |
| Cancel nach Executor-Ergebnis, vor Memory-Commit, verhindert Speicherung | `test_run_dialogue_real_ros2_integration.py::test_cancel_during_speaking_writes_no_memory_summary_even_for_a_known_person` (echte ROS2-Kommunikation) |
| Executor-Worker-Ausnahme erzeugt terminalen Fehlerpfad | bereits in AP8.9 (`_run_exec()`s `try/except/finally`), unverändert bestätigt |
| Wiederholte Abbrüche lassen registrierte Arbeit nicht unbegrenzt wachsen | `repeated_session_cleanup`-Benchmark (`docs/AP8_RUNTIME_PERFORMANCE.md`): 500 Sitzungen, `rss_growth_kb: 0` |
| Ein Mitglied verlässt eine gültige Gruppe: kein vollständiger Abbruch | `test_bt_group_loss_preemption.cpp::StableGroupWithEnoughMembersDoesNotPreemptTheRunningDialogue` (echte BT-Ticks) |
| Gruppe wird ungültig: MonitorParticipants präemptiert | `test_bt_group_loss_preemption.cpp::GroupBecomingInvalidPreemptsTheRunningDialogue` (echter `rclcpp_action`-Server) |
| Nach Gruppenverlust startet kein alter Antwortplan neu | `test_bt_group_loss_preemption.cpp::NoNewAnswerPlanStartsAfterGroupLossHalt` |

## 5. Echte lokale ROS2-Integration

`test_run_dialogue_real_ros2_integration.py` (6 Tests, davon 2 neu in
diesem Auftrag): echter `RunDialogueActionServer` gegen echte
`Say`-/`PlayGesture`-Fake-Action-Server UND jetzt zusätzlich echte
`/get_person_context`-/`/write_memory_summary`-Services
(`_FakePersonMemoryServices`) sowie echte `/perception/person_tracks`-/
`/identity/person_identities`-Publikation -- beweist die aufgelöste
Personen-ID über echte ROS2-Kommunikation, nicht nur über
`person_context.get("known")`.

`test_bt_group_loss_preemption.cpp` (neu, 3 Tests): echter
`ReactiveSequence`-Teilbaum aus `MonitorParticipants` +
`RunDialogueViaBT` (dieselbe Struktur wie `GroupConversationLoop` in
`pepper_main.xml`), echter `rclcpp_action`-Fake-Server, echte
`/perception/conversation_groups`-Publikation.

`test_bridge_node_read_only_safety_parameters.py` (neu): echter
`PepperBridgeNode` (kein Fake), `dry_run:=true`.

## 6. Offline-Isolationsnachweis

Siehe `test_bridge_node_read_only_safety_parameters.py` (read_only-
Durchsetzung für alle fünf sicherheitsrelevanten Parameter, echter
Node-Konstruktionslauf ohne SSH-Verbindung bestätigt).
`test_bridge_node_health_offline_isolation.py` (aus 14/14, unverändert
gültig) bleibt die Grundlage für den Health-Timer-Nachweis.

## 7. Benchmarks und Optimierungen

Siehe `docs/AP8_RUNTIME_PERFORMANCE.md` für die vollständigen Vorher-/
Nachher-Zahlen. Kurzfassung: Gestenindex-Snapshot-Cache (Kandidat A)
umgesetzt, messbarer Vorteil in beiden geprüften Fällen (groß ohne
Suchtext, klein mit Suchtext); Warte-/Callback-Umstellung (Kandidat B)
bewusst NICHT umgesetzt (Risiko/Nutzen-Abwägung, ehrlich dokumentiert).

## 8. Unveränderte Sicherheitsgrenzen (Abschnitt 10)

`git diff --stat` gegen `gesture_execution_policy.py`/
`gesture_catalog.py`/`gesture_cancellation.py` bleibt LEER (keine dieser
Dateien wurde in AP8-R3 angefasst). `overall_verdict==pass AND
collision_checked==true` bleibt unverändert die einzige
Produktionsfreigabe. Kein Fake-Collision-Backend im produktiven Pfad.
Katalog: 24 Dateien, byte-identisch zur Baseline (17 draft/6
dry_run_validated/1 live_validated unverändert).

## 9. Verbleibende Softwarefehler / fehlende Nachweise

- Kein dedizierter End-zu-Ende-Test für "Safety-Verlust während Antwort
  verhindert weitere Segmente" auf Ebene einer vollständigen
  `_execute()`-Instanz (Code-Struktur + dieselbe, bereits getestete
  `_dialogue_abort_requested()`-Prüfung belegen den Pfad, aber kein
  eigener Integrationstest wegen des Aufwands, einen vollständigen
  Goal-Handle nachzubilden).
- Kandidat B (Warte-/Callback-Umstellung) bewusst nicht umgesetzt.

## 10. Verbleibende Hardware-Restpunkte / Produktionssperren (unverändert)

Kein echtes Kollisions-Backend (weiterhin keine Produktionsgeste
möglich); `t_pose` bleibt v1-Sonderfall; alle 14 Punkte aus
`docs/GESTURE_HARDWARE_ACCEPTANCE.md` bleiben `hwverificationrequired`.
Keine Hardwareverbindung, keine reale Bewegung, kein externer
LLM-Aufruf in diesem Auftrag.
