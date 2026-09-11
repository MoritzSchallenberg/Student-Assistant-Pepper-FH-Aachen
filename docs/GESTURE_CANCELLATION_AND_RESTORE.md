# Gesture Cancellation and Restore

Entwicklungsauftrag 04-B, AP8.3 (Grundlage) + AP8-R1.4/1.5/1.6/1.7
(strukturierte Gründe, Restore-Matrix, Thread-/Lease-Lebenszyklus,
Revocation-Race). Module: `ihk_pepper_bridge/ihk_pepper_bridge/
{gesture_cancellation,gesture_catalog,bridge_node}.py`.

## Drei unterscheidbare Zustände

```text
cancel_requested                       -- eine Abbruchanfrage liegt vor
cancel_accepted_or_sent                -- ROS-Cancel/Interrupt wurde gesendet
physical_or_transport_completion_confirmed -- der Transport-Thread ist NACHWEISLICH beendet
```

Eine ROS2-Cancel-Bestätigung (`goal_handle.canceled()`) ist **kein**
Hardwarestillstand. Eine Lease-Revocation-Bestätigung ist **nur** eine
Aussage über den Arbiter-Zustand. `qicli`/SSH-Interrupt bleibt Best-Effort,
bis ein echter Hardwaretest den physischen Stopp beweist (siehe
`docs/ACTION_CANCELLATION.md`).

## Strukturierte Cancellation-Gründe (AP8-R1.4)

**Bestätigter Fund (AP8-R1, Abschnitt 3.5):** `cancel_event` transportierte
bisher nur den booleschen Zustand "abbrechen" — ROS-Cancel, Timeout,
Lease-Widerruf, Präemption, Not-Stopp, Bumper, Nav2-/Mapping-/
Interaktionskonflikt, Pepper-Verbindungsverlust, Transportfehler und
Node-Shutdown waren nicht unterscheidbar. `on_cancel=restore` konnte
deshalb nicht für jeden Grund korrekt entscheiden.

`gesture_cancellation.py::CancelSignal` ersetzt den bloßen
`threading.Event` durch einen Träger für **genau einen**, einmal
gesetzten `GestureCancelReason`:

```text
NORMAL_USER_CANCEL   CODEWORD_INTERRUPT   TIMEOUT
LEASE_REVOKED        PREEMPTED            SAFETY_INVALID
EMERGENCY_STOP       BUMPER_ACTIVE        NAVIGATION_STARTED
MAPPING_STARTED      INTERACTION_INVALID  PEPPER_UNREACHABLE
TRANSPORT_FAILED     NODE_SHUTDOWN
```

`CancelSignal.set(reason)` ist **idempotent**: nur die erste Anfrage legt
den Grund fest, jede weitere (auch mit einem anderen Grund) ändert ihn
nicht mehr. Das erfüllt sowohl "der erste sicherheitsrelevante
Cancel-Grund gewinnt" als auch "ein späterer normaler Cancel darf einen
bereits gesetzten Not-Stopp-Grund nicht überschreiben", ohne eine
gesonderte Prioritätstabelle zwischen den Gründen zu brauchen.
`CancelSignal` bleibt duck-type-kompatibel zu einem `threading.Event`
(`is_set()`/`wait()`) — bestehender Code, der nur `is_set()` liest,
funktioniert unverändert; ein einfaches `threading.Event` ohne
`.reason`-Attribut gilt beim Abbruch weiterhin wie `NORMAL_USER_CANCEL`
(Rückwärtskompatibilität).

## Restore-/Breathing-Matrix (AP8-R1.5)

| Ende/Grund | Restore erlaubt? | Breathing reaktivieren? |
| --- | ---: | ---: |
| normale erfolgreiche Beendigung, Safety gültig | gemäß `restore_after` | ja (bei frischer Safety-Bestätigung) |
| `NORMAL_USER_CANCEL` + `on_cancel=restore` + Lease/Safety gültig | ja | ja |
| `NORMAL_USER_CANCEL` + `on_cancel=hold` | nein | nur bei sicherem Zustand |
| `CODEWORD_INTERRUPT` | nein | nur nach erneuter Safety-Prüfung |
| `TIMEOUT` | nein | nein |
| `LEASE_REVOKED`/`PREEMPTED` | nein | nein |
| `EMERGENCY_STOP`/`BUMPER_ACTIVE` | nein | nein |
| `SAFETY_INVALID` | nein | nein |
| `NAVIGATION_STARTED`/`MAPPING_STARTED`/`INTERACTION_INVALID` | nein | nein |
| `PEPPER_UNREACHABLE` | nein | nein |
| `TRANSPORT_FAILED` | nein | nein |
| `NODE_SHUTDOWN` | nein | nein |

Implementiert als zwei reine Funktionen in `gesture_cancellation.py`:
`restore_allowed(reason, gesture_on_cancel, safety_ok_now)` und
`breathing_may_reactivate(reason, safety_ok_now)`. **Nur**
`NORMAL_USER_CANCEL` kann überhaupt zu `restore_allowed()==True` führen
(zusätzlich an `on_cancel=="restore"` UND einen frischen, zum
Abbruchzeitpunkt gültigen Sicherheitszustand gebunden). Jeder andere
Grund verbietet Restore **unbedingt**.

`GestureCatalog._play_v2()`/`_play_v1()` nutzen diese Matrix im
`finally`-Block: eine **normale** Beendigung (kein Abbruch) restauriert
weiterhin gemäß `restore_after` unverändert; eine **abgebrochene**
Geste ruft `restore_allowed()`/`breathing_may_reactivate()` mit dem
`CancelSignal.reason` und dem Rückgabewert von `safety_ok_for_restore_fn()`
auf.

### Warum Breathing nicht bedingungslos reaktiviert wird

`setBreathing(True, ...)` kann selbst neue Gelenkbewegung auslösen. Nach
einem Not-Stopp, Bumper, ungültigen SafetyState oder unbestätigten
Transportabbruch darf Breathing deshalb **nicht** bedingungslos im
`finally` reaktiviert werden — es bleibt deaktiviert, bis ein frisch
bestätigter sicherer Zustand oder ein Bedienereingriff vorliegt.

### Reales Beispiel: v1-Migration (Commit 8/12)

Vor AP8-R1 restaurierte `_play_v1()`/`_play_v2()`s `finally`-Block
**unbedingt**, sobald ein Snapshot existierte — auch nach einem
sicherheitsbedingten Abbruch, und selbst nach einem reinen
Transportfehler (`TRANSPORT_FAILED`). Das wurde korrigiert: ein
Transportfehler restauriert jetzt **nicht** mehr automatisch und
reaktiviert Breathing **nicht** mehr automatisch (siehe
`test_transport_failure_never_restores_or_reactivates_breathing_v1/v2`
in `test_gesture_catalog_v2.py`) — vorher hätte ein zweiter,
automatischer Bewegungsbefehl nach einem bereits fehlgeschlagenen
Transport ein unkontrolliertes Sicherheitsrisiko dargestellt.

## Kein Thread darf nach Action-Ende unbemerkt weiterlaufen (AP8-R1.6)

**Bestätigter Fund (AP8-R1, Abschnitt 3.4):** die Bridge wartete nur
eine begrenzte Cancel-Grace-Zeit (`GESTURE_CANCEL_GRACE_S`) auf
`done_event`. War der Transport danach weiterhin aktiv, wurde die Action
trotzdem beendet und die Lease freigegeben, obwohl der Hintergrund-Thread
noch qicli-Aufrufe, Restore oder weitere Bewegungen ausführen konnte.

`bridge_node.py::_execute_gesture()` unterscheidet jetzt explizit:

- **Transport bestätigt innerhalb der Grace-Zeit beendet**
  (`done_event.is_set()`): normaler Cleanup-Pfad — `gesture_in_progress`
  auf `False`, Registrierung entfernt, Lease freigegeben.
- **Transport NICHT bestätigt beendet**: die Action wird mit
  `success=False, error_message="cancel_unconfirmed"` beendet, **aber**:
  - die Lease wird **nicht** freigegeben (blockiert dadurch automatisch
    jedes zweite Ziel auf denselben Ressourcen über die bestehende
    Arbiter-Konfliktprüfung — kein zweiter Mechanismus nötig),
  - die Lease-ID wird in `_quarantined_lease_ids` aufgenommen, sodass
    `_safety_ok_for_restore()` für sie **fail-closed** `False` liefert —
    ein Thread, der *nach* dieser Rückgabe doch noch mit
    `on_cancel=restore` endet, kann keine Restore-Trajektorie mehr
    auslösen,
  - ein separater Daemon-Thread (`_quarantine_unconfirmed_execution()`)
    wartet **unbegrenzt** auf das tatsächliche Thread-Ende und holt den
    Cleanup (Lease-Freigabe, Registrierung entfernen) dann **genau
    einmal** nach.

Ein `finally`-Fallback (`if lease_id not in self._quarantined_lease_ids`)
stellt sicher, dass auch eine unerwartete Exception vor dem regulären
Quarantäne-Pfad niemals zu einer sofortigen Lease-Freigabe führt, solange
`done_event` nicht bestätigt gesetzt ist.

## Lease-Revocation-Race geschlossen (AP8-R1.7)

**Bestätigter Fund (AP8-R1, Abschnitt 3.8):** zwischen (1) Prüfung, ob
die neu erworbene Lease bereits widerrufen wurde, (2) der zweiten
Policy-Prüfung und (3) der Registrierung des `cancel_event` bestand ein
kleines Zeitfenster — traf die Revocation genau dort ein, wurde die
Lease-ID zwar in `_revoked_lease_ids` gespeichert, aber kein
`cancel_event` gefunden; die Geste konnte anschließend vollständig
durchlaufen.

Fix: `_active_execution_lock` (ein `threading.Lock`) schützt
`_active_gesture_cancel_events`/`_revoked_lease_ids` gemeinsam für
`_on_lease_revoked()` (läuft auf dem ROS-Subscription-Thread) und
`_execute_gesture()` (Action-Thread):

1. `_register_active_execution(lease_id, cancel_signal)` registriert das
   `CancelSignal` **sofort** nach Lease-Erwerb (nicht erst nach der
   zweiten Prüfung) und meldet unter demselben Lock zurück, ob die Lease
   zu diesem Zeitpunkt bereits widerrufen wurde.
2. Die zweite `authorize()`-Prüfung erhält dieses Ergebnis als
   `lease_revoked` im `RuntimeContext`.
3. **Unmittelbar vor Transportstart** wird `_is_lease_revoked(lease_id)`
   ein weiteres Mal unter Lock geprüft — schließt das (kleine, aber
   reale) Fenster zwischen der zweiten Prüfung und dem tatsächlichen
   Threadstart.

Ein Widerruf im Fenster zwischen Lease-Erwerb und Transportstart
verhindert den Start vollständig (zwei Offline-E2E-Varianten in
`test_ap8r1_offline_e2e.py::test_scenario_h_*` decken beide Zeitpunkte
ab). Ein Widerruf während der Ausführung bricht das exakt betroffene
Ziel ab (bestehender Mechanismus aus AP8.3, unverändert). Ein alter oder
fremder Widerruf beeinflusst nie ein späteres/anderes Ziel. Doppelte
Nachrichten bleiben idempotent (`CancelSignal.set()`).

## Same-owner/different-goal Konflikte (AP8.3, unverändert seit Commit 4/11)

`actuator_arbiter.py::acquire()`s Ausschlussbedingung erfordert sowohl
übereinstimmenden `owner_id` **als auch** übereinstimmenden, nicht-leeren
`goal_id`, um eine Lease als "dasselbe, erneut angefordertes Ziel" zu
behandeln — zwei Ziele desselben Eigentümers mit unterschiedlichem
`goal_id` konfliktieren weiterhin korrekt bei überlappenden Ressourcen.
