# Dialog-Gesten-Lifecycle: Bindung, Abbruch, unbestätigtes Ende

Stand: 2026-09-13. Entwicklungsauftrag 04-B, AP8.8, Commit 13/14.
Implementierung: `ihk_pepper_dialog/run_dialogue_action_server.py`,
`ihk_pepper_dialog/response_plan_executor.py`,
`ihk_pepper_behavior_tree/{include/ihk_pepper_behavior_tree/bt_nodes.hpp,src/bt_nodes.cpp}`.
Siehe auch `docs/RESPONSE_PLAN_EXECUTION.md` (Executor-Details),
`docs/ACTION_CANCELLATION.md` (vollständige, schichtübergreifende
Abbruchkette), `docs/BEHAVIOR_TREE.md` (`RunDialogueViaBT`),
`docs/GESTURE_CANCELLATION_AND_RESTORE.md` (Restore-/Atem-Matrix).

Dieses Dokument beschreibt den geschlossenen Kreislauf zwischen
deterministischer Bestätigungsgeste, begrenzter Denkschleife,
Drei-LLM-Pipeline, ResponsePlan-Ausführung, Say/PlayGesture-Aktionen,
Abbruch/Präemption und Sitzungsende -- und was davon tatsächlich
bewiesen ist vs. was `hwverificationrequired` bleibt.

## 1. Sitzungsgebundener Ablauf (`DialogueState`)

```
ACKNOWLEDGING -> THINKING (optional) -> WAITING_FOR_RESPONSE (optional)
              -> SPEAKING -> WAITING_FOR_FOLLOWUP
```

`ACKNOWLEDGING`/`WAITING_FOR_RESPONSE`/`THINKING` sind `DialogueState`-
Werte (Feedback des `RunDialogue`-Ziels), NICHT zu verwechseln mit
`InteractionState`-Werten (`CONVERSATION_READY` etc., Zustand des
Gesamtsystems außerhalb des Dialogs) -- beide Enums werden im Code klar
getrennt geprüft (`_runtime_gesture_context()["current_interaction_state"]`
vs. `feedback(state_value, state_name, ...)`). Keine YAML-Zustände wurden
für diesen Auftrag erweitert; die bestehenden Werte reichen aus.

`WAITING_FOR_RESPONSE` wird NUR sichtbar, wenn die Denkschleife
tatsächlich anläuft (Pipeline noch nicht fertig NACH
`thinking_loop_delay_s`) -- eine schnelle Antwort überspringt diesen
Zustand vollständig (Regressionstest: Szenario B,
`test_ap8_dialogue_lifecycle_offline_e2e.py::
test_scenario_b_no_thinking_loop_for_a_fast_pipeline`).

## 2. Bestätigungs-/Denkgeste: System-Gesten, nie LLM-wählbar

`acknowledge_nod_small`/`thinking_loop_subtle` sind `system_only: true`,
`selectable_by_llm: false` -- werden NIE von LLM 2 vorgeschlagen, IMMER
höchstens einmal pro akzeptierter Frage angefordert
(`_run_acknowledge_gesture()`/`_run_thinking_loop()`, aufgerufen aus
genau einer Stelle in `_acknowledge_and_run_pipeline()` pro Aufruf).

- **Bestätigungsgeste**: Fire-and-forget in einem eigenen Thread
  (`acknowledge_thread`) -- blockiert bewusst NICHT den Pipeline-Start.
  Ein Fehlschlag/eine Ablehnung des Rechecks (siehe unten) blockiert die
  sichere LLM-/TTS-Verarbeitung NICHT (der Thread schluckt seine eigene
  Exception, siehe `_run_acknowledge_gesture()`s `try/except`). AP8.8
  schließt eine bestätigte Lücke: der Thread war bisher NICHT
  vollständig verfolgt -- ein neues `acknowledge_done`
  (`threading.Event`, im `finally` des inneren `_run_acknowledge()`
  gesetzt) macht sein tatsächliches Ende jetzt sichtbar; die
  Hauptschleife wartet bei einem Cancel BEGRENZT (2.0s) darauf, statt
  den Thread einfach unverfolgt weiterlaufen zu lassen.
- **Denkschleife**: startet NUR, wenn (a) die Pipeline nach
  `thinking_loop_delay_s` noch läuft, (b) Interaktions-/
  Sicherheitszustand zum Startzeitpunkt noch gültig ist. Deckel:
  `thinking_loop_max_repetitions` UND `thinking_loop_max_duration_s`
  wirken UNABHÄNGIG voneinander (je ein eigener Regressionstest,
  Szenario C). Zeitmessung über `time.time()` (monoton innerhalb eines
  Laufs, keine Systemzeitsprünge in dieser Session relevant). Abbruchpfad:
  `stop_event.is_set()` wird NUR ZWISCHEN zwei Zyklen geprüft (nicht
  mitten in einer laufenden Trajektorie, siehe Abschnitt 5 unten) --
  bewusst nicht als feinere Garantie behauptet, als sie ist.
- **AP8.8-Fix**: bei einem Cancel WÄHREND die Pipeline noch läuft wurde
  bisher NUR `thinking_loop_stop` gesetzt (verhindert den NÄCHSTEN
  Zyklus), aber eine GERADE LAUFENDE Bestätigungs-/Denkgeste NICHT aktiv
  beendet -- der Cancel-Effekt kam erst mit dem natürlichen Ende dieses
  einen Zyklus an. `_acknowledge_and_run_pipeline()` ruft jetzt bei
  einem erkannten Cancel SOFORT zusätzlich
  `self._cancel_active_actions()` auf (bricht das aktuell aktive Say-/
  Gesture-Ziel aktiv per `cancel_goal_async()` ab) und verlässt die
  Wartschleife UNMITTELBAR (`break`), statt weiter auf `pipeline_done`
  zu warten. Regressionstest:
  `test_dialogue_thinking_loop.py::test_cancel_during_pipeline_returns_none_promptly_without_waiting_for_the_pipeline`
  (eine absichtlich hängende Pipeline, `elapsed < 2.0s` trotz 10s-Timeout
  im Fake).

## 3. Später eintreffendes Pipeline-Ergebnis wird nie verwendet

Bei einem erkannten Cancel gibt `_acknowledge_and_run_pipeline()` sofort
`None` zurück, OHNE den `pipeline_thread` noch zu joinen -- dieser läuft
als verwaister Daemon-Thread strukturell sicher weiter (sein Ergebnis
landet in einem pro Aufruf FRISCHEN lokalen `dict`, das nach der
Rückkehr nie wieder gelesen wird). Der `None`-Rückgabewert nutzt den
BESTEHENDEN `_execute()`-Vertrag (`if pipeline_output is None: continue`)
-- die äußere Schleife prüft am Schleifenkopf erneut
`goal_handle.is_cancel_requested` und beendet den Durchlauf dort reell,
statt eine neue Pipeline für dieselbe bereits beendete Antwortgenerierung
zu starten. Es wird an keiner Stelle behauptet, ein Python-Thread oder
ein externer LLM-Aufruf sei "beendet", nur weil sein Ergebnis nicht mehr
gelesen wird -- der Thread lebt faktisch weiter, das Provider-seitige
Fehlen einer echten Interrupt-Fähigkeit bleibt ehrlich dokumentiert
(kein Provider in dieser Session unterstützt einen echten Server-Abbruch
eines laufenden Requests).

## 4. Sitzungs-/Ziel-/Antwortbindung

- **Ein-Ziel-Erzwingung**: `_goal_callback()` reserviert
  `self._active_session_id` ATOMAR unter
  `self._active_execution_lock` -- ein zweites `RunDialogue`-Ziel wird
  abgelehnt (`GoalResponse.REJECT`), solange eine Sitzung aktiv ist.
  `_execute()`s neuer `finally`-Block gibt `self._active_session_id`
  NUR frei, wenn er noch dem EIGENEN `session_id` entspricht (ein
  fremder/verzögerter Aufruf kann den Slot einer neueren Sitzung nicht
  versehentlich räumen). Bewiesen über ECHTE ROS2-Action-Kommunikation:
  `test_run_dialogue_real_ros2_integration.py::
  test_a_second_concurrent_run_dialogue_goal_is_rejected`.
- **Track-ID ≠ Person-ID ≠ Gruppenidentität**: `session_id` kann ein
  reiner Track-Bezeichner sein (`_try_parse_int()` versucht, ihn als
  `track_id` zu interpretieren) -- er wird NICHT unkritisch als
  persistente Personen-ID oder vollständige Gruppenidentität behandelt.
  Ein numerischer `session_id`-Wert ohne je empfangenen
  `PersonTrackArray`-Eintrag führt (fail-closed) zu einem sofortigen
  `PERSON_LOST`-Abbruch -- ein reales, im Test entdecktes Verhalten
  (siehe Abschnitt 8 unten), keine neu erfundene Regel.
- **Goal-Handle-Besitz**: `_send_goal_and_wait()`s Call-Token-Mechanismus
  (siehe `docs/ACTION_CANCELLATION.md`) stellt sicher, dass ein Ergebnis
  exakt zu der Sitzung/Frage gehört, für die es erzeugt wurde -- ein
  alter Callback kann NIE den Datensatz einer neuen Ausführung
  verändern, eine spätere Bereinigung entfernt NUR den eigenen
  Datensatz.
- **ResponsePlanExecutor-Wiederverwendung**: derselbe Executor wird über
  die Sitzung hinweg wiederverwendet (kein Neu-Konstruieren pro Frage);
  ein neuer Lauf wird ausschließlich durch den bewusst
  sitzungsgebundenen `_execute()`-Aufruf gestartet, nie implizit.

## 5. ResponsePlan-Ausführung: Cancel-Reihenfolge je Segment

Siehe `docs/RESPONSE_PLAN_EXECUTION.md` für die vollständige AP8.8-
Änderungsliste (Cancel-Flag-Lebenszyklus, atomarer Doppelstart-Schutz,
Gesten-Ausnahme-Erfassung, unterbrechbare Nachlaufpause). Kurzfassung
der Segmentregeln:

| `gesture_relation` | Reihenfolge | Cancel-Wirkung |
|---|---|---|
| `before_segment` | Geste, DANACH Sprache | Cancel zwischen Geste und Sprache verhindert die Sprache; ein rein optionaler Gestenfehlschlag bei noch sicherem Zustand erlaubt die Sprache trotzdem |
| `with_segment_start` | Geste + Sprache nahezu gleichzeitig, BEIDE Ausführungen verfolgt | kein garantierter wort-/lippen-/hardware-exakter Gleichlauf -- ausdrücklich nicht behauptet |
| `after_segment` | Sprache, DANACH Geste | Geste NUR bei erfolgreicher Sprache UND ohne zwischenzeitliches Cancel |

Ein Cancel zwischen zwei Teilaktionen verhindert die noch nicht
gestartete Teilaktion (nie rückwirkend die bereits laufende). Die
kanonische Geschwindigkeitsskalen-Auflösung aus AP8-R1/R2 bleibt
unverändert -- keine neue lokale Clamping-/Sonderlogik in diesem Auftrag.

## 6. Cancel-Quellen während des gesamten Lebenszyklus

Der Lebenszyklus reagiert nicht nur am Rundenanfang, sondern während
aller relevanten Phasen auf: ROS-Goal-Cancel/Präemption,
Benutzer-Stop, Codewort "Eisenbahn", Sicherheitsereignis/ungültiger
Sicherheitszustand, Personenverlust, Verlust der aktiven
Gesprächsgruppe, Sitzungs-Timeout, Node-Shutdown. Bestehende Verträge
bleiben unverändert:

- `GestureCancelReason`/`CancelSignal`: ein generisches ROS-Cancel bleibt
  `PREEMPTED` (NIE automatisch als `NORMAL_USER_CANCEL`
  umgedeutet), der Codewort-Pfad nutzt weiterhin
  `CODEWORD_INTERRUPT` über `/interaction/authorized_command`
  (`command: interrupt_and_look`) -- der zuerst gesetzte Abbruchgrund
  bleibt bestehen, ein späterer Sicherheitsgrund überschreibt NIE einen
  bereits gesetzten.
- Restore bleibt nur innerhalb der bestehenden, engen Matrix erlaubt --
  kein Restore nach Codewort, Sicherheitsereignis, Präemption,
  unbestätigtem Transportende oder Interaktionsverlust (unverändert,
  siehe `docs/GESTURE_CANCELLATION_AND_RESTORE.md`). Keine automatische
  Reaktivierung der Atemroutine nur wegen eines Dialog-Cleanups.
- Gruppenverlust: der Verlust EINES einzelnen Mitglieds ist nicht
  automatisch Verlust der GESAMTEN Gruppe -- bestehende Gruppenregeln/
  `MonitorParticipants` bleiben die einzige Quelle dieser Entscheidung,
  kein neuer paralleler Mechanismus. Keine Vermischung persönlicher
  Erinnerungen innerhalb einer Gruppe.

## 7. Unbestätigtes Ende bleibt unbestätigt

Fünf Stufen bleiben explizit unterschieden und werden von keinem Offline-
Test als "Stufe 5" behauptet:

1. Cancel angefordert
2. Cancel-Anfrage angenommen
3. Action terminal (ROS2-Ergebnis liegt vor)
4. Transport tatsächlich beendet
5. Physischer Stillstand hardwareseitig bestätigt

Bleibt ein Ende unbestätigt: sichtbarer Fehler-/`cancel_unconfirmed`-
Zustand, kein normaler Folgezustand, keine neue konkurrierende Geste,
kein Gedächtniseintrag, bestehende Handles/lokale Sperren bleiben
erhalten (nicht durch einen lokalen Timeout geräumt). Die AP8-R2-Regel
bleibt unverändert: Bridge/Katalog geben Lease/Quarantäne NIE über einen
lokalen Timeout bei unbestätigtem Transportende frei.

## 8. Reale, im Test entdeckte Verhaltensweisen (keine erfundenen Werte)

Beim Bau von `test_run_dialogue_real_ros2_integration.py` traten zwei
reale, vorher nicht dokumentierte Laufzeitverhalten zutage (kein
Bugfix nötig, aber Testkonstruktion musste sich danach richten -- hier
dokumentiert, damit sie nicht als Testartefakt missverstanden werden):

- `RunDialogueActionServer.__init__()` liest LLM-Provider-Parameter
  SOFORT bei der Konstruktion (`get_parameter(...).value`) -- ein
  `set_parameters()`-Aufruf NACH der Konstruktion kommt zu spät und
  wird ignoriert. Parameter müssen vor `rclpy.init()`/Node-Konstruktion
  als globale ROS-Args übergeben werden.
  (Bereits bekanntes, korrektes Muster aus
  `manual_dialogue_e2e_check.py` -- hier nur erneut bestätigt.)
- Ein numerischer `session_id`-String wird von `_try_parse_int()` als
  `track_id` interpretiert -- ohne je empfangenen `PersonTrackArray`
  gilt der Track fail-closed als nicht lebendig, die Sitzung endet
  sofort mit `PERSON_LOST`. Reale Tests müssen deshalb einen
  nicht-numerischen `session_id`-Wert verwenden, wenn kein Track
  simuliert wird.

## 9. Getestet / nicht getestet

**Offline, reale Projektlogik (kein `rclpy.init()`)**:
`test_response_plan_executor.py` (23 Tests), `test_dialogue_thinking_loop.py`,
`test_run_dialogue_cancellation.py`,
`test_ap8_dialogue_lifecycle_offline_e2e.py` (9 neue Szenarien: B
Denkschleife startet nach Verzögerung / kein Start bei schneller Antwort,
C Wiederholungs-/Dauerdeckel unabhängig + sofortiger Stopp bei bereits
gesetztem `stop_event`, D optionale Geste durch Recheck gesperrt aber
Sprache läuft trotzdem, I Personenverlust über `_track_alive` inkl.
Altersgrenze) -- alle binden die ECHTEN, ungebundenen Methoden von
`RunDialogueActionServer`/`ResponsePlanExecutor` an ein leichtgewichtiges
Fake, kein Test prüft nur eigene Fake-Logik. Szenarien A (schnelle
Antwort), E (früher Cancel), K (konkurrierende Sitzung) sind über echte
ROS2-Action-Kommunikation in `test_run_dialogue_real_ros2_integration.py`
abgedeckt; F (Cancel während Pipeline) über
`test_dialogue_thinking_loop.py`; L (verspätete Goal-Annahme) über
`test_run_dialogue_cancellation.py` und
`test_bt_dialogue_gesture_lifecycle.cpp`; G/H (Sicherheit/Codewort) und
M (unbestätigtes Ende) über die unverändert weiterhin grünen
AP8-R1/R2-Tests (`test_ap8r1_offline_e2e.py` u.a.) -- nicht erneut
dupliziert, siehe deren eigene Dateien.

**Echte ROS2-Action-Integration** (Abschnitt 10 des Auftrags):
`test_run_dialogue_real_ros2_integration.py` -- ein echter
`RunDialogueActionServer`-Node gegen echte `Say`-/`PlayGesture`-
Fake-ActionServer (echte `rclpy.action.ActionServer`-Instanzen statt
einer echten Pepper-Bridge), volle Drei-LLM-Pipeline über
`MockLLMProvider`, `ResponsePlanValidator`/`ResponsePlanExecutor`
unverändert real durchlaufen. Bewiesen: kompletter Runde-Trip
(Transkript -> Bestätigungsgeste -> Sprache -> Ergebnis), echter Cancel
über die reale Action (bricht das aktive Say-Ziel), Ablehnung eines
zweiten konkurrierenden Ziels. **Verboten und nicht verwendet**: echte
Pepper-Adresse, echte SSH-/qicli-Verbindung, externer LLM-Aufruf, Live-
Nav2, echte Bewegung.

**Funktionale BT.CPP-GTests**: `test_bt_dialogue_gesture_lifecycle.cpp`
(2 Tests, echter `rclcpp_action`-Server) -- siehe
`docs/BEHAVIOR_TREE.md` für Details.

**Nicht getestet / bleibt `hwverificationrequired`**: ob ein reales
Mid-Trajectory-Stoppen auf Servo-Ebene stattfindet (siehe die
korrigierte Docstring-Erklärung in `_run_thinking_loop()` --
Unterbrechung existiert real, aber mit Keyframe-/Segment-Granularität,
kein hardwarebestätigter Mid-Servo-Stopp); ob ein echter LLM-Provider
einen laufenden Request tatsächlich serverseitig abbricht (keiner der
verfügbaren Provider-Implementierungen bietet das); jede physische
Stufe-5-Bestätigung (Abschnitt 7).
