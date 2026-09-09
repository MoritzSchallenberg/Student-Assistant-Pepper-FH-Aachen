# Zentraler Aktuator-Arbiter

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP5B.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_interaction/ihk_pepper_interaction/
actuator_arbiter.py` (reine Kernlogik), `actuator_arbiter_node.py`
(ROS2-Wrapper), `resource_derivation.py`. Siehe auch
`docs/ACTION_CANCELLATION.md` für die Abbruch-Kette, die auf diesen
Leases aufbaut.

## Zweck

Vor AP5B konnte jede Action (Say/PlayGesture/ApproachPerson/...) direkt
auf Peppers Aktoren zugreifen, ohne dass eine zentrale Stelle wusste,
welche Ressource gerade belegt ist. Zwei gleichzeitige Aufrufe auf
dieselbe Ressource (z.B. zwei Gesten auf denselben Arm, oder eine Geste
während Nav2 fährt) konnten sich gegenseitig stören. Der Arbiter macht
"wer darf gerade was tun" explizit und serverseitig durchsetzbar, bevor
`ihk_pepper_bridge` überhaupt einen Transport anfasst.

**Der Arbiter ersetzt NICHT Motion Guard** (bleibt die endgültige,
hardwarenahe Sicherheitsschicht vor `/cmd_vel`, siehe `motion_guard.py`)
und ist **keine Authentifizierungsschicht** gegen absichtlich bösartige
ROS2-Nodes (ROS2 bietet in diesem Projekt keine Node-Authentifizierung)
-- ein Node, der die Lease-Services einfach ignoriert, kann weiterhin
direkt einen Transport aufrufen. Die Verteidigung liegt darin, dass
JEDER vertrauenswürdige, im Projekt selbst verwendete Aufrufer
(`bridge_node.py`, `person_approach_node.py`) tatsächlich über den
Arbiter geht.

## Ressourcen

`SPEECH, HEAD, LEFT_ARM, RIGHT_ARM, TORSO, BASE` (verpflichtend,
exklusiv) und `LEDS, TABLET` (optional, NIE exklusiv -- nehmen nie an
Konflikt-/Präemptionsprüfungen teil). Zusätzliche, nicht rein
ressourcenbasierte Regel: `TORSO` und `BASE` schließen sich GEGENSEITIG
aus, selbst wenn beide für sich genommen frei wären (Umknick-/
Fallrisiko bei gleichzeitigem Fahren+Neigen).

`resource_derivation.py` leitet aus einer Aktion die betroffenen
Ressourcen ab (`resources_for_gesture(gesture)`,
`resources_for_speech()`) -- eine Geste, die laut Katalog `affects_head`
setzt, beansprucht zusätzlich `HEAD`, nicht nur den/die Arm(e).

## Prioritäten (serverseitig bestimmt, NIE vom Client/LLM setzbar)

Niedrigere Zahl = höhere Dringlichkeit:

| Rang | Bedeutung |
|---|---|
| 1 | `PRIORITY_EMERGENCY_STOP` |
| 2 | `PRIORITY_HARDWARE_FAULT` |
| 3 | `PRIORITY_USER_STOP` |
| 4 | `PRIORITY_SAFETY_ABORT` |
| 5 | `PRIORITY_RETURN_TO_SAFE` |
| 6 | `PRIORITY_NAVIGATION` |
| 7 | `PRIORITY_DIALOGUE` |
| 8 | `PRIORITY_PRESENTATION` |
| 9 | `PRIORITY_ATTRACT` |
| 10 | `PRIORITY_IDLE` |

Ein Owner, der eine Priorität `<= PRIORITY_SAFETY_ABORT` beansprucht,
aber nicht mit einem vertrauenswürdigen Präfix beginnt
(`TRUSTED_EMERGENCY_OWNER_PREFIXES = ("motion_guard", "supervisor",
"actuator_arbiter")`), wird von `actuator_arbiter_node.py::
_effective_priority()` serverseitig auf `PRIORITY_RETURN_TO_SAFE`
zurückgestuft -- die Anfrage wird NICHT abgelehnt, nur die beanspruchte
Dringlichkeit korrigiert. Verhindert, dass ein LLM oder ein frei
befüllbares Action-Feld eine Notfallpriorität vortäuscht.

## Lease-Lebenszyklus

`acquire(resources, owner_id, priority, safety_ok, ttl_s, goal_id) ->
AcquireResult` ist eine **synchrone Sofortentscheidung** (gewährt/
abgelehnt), niemals ein wartender Aufruf -- kein Aufrufer hält je einen
Teil der angeforderten Ressourcen, während er auf den Rest wartet:
entweder werden ALLE angeforderten Ressourcen atomar gewährt, oder
keine. Das schließt Deadlocks strukturell aus.

- **Konflikt**: eine angeforderte Ressource ist bereits an einen anderen
  Owner mit GLEICHER oder HÖHERER Priorität vergeben -> `granted=False`,
  `conflicting_owners` gefüllt.
- **Präemption**: eine angeforderte Ressource ist an einen Owner mit
  NIEDRIGERER Priorität vergeben -> dessen Lease wird sofort entzogen,
  die neue Anfrage gewährt. Eine sicherheitskritische Lease (Priorität
  `<= PRIORITY_SAFETY_ABORT`) kann NIE per normalem `acquire()`
  präemptiert werden -- nur `emergency_revoke_all()` (siehe unten)
  entzieht sie.
- **`safety_ok=False`**: JEDE Anfrage wird abgelehnt, unabhängig von
  Priorität/Konflikten -- `actuator_arbiter_node.py` startet fail-closed
  (`safety_ok=False`, keine aktiven Leases), bis das erste frische
  `SafetyState`-Signal eintrifft.
- **`renew(lease_id, ttl_s)`**: verlängert eine bestehende Lease,
  idempotent-sicher (unbekannte/abgelaufene `lease_id` -> `False`, wirft
  nie).
- **`release(lease_id)`**: gibt eine Lease frei, ebenso idempotent.
- **`emergency_revoke_all(reason)`**: entzieht ALLE aktiven Leases
  sofort, unabhängig von Priorität/`safety_ok` -- ausgelöst von
  `actuator_arbiter_node.py::_on_safety_state()` bei
  `emergency_stop`/`bumper_active`. Deckt automatisch JEDE Ressource ab,
  inklusive `BASE` (siehe `docs/ACTUATOR_ARBITER.md`-Abschnitt
  "BASE-Lease/Motion Guard" unten) -- keine ressourcenspezifische
  Sonderbehandlung nötig.

## ROS2-Schnittstelle (`actuator_arbiter_node.py`)

Services: `~/acquire` (`AcquireActuatorLease`), `~/renew`
(`RenewActuatorLease`), `~/release` (`ReleaseActuatorLease`), `~/cancel`
(`CancelActuation`, siehe `docs/ACTION_CANCELLATION.md`). Topics:
`~/state` (`ActuatorState`, 1Hz), `~/diagnostics` (`String`),
`~/base_lease_valid` (`Bool`, absoluter Pfad
`/actuator_arbiter/base_lease_valid` -- von Motion Guard konsumiert,
siehe unten).

## BASE-Lease/Motion Guard-Integration

`motion_guard.py::MotionGuardInputs.base_lease_valid` (kein Default, wie
jedes andere Feld dort) ist ein zusätzliches, PFLICHTIGES Gate in
`evaluate_motion_guard()`, direkt nach `safety_allow_motion`: fehlt/ist
veraltet die BASE-Lease, wird JEDER von Null verschiedene Fahrbefehl
blockiert. Ein Stopp-Befehl kommt trotzdem immer durch, weil
`motion_guard_node.py` bei `allow=False` ohnehin IMMER explizit
`Twist()` (Nullgeschwindigkeit) publiziert statt den Kandidatenbefehl
einfach zu verwerfen.

`person_approach_node.py::_drive_to_pose()` erwirbt die BASE-Lease
(`PRIORITY_NAVIGATION`, Owner `"person_approach"`) VOR jedem gesendeten
Nav2-Ziel -- ohne gewährte Lease wird gar kein Ziel gesendet. Während
längerer Fahrten wird die Lease periodisch erneuert (alle 10s, TTL 20s);
schlägt eine Erneuerung fehl, wird die laufende Fahrt aktiv abgebrochen.
Freigabe in JEDEM Ausstiegspfad (Erfolg/Fehler/Zeitüberschreitung/
Cancel). Bumper/Not-Halt widerrufen die Lease bereits generisch über
`emergency_revoke_all()`.

## Serverseitiges Vertrauensmodell

`actuator_arbiter_node.py` ist der einzige Ort, der Prioritäten
tatsächlich durchsetzt -- ein Client kann in seiner Anfrage JEDE
Priorität eintragen, aber `_effective_priority()` korrigiert
unvertrauenswürdige Notfall-Ansprüche serverseitig (siehe oben). Das
Feld `owner_id` selbst ist NICHT kryptografisch abgesichert (kein
Node-Authentifizierungsmechanismus in ROS2 vorhanden, siehe oben) --
die Grenze ist organisatorisch: nur die im Projekt selbst verwendeten
Owner-Präfixe (`pepper_bridge`, `person_approach`, `motion_guard`,
`supervisor`, `actuator_arbiter`) werden als vertrauenswürdig behandelt.

## Getestet

66 Unit-Tests über drei Dateien (`test_actuator_arbiter.py`,
`test_resource_derivation.py`, `test_actuator_arbiter_node.py`, siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`): Konflikt/Präemption/
Safety-kritisch-nie-präemptierbar, `emergency_revoke_all()` bypasst
Priorität/`safety_ok`, Präferenzstufen-Rückstufung nicht
vertrauenswürdiger Owner, `TORSO`/`BASE`-gegenseitiger Ausschluss,
`renew()`/`release()`-Idempotenz. Weitere 12 Tests in
`test_person_approach_base_lease.py` für die BASE-Lease-Integration
(inkl. End-zu-Ende gegen ein Fake-Nav2). **Nicht live gegen echten
Pepper getestet** -- kein Roboter in dieser Session erreichbar.
