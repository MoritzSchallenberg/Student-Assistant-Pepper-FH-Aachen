# Action-Cancellation: die vollständige Abbruch-Kette

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP5B.
Siehe auch `docs/ACTUATOR_ARBITER.md` (Leases/`CancelActuation`),
`docs/GESTURE_TRANSPORT.md` (`MotionTransport.cancel()`),
`docs/RESPONSE_PLAN_EXECUTION.md` (`ResponsePlanExecutor.cancel_active_fn`).

## Der zentrale Unterschied: ROS-Cancel vs. bestätigter Hardware-Stopp

Ein `action_msgs`-Cancel (`goal_handle.cancel_goal_async()`) bestätigt
NUR, dass der ROS2-Action-Server die Abbruch-ANFRAGE angenommen hat --
NICHT, dass Pepper sich tatsächlich bewegt hat oder verstummt ist.
Dieses Dokument beschreibt für jede Schicht ehrlich, WAS genau bestätigt
wird und was nicht. Kein Code in diesem Projekt behauptet einen
"bestätigten Hardware-Abbruch", ohne dass echte Pepper-Hardware das
verifiziert hat -- das ist in dieser Session nicht möglich (kein
Roboter erreichbar), daher bleibt der Hardware-Pfad durchgängig als
`hwverificationrequired` markiert.

## Fähigkeitstest: unterstützt qicli/NAOqi einen echten Mid-Trajectory-Abbruch?

Geprüfte Optionen (Auftrag-Reihenfolge A/B/C):

- **A. Async Task + Cancel**: NAOqi/`qi`-Framework bietet grundsätzlich
  asynchrone Tasks mit Cancel-Fähigkeit (`qi.Session`/`ALMotion`-Futures)
  -- aber `apps/web/pepper/qicli.py` ruft NAOqi ausschließlich über
  **synchrone SSH-Shell-Befehle** auf (`qicli call ALMotion....` per
  `exec_command()`, wartet auf den Prozessabschluss). Es gibt in diesem
  Code KEIN async Task-Handle, das man später abbrechen könnte -- ein
  einmal abgeschickter `exec_command()`-Aufruf läuft serverseitig
  ungestört weiter, bis NAOqi selbst fertig ist.
- **B. Persistenter qi-Helper-Prozess**: `motion_transport.py::
  LocalPepperQiHelperTransport` ist als dokumentierter, NICHT
  implementierter Platzhalter für genau diesen Ansatz vorgesehen (jede
  Methode wirft `NotImplementedError`) -- eine direkte NAOqi-SDK-
  Anbindung (statt SSH+`qicli`) könnte echte Task-Handles halten. Nicht
  umgesetzt in dieser Session (kein Pepper zum Verifizieren erreichbar,
  und ein persistenter Fremdprozess auf Pepper wäre ein zusätzliches,
  eigenständig zu betreibendes Sicherheitsrisiko).
- **C. Ehrlich dokumentiertes Best-Effort** (umgesetzt): kein echtes
  Mid-Trajectory-Abbrechen. Stattdessen wird die REAKTIONSZEIT auf einen
  Abbruchwunsch minimiert und jeder Abbruch ehrlich als
  "angefordert"/"bestätigt (Server-seitig)" statt "Hardware garantiert
  gestoppt" gekennzeichnet.

**Ergebnis**: Option C wurde umgesetzt, exakt wie vom Auftrag für den
Fall vorgesehen, dass A/B nicht nachweisbar sind ("implementiere die
sichere Abstraktion und Mocks, markiere den Hardwarepfad jedoch
ausdrücklich als `hwverificationrequired`").

## Die Kette, Schicht für Schicht

### 1. Transport (`motion_transport.py`, `pepper_client.py`)

`MotionTransport.cancel(timeout_s) -> CancelResult` ersetzt das
vorherige, potenziell UNBEGRENZTE Warten (bestätigter Fund: `cancel()`
konnte bei einer laufenden synchronen Trajektorie beliebig lange
blockieren). `PepperInterruptChannel` (`pepper_client.py`) ist eine
ZWEITE, vom Hauptkanal unabhängige SSH-Verbindung + eigenes
`threading.RLock`, ausschließlich für `stop_motion()`/`stop_speech()`/
`send_hold_position()` -- notwendig, weil der geteilte Hauptkanal
beliebig lange hinter einem laufenden `exec_command()` blockieren kann;
ein Abbruchwunsch darf nie dahinter warten müssen. Details:
`docs/GESTURE_TRANSPORT.md`.

`apps/web/pepper/qicli.py::say()` hatte zusätzlich eine echte
Shell-Injection-Lücke (Text wurde per f-String direkt in doppelte
Anführungszeichen eingebettet) -- behoben über `shlex.quote()`. Neue
`say_text_only()` nutzt `ALTextToSpeech.say` (keine automatische
Körperanimation, anders als `ALAnimatedSpeech.say`) und neue
`stop_speech()`/`stop_motion()` sind die vom Interrupt-Kanal
verwendeten Primitive.

`ihk_pepper_bridge/tts_guard.py::validate_tts_text()` ist eine
zusätzliche, von jeder Dialog-seitigen Sanitisierung UNABHÄNGIGE
Verteidigungsschicht direkt an der Bridge-Grenze -- lehnt leeren/zu
langen Text, NAOqi-Steuertags und Shell-Metazeichen ab.

### 2. Bridge (`bridge_node.py`)

`_execute_say()`/`_execute_gesture()` laufen in einem Hintergrundthread
mit begrenztem Polling (statt vollständig blockierend) -- ein
`cancel_event`/`interrupt_channel`-Paar wird an `GestureCatalog.play()`
durchgereicht (beide Parameter optional, `None` erhält das Verhalten
vor AP5B exakt). Jede Say-/PlayGesture-Ausführung erwirbt zuerst eine
Lease vom Aktuator-Arbiter (siehe `docs/ACTUATOR_ARBITER.md`) und gibt
sie in JEDEM Ausstiegspfad wieder frei.

### 3. Dialog (`response_plan_executor.py`, `run_dialogue_action_server.py`)

Vor AP5B war `ResponsePlanExecutor.cancel()` rein passiv (nur ein Flag,
zwischen Segmenten geprüft). Der neue `cancel_active_fn`-Hook ruft
SOFORT `run_dialogue_action_server.py::_cancel_active_actions()` auf,
die das gerade aktive Say-/Gesture-Ziel aktiv per `cancel_goal_async()`
abbricht. `_send_goal_and_wait()` bricht bei EIGENEM Timeout jetzt
ebenfalls aktiv ab (begrenzte 2.0s-Bestätigungswartezeit) statt nur
aufzugeben. Der `executor.execute()`-Aufruf selbst läuft in einem
Hintergrundthread mit einer 0.1s-Cancel-Poll-Schleife (bis zu 5.0s
Bestätigungswartezeit). Details: `docs/RESPONSE_PLAN_EXECUTION.md`.

### 4. Behavior Tree (`bt_nodes.hpp`/`bt_nodes.cpp`)

`onHalted()` der fünf Action-Knoten (`SpeakText`, `PlayCatalogGesture`,
`PlayDailyPresentation`, `ApproachSelectedPerson`, `RunDialogueViaBT`)
rief vor AP5B `async_cancel_goal()` komplett OHNE Feedback/Bestätigung
auf ("fire-and-forget"). Neue, ROS-unabhängige (per `std::future`
testbare) Hilfsfunktion `waitForBoundedCancelConfirmation()`: wartet
BEGRENZT (250ms) auf die Cancel-Bestätigung des Servers und
protokolliert ehrlich, ob sie eingetroffen ist
(`last_halt_cancel_confirmed_`-Member, über `lastHaltCancelConfirmed()`
abrufbar). 250ms ist bewusst kurz -- der Future wird bereits fertig,
sobald der Action-Server die Cancel-Anfrage per `CancelGoal`-Service
angenommen hat (ein schneller, lokaler ROS2-Vorgang), nicht erst, wenn
die physische Bewegung tatsächlich steht.

`WaitForGestureFromTrack`/`SetInteractionState` haben keine laufende
Action-Goal (Topic-Subscription bzw. Service-Aufruf) und bleiben
unverändert.

### 5. Presentation Manager (`presentation_manager_node.py`)

Vor AP5B wurde ein Abbruch der Präsentation nur zwischen Schritten
(`_check_cancel()`) bemerkt -- ein GERADE LAUFENDES Say-Ziel (z.B.
während der Anmoderation) lief unbeeinflusst bis zu seinem natürlichen
Ende weiter. `_cancel_callback()` bricht jetzt sofort das aktive
Say-Ziel ab (`_active_say_goal_handle` + `_cancel_active_say()`), bevor
die eigentliche `_execute()`-Schleife überhaupt reagiert.

### 6. SetHeadPose/OrientHeadToSound (Entwicklungsauftrag 04-B, AP6)

Neuer, sechster Cancel-Pfad, derselben Architektur folgend:
`bridge_node.py::_execute_set_head_pose()` läuft im Hintergrundthread
mit begrenztem Polling (`HEAD_POLL_INTERVAL_S`/`HEAD_CANCEL_GRACE_S`,
gleiches Muster wie `_execute_say`/`_execute_gesture`) -- ein Cancel
ruft `self.interrupt_channel.stop_motion()` über denselben zweiten
SSH-Kanal wie Say/PlayGesture auf. Der BT-Knoten `OrientHeadToSound`
verwendet dieselbe `waitForBoundedCancelConfirmation()`-Hilfsfunktion
wie die anderen fünf Action-Knoten (siehe `docs/BEHAVIOR_TREE.md`).
`orient_to_sound_node.py::_send_goal_and_wait()` bricht bei eigenem
Timeout oder bei eigenem Cancel ebenfalls aktiv das laufende
`SetHeadPose`-Ziel ab (begrenzte 2.0s-Bestätigungswartezeit, gleiches
Muster wie `run_dialogue_action_server.py`).

## `CancelActuation`-Service (Arbiter-Ebene)

Ein zusätzlicher, ressourcenzentrierter Abbruchweg über den Aktuator-
Arbiter (`/actuator_arbiter/cancel`, `lease_id` ODER `goal_id`):
widerruft die Lease SOFORT arbiterseitig. Bestätigt NUR den
Arbiter-seitigen Widerruf, NICHT den tatsächlichen Hardware-Stopp --
der eigentliche Besitzer (z.B. `pepper_bridge`) bemerkt den Entzug über
sein eigenes State-Polling und leitet den Abbruch an den Transport
weiter (Kette wie oben). `emergency_revoke_all()` (Bumper/Not-Halt)
bypasst diesen Weg komplett und widerruft ALLE Leases sofort, unabhängig
von Priorität/`safety_ok`.

## Geschlossene Umgehungspfade

`apps/web/app.py`, `apps/web/stt/listen_loop.py`,
`vision/mimic_arms.py` sprachen/sprechen Pepper teilweise DIREKT per
qicli an, komplett an der oben beschriebenen Kette vorbei (keine Lease,
kein Cancel-Schutz, keine `tts_guard`-Validierung). Siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md` (AP5B, Commit 5) für die
Details der Sperre (`PEPPER_WEB_HARDWARE_TEST_ENABLED`, sicherer
Default `false`).

## Getestet / nicht getestet

Jede der fünf Schichten hat eigene Unit-/gtest-Abdeckung gegen Fakes
(siehe `docs/DEVELOPMENT_ORDER_04_B_REPORT.md` für die genaue
Testliste). **Nicht getestet, weil kein Pepper in dieser Session
erreichbar ist**:

- Ob ein echter zweiter SSH-Kanal (`PepperInterruptChannel`) auf
  echter Hardware tatsächlich schneller reagiert als der Hauptkanal.
- Ob ein `stop_motion()`/Hold-Position-Befehl eine laufende
  `angleInterpolation`-Trajektorie auf echter Hardware tatsächlich
  unterbricht, oder ob NAOqi sie trotzdem zu Ende ausführt.
- Die vier Hardware-Testphasen A-D aus Auftrag-Abschnitt 16 wurden NICHT
  durchgeführt (kein Roboter). Alle Cancel-Pfade bleiben durchgängig
  `hwverificationrequired`.

## Neue Cancel-Pfade (Entwicklungsauftrag 04-B, AP7)

`ReturnToOriginViaBT` (BT.CPP) und `_execute_return_to_origin()`/
`_execute_follow()` (`person_approach_node.py`) reihen sich in dieselbe
Kette ein: `onHalted()` bricht über `waitForBoundedCancelConfirmation()`
wirklich ab (gleiche Vorlage wie `ApproachSelectedPerson`/
`RunDialogueViaBT`), und beide Python-Actions prüfen ihren `monitor_fn`
bei JEDEM Fahrsegment neu (nicht nur einmalig beim Start). Neu bei
FollowPerson: ein `monitor_fn`-Abbruch mit Grund `"replan_needed"`
(relevante Personenbewegung während der Fahrt) wird bewusst NICHT wie
ein echter Fehlerabbruch behandelt -- die äußere Schleife plant sauber
neu, statt die gesamte Aktion scheitern zu lassen. Details:
`docs/FOLLOW_PERSON_RUNTIME.md`, `docs/RETURN_TO_ORIGIN.md`.

## PlayGesture-Abbruch: unbestätigt bleibt unbestätigt (Entwicklungsauftrag 04-B, AP8-R1.6)

`pepper_bridge`s `PlayGesture`-Action folgt seit AP8-R1 strikt der oben
etablierten Unterscheidung `cancel_requested` / `cancel_accepted_or_sent`
/ `physical_or_transport_completion_confirmed`. Bestätigt der
Hintergrund-Thread sein Ende nicht innerhalb der Cancel-Grace-Zeit,
meldet die Action `success=False, error_message="cancel_unconfirmed"` --
**nie** Erfolg. Die zugehörige Aktuator-Lease wird dabei absichtlich
**nicht** freigegeben (blockiert dadurch automatisch jedes zweite Ziel
auf denselben Ressourcen über die bestehende Arbiter-Konfliktprüfung)
und erst bereinigt, sobald der Thread nachweislich endet. Details inkl.
der genauen Quarantäne-Mechanik: `docs/GESTURE_CANCELLATION_AND_RESTORE.md`.

## Verspätete Goal-Annahme und Handle-Besitz (Entwicklungsauftrag 04-B, AP8.8)

Zwei bestätigte Race-Lücken rund um verspätet eintreffende
Goal-Ergebnisse wurden geschlossen -- Details/Tests siehe
`docs/DIALOGUE_GESTURE_LIFECYCLE.md` (Abschnitt "Session-/Goal-Bindung"),
hier nur die Kurzfassung für die Abbruch-Kette:

- **`run_dialogue_action_server.py::_send_goal_and_wait()`**: ein
  `call_token = object()` pro Aufruf plus ein
  `self._active_goal_tokens`-Dict binden ein `active_goal_attr`
  (`_active_say_goal_handle`/`_active_gesture_goal_handle`) jetzt an den
  EIGENEN Aufruf. Trifft eine Goal-Annahme ein, NACHDEM der eigene
  Aufruf bereits per Timeout aufgegeben hat (`abandoned`-Event gesetzt),
  wird das verspätet angenommene Ziel SOFORT storniert und
  `active_goal_attr` NIE angefasst -- vorher konnte ein solches
  Spätergebnis den Handle eines ganz anderen, neueren Aufrufs
  überschreiben. Jeder Aufräumpfad (`on_result`, `finally`) gibt den
  Handle nur frei, wenn der eigene Token noch der aktuell eingetragene
  ist (`_release_if_owner()`).
- **`RunDialogueViaBT::onHalted()`** (BT.CPP): war `goal_handle_` beim
  Halt noch `nullptr` (Annahme steht noch aus), passierte bisher GAR
  NICHTS -- eine später eintreffende Annahme lief danach komplett
  unbeaufsichtigt weiter, ohne dass je ein Cancel gestellt wurde. Ein
  neues `halted_before_acceptance_`-Flag plus ein
  `SendGoalOptions::goal_response_callback` (statt des bisherigen
  optionslosen `async_send_goal(goal)`) stornieren ein so verspätet
  angenommenes Ziel jetzt unmittelbar bei Ankunft der Annahme. Ein
  bestätigt fertiges Cancel-Future beweist dabei für sich allein WEDER
  eine erfolgreiche Annahme NOCH einen tatsächlichen Stillstand -- die
  bestehende Unterscheidung `cancel_requested`/`cancel_accepted`/
  `action_terminal`/`transport_terminal`/`physisch bestätigt` bleibt
  unverändert gültig, siehe oben. Funktional bewiesen über echte
  `rclcpp_action`-Kommunikation gegen einen kontrollierten
  Fake-Server: `test/test_bt_dialogue_gesture_lifecycle.cpp`.
- **`RunDialogueActionServer._goal_callback()`**: erzwingt jetzt (unter
  `self._active_execution_lock`) ein hartes Ein-Ziel-Limit -- ein
  zweites `RunDialogue`-Ziel wird abgelehnt (`GoalResponse.REJECT`),
  solange eine Sitzung bereits läuft, statt zwei Ausführungen
  unkoordiniert dieselben globalen Action-Handle-Attribute teilen zu
  lassen. Über echte ROS2-Action-Kommunikation bewiesen:
  `test/test_run_dialogue_real_ros2_integration.py::
  test_a_second_concurrent_run_dialogue_goal_is_rejected`.

## Unbestätigtes Ende gab den Handle trotzdem frei (Entwicklungsauftrag 04-B, AP8.9)

Bestätigter Fund: `_send_goal_and_wait()`s `finally`-Block rief
`_release_if_owner()` bisher UNBEDINGT auf -- auch dann, wenn selbst die
zusätzliche 2.0s-Cancel-Bestätigungswartezeit nach dem eigenen Timeout
KEIN Ergebnis brachte. Ein Timeout beweist aber kein terminales Ende
einer noch laufenden Action (dieselbe Regel wie beim Bridge-seitigen
`cancel_unconfirmed`, siehe oben). Ein neues `self._unconfirmed_action_attrs`-
Set verhindert jetzt sowohl die Freigabe als auch jeden NEUEN Aufruf für
dasselbe `active_goal_attr`, bis der irgendwann doch noch eintreffende
echte `on_result()`-Callback die Markierung wieder aufhebt (und dabei --
wie zuvor -- nur den eigenen Datensatz bereinigt, siehe Call-Token oben).
`RunDialogueActionServer._execute()`s Hauptschleife behandelt ein so
markiertes Attribut als sichtbaren `ACTION_UNCONFIRMED`-Fehlerzustand:
kein normaler Folgezustand, kein Memory-Schreiben, keine neue
konkurrierende Ausführung. Getestet in `test_run_dialogue_cancellation.py`
(`test_send_goal_and_wait_does_not_release_the_handle_after_an_unconfirmed_timeout`,
`test_a_new_call_is_refused_while_the_same_attr_is_still_unconfirmed`,
`test_a_late_arriving_result_clears_the_unconfirmed_marker_and_releases_the_handle`).
