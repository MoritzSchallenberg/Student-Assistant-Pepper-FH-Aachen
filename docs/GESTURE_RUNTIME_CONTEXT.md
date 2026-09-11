# Gesture Runtime Context

Entwicklungsauftrag 04-B, AP8.2 (Grundlage) + AP8-R1.3 (Watchdog). Module:
`ihk_pepper_bridge/ihk_pepper_bridge/{bridge_node,gesture_execution_policy,safety_topics}.py`.

## Momentaufnahme statt gespeichertem Zustand

`RuntimeContext` (siehe `gesture_execution_policy.py`) ist eine reine,
vom Aufrufer vollständig befüllte Momentaufnahme. `None` bedeutet
**immer** "unbekannt/nicht geliefert" und wird fail-closed wie ein
ungültiger Wert behandelt, nie wie "kein Problem".

`bridge_node.py::_current_runtime_context()` baut sie aus fünf einzeln
mit eigenem Zeitstempel geführten Signalen (`FreshBool`/`FreshValue`,
siehe `safety_topics.py`):

| Signal | Fail-closed bei fehlend/veraltet |
| --- | --- |
| `safety_ok` | jede Hardwaregeste sperren |
| `nav2_moving` | als Bewegung behandeln, stationäre Gesten sperren |
| `mapping_active` | Kopfgesten sperren |
| `current_interaction_state` | Gesten mit Zustands-Allowlist sperren |
| `pepper_reachable` | Hardwaregeste sperren |

## Wann der Kontext geprüft wird

1. **Vor Autorisierung** (erste `authorize()`-Prüfung).
2. **Unmittelbar vor `transport.start()`** (zweite `authorize()`-Prüfung,
   nach Lease-Erwerb).
3. **Während der gesamten laufenden Geste, periodisch** — siehe
   Laufzeit-Watchdog unten (AP8-R1.3, neu).

## Laufzeit-Watchdog (AP8-R1.3)

**Bestätigter Fund (AP8-R1, Abschnitt 3.3):** die ersten beiden
Prüfzeitpunkte deckten den Zeitraum **während** einer laufenden
Bewegung nicht ab. `max_duration_s` begrenzte nur die kompilierte
Solltrajektorie, nicht die tatsächliche Ausführungszeit — eine wirklich
hängende Transportausführung (z.B. eine SSH-Verbindung, die nie
zurückkehrt) wurde dadurch nicht zuverlässig abgebrochen.

`bridge_node.py::_watchdog_check()` wird in **jeder** Iteration der
bestehenden Poll-Schleife (`GESTURE_POLL_INTERVAL_S = 0.1s`) aufgerufen,
solange eine Geste läuft. Er prüft, in dieser Reihenfolge:

1. Ist bereits ein Abbruchgrund gesetzt? → nichts tun (idempotent).
2. Ist der Node im Shutdown (`self._shutting_down`, gesetzt von
   `destroy_node()`)? → `NODE_SHUTDOWN`.
3. Ist die harte, absolute Zeitgrenze überschritten (`hard_deadline
   = Startzeit + expected_duration_s + GESTURE_WATCHDOG_TIMEOUT_MARGIN_S`,
   Marge = 5.0s)? → `TIMEOUT`.
4. Wurde die Lease widerrufen? → `LEASE_REVOKED`.
5. Nur für `HARDWARE_CAPABLE_PROFILES`: erneuter Aufruf von
   `GestureExecutionPolicy.authorize()` mit dem **aktuellen**
   `RuntimeContext` — **keine zweite, abweichende Sicherheitslogik**.
   Eine Ablehnung wird auf einen strukturierten `GestureCancelReason`
   übersetzt (`SAFETY_INVALID`/`EMERGENCY_STOP`/`BUMPER_ACTIVE`,
   `PEPPER_UNREACHABLE`, `NAVIGATION_STARTED`, `MAPPING_STARTED`,
   `INTERACTION_INVALID`, `LEASE_REVOKED`).

Der Watchdog setzt selbst **keine** neue Abbruchlogik — er setzt nur den
strukturierten Grund auf dem bestehenden `CancelSignal` (siehe
`docs/GESTURE_CANCELLATION_AND_RESTORE.md`); das eigentliche Abbrechen
(Interrupt-Kanal, `transport.cancel()`) übernimmt der bereits bestehende
`cancel_event`-Beobachtungspfad in `gesture_catalog.py::_play_v2()`.

`max_duration_s` ist damit ein **harter Laufzeitdeckel**: ein Transport
darf nicht unbegrenzt weiterlaufen, nur weil seine Solltrajektorie beim
Kompilieren innerhalb des Deckels lag.

## Warum `EMERGENCY_STOP`/`BUMPER_ACTIVE` unterscheidbar sind

`bridge_node.py` hält seit AP8-R1 zusätzlich zum abgeleiteten
`safety_ok`-Bool die **rohen** `SafetyState`-Felder
(`_last_emergency_stop`/`_last_bumper_active`). `_classify_safety_cancel_reason()`
übersetzt eine `safety_state_ungueltig_oder_unbekannt`-Ablehnung in den
präzisesten verfügbaren Grund — `EMERGENCY_STOP`, wenn das Flag zuletzt
aktiv war, sonst `BUMPER_ACTIVE`, sonst der generische `SAFETY_INVALID`
(z.B. fehlend/veraltet).
