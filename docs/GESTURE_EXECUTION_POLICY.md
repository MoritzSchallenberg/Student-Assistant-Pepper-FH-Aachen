# Gesture Execution Policy

Entwicklungsauftrag 04-B, AP8.1 (Grundlage) + AP8-R1 (Korrekturen). Modul:
`ihk_pepper_bridge/ihk_pepper_bridge/gesture_execution_policy.py`.

## Warum die Bridge die autoritative Grenze ist

Filter in `gesture_memory_node`, `run_dialogue_action_server` oder dem
Behavior Tree sind **zusätzliche**, aber **nicht die letzte**
Sicherheitsschicht. Ein direkter Aufruf von `/pepper_bridge/play_gesture`
(egal ob über ein manuelles Tool, einen Bug im Aufrufer, oder einen fest
im Baum eingetragenen Gestennamen) muss an `pepper_bridge` selbst
abgelehnt werden können — unabhängig davon, was ein Aufrufer vorher schon
gefiltert hat. `GestureExecutionPolicy.authorize()` ist deshalb die
**einzige** Stelle, die über `tested_status`, `speed_scale` und
Laufzeitkontext entscheidet; kein Parameter, kein Actionfeld und kein
`system_only`-Flag kann diese Prüfung umgehen.

## Zwei Aufrufzeitpunkte

`authorize()` wird **zweimal** aufgerufen:

1. **Vor Lease-Erwerb** — verhindert, dass eine von vornherein
   unzulässige Anfrage überhaupt eine Ressource belegt.
2. **Unmittelbar vor Transportstart** — der Laufzeitkontext kann sich
   zwischen beiden Aufrufen geändert haben (Safety-Ereignis, Nav2 startet,
   Lease wird widerrufen). Eine Ablehnung hier gibt die gerade erworbene
   Lease sofort wieder frei, **ohne** den Ausführungs-Thread je zu
   starten.

Eine Ablehnung startet an keiner Stelle einen Hintergrund-Thread, erwirbt
keine Lease und berührt weder SSH noch qicli.

## Speed-Scale: genau eine kanonische Auflösung (AP8-R1.1)

**Bestätigter Fund (AP8-R1, Abschnitt 3.1):** die Policy interpretierte
`speed_scale == 0.0` bereits korrekt als "Katalogdefault verwenden", aber
der Bridge-Ausführungspfad selbst rechnete unabhängig davon mit
`goal_handle.request.speed_scale or 1.0` — die Policy konnte z.B. mit
`0.6` rechnen, während `GestureCatalog.play()`/der Compiler tatsächlich
`1.0` bekamen.

`gesture_execution_policy.py::resolve_speed_scale(gesture,
requested_speed_scale) -> SpeedScaleResolution` ist jetzt die **einzige**
Stelle, die diese Auflösung kennt:

```text
requested_speed_scale == 0.0 (oder None)  -> gesture.speed_scale_default
requested_speed_scale < 0.0                -> ablehnen (speed_scale_negativ)
requested_speed_scale ist NaN oder inf     -> ablehnen (speed_scale_ungueltig)
requested_speed_scale ausserhalb des
    zulaessigen positiven Bereichs         -> ablehnen (speed_scale_ausserhalb_bereich),
                                               NICHT klemmen
requested_speed_scale gueltig              -> exakt diesen Wert verwenden
```

`0.0` ist der **einzige** Default-Sentinel (der ROS2-Actionfeld-
Standardwert für ein nicht gesetztes `float64`-Feld). Ein negativer Wert
ist **kein** weiterer Sentinel, sondern ein sicherheitsrelevanter Fehler
und wird abgelehnt.

`GestureCatalog.play()`/`gesture_catalog.py::validate_speed_scale()`
nutzt **dieselbe** Grenzprüfung (dieselben `MIN_SPEED_SCALE_V1/V2`,
`MAX_SPEED_SCALE_V1/V2`) — vorher klemmte `play()` einen außerhalb
liegenden Wert still auf den Deckel (`speed_scale=100.0` wurde
stillschweigend zu `1.5`); jetzt wird ein solcher Wert **abgelehnt**,
nicht verfälscht.

### Warum nur einmal aufgelöst wird

`bridge_node.py::_execute_gesture()` berechnet den effektiven Wert genau
zweimal — einmal in der ersten `authorize()`-Entscheidung (für die
Lease-TTL, da die Lease vor der zweiten Prüfung erworben werden muss),
und ein zweites Mal in der zweiten `authorize()`-Entscheidung. **Ab der
zweiten Entscheidung ist `second_decision.effective_speed_scale`
verbindlich** — dieser Wert wird unverändert an `GestureCatalog.play()`,
den `KinematicCompiler`, den `TrajectorySafetyReport` und den
Watchdog weitergereicht, nie erneut unabhängig berechnet. Weicht der
zweite Wert unerwartet vom ersten ab (beide müssten für dieselbe Anfrage
deterministisch identisch sein), wird die Ausführung sicherheitshalber
abgelehnt (`speed_scale_inkonsistent`).

## Ausführungsprofile

| Profil | Minimaler `tested_status` | Berührt Hardware? |
| --- | --- | --- |
| `offline_mock` | `draft` | nie (strukturell erzwungen) |
| `offline_preview` | `draft` | nie (strukturell erzwungen) |
| `supervised_hardware_test` | `dry_run_validated` | ja, nur mit expliziten Gates |
| `production` | `live_validated` | ja |

`HARDWARE_CAPABLE_PROFILES = {supervised_hardware_test, production}` —
nur diese beiden Profile werten den `RuntimeContext` überhaupt aus;
`offline_mock`/`offline_preview` erzwingen `effective_dry_run=True`
unabhängig vom rohen `dry_run`-Parameter.

## v1-Gesten bleiben in `production` gesperrt (AP8-R1.9)

**Bestätigter Fund (AP8-R1, Abschnitt 3.6):** der v1-Transport
(`GestureCatalog._play_v1()`) führt mehrere blockierende `set_angle()`-
Aufrufe sequenziell aus, prüft Cancellation nur *zwischen* zwei
Schritten (nie *während* eines laufenden `set_angle()`-Aufrufs) und hat
keinen Laufzeit-Watchdog innerhalb eines einzelnen Schritts. Damit besitzt
v1 nicht dieselben Sicherheitsgarantien wie v2.

`bridge_node.py::_execute_gesture()` lehnt deshalb **jede** Geste mit
`schema_version == 1` im Profil `production` **strukturell** ab —
noch vor der eigentlichen `authorize()`-Prüfung, mit dem stabilen Grund
`legacy_v1_not_safely_interruptible`. `t_pose.yaml` behält seinen
historischen `tested_status: live_validated` (er beschreibt weiterhin den
**damals** geprüften v1-Ablauf), aber dieser Status kann die neue
Laufzeitsperre nicht umgehen. v1 bleibt in `supervised_hardware_test`
(mit menschlicher Aufsicht) und `offline_mock`/`offline_preview`
nutzbar.

Empfohlener weiterer Weg (noch nicht durchgeführt, `hwverificationrequired`):
`t_pose` kontrolliert auf v2 migrieren, Startpose/synchrone Trajektorie
prüfen, Status wegen des geänderten Transportpfads auf `draft`
zurücksetzen, Offline-Evidenz erzeugen, getrennt beaufsichtigt auf Pepper
testen, erst danach wieder `live_validated` setzen.

## `max_duration_s` gilt in jedem Profil

Die kinematische Sicherheitsgrenze `max_duration_s` (gegen die
`effective_speed_scale`-skalierte `expected_duration_s`) gilt
unabhängig vom Profil — auch offline. Sie begrenzt aber nur die
**kompilierte Solltrajektorie**; die tatsächliche Ausführungszeit wird
zusätzlich vom Laufzeit-Watchdog begrenzt (siehe
`docs/GESTURE_RUNTIME_CONTEXT.md`).

## Ressourcenbelegung ist keine Bewegungsfreigabe (Entwicklungsauftrag 04-B, AP8-R3)

`GestureExecutionPolicy.authorize()`/`resources_for_gesture()`
beantworten NICHT, ob Kopf/Arme/Torso im aktuellen Modus überhaupt
bewegt werden dürfen — eine erfolgreiche Autorisierung UND ein
erworbenes Lease sind notwendig, aber nicht hinreichend. Eine
zusätzliche, restriktive Schicht (`bridge_node.py::_resource_motion_denied()`,
neue read_only-Parameter `allow_head_motion`/`allow_arm_motion`/
`allow_torso_motion`) prüft VOR Lease-Erwerb zusätzlich, ob die
betroffenen Ressourcen tatsächlich freigegeben sind — wirkungslos für
`offline_mock`/`offline_preview` (dieselbe Ausnahme wie hier), aktiv für
`supervised_hardware_test`/`production`. Details:
`docs/AP8_R3_RUNTIME_HARDENING.md`.
