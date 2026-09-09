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
