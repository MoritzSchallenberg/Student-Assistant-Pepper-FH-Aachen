# Checkliste: Beaufsichtigter Live-Test einer Geste

Stand: 2026-09-11. Entwicklungsauftrag 3, AP14; Codepfad seit
Entwicklungsauftrag 04-B, AP8-R2 (Abschnitt 3.11) geändert.
Werkzeug: `ros2 run ihk_pepper_bridge gesturectl live-test <name>` (siehe
`ihk_pepper_bridge/gesturectl.py`).

## Voraussetzung: Bridge läuft bereits im Testprofil

**Neu seit AP8-R2**: `live-test` löst KEINE Bewegung mehr direkt über
`KinematicCompiler`/`QicliTrajectoryTransport` aus (das umging bisher
Ausführungsrichtlinie/Validator/Lease/Watchdog/Cancel/Quarantäne
vollständig). Stattdessen muss die Bridge VORHER separat gestartet sein:

```
ros2 run ihk_pepper_bridge bridge_node --ros-args \
  -r __ns:=/pepper_bridge \
  -p dry_run:=false \
  -p execution_profile:=supervised_hardware_test
```

`live-test` spricht danach ausschließlich die reguläre `PlayGesture`-
Action dieser Bridge an (`/pepper_bridge/play_gesture`, Namespace über
`--bridge-namespace` änderbar) -- exakt derselbe Codepfad wie im
Normalbetrieb, mit denselben Sicherungen.

## Voraussetzungen (vom CLI selbst geprüft/erzwungen)

1. Die Geste ist `schema_version: 2` (v1-Gesten liefen bereits in
   früheren Aufträgen live, `live-test` deckt aktuell nur v2 ab).
2. `pepper_client.is_reachable()` liefert `True` -- ohne erreichbaren
   Pepper bricht der Befehl sofort ab, OHNE eine der folgenden Fragen zu
   stellen.
3. Die Geste wurde vorher erfolgreich mit `gesturectl dry-run <name>`
   geprüft (keine Compiler-/Validierungsfehler).
4. Die Bridge läuft bereits erreichbar im Profil
   `supervised_hardware_test` (siehe oben) -- sonst bricht `live-test`
   NACH der Checkliste, aber VOR jeder Aktion mit einem klaren Fehler ab
   (`PlayGesture-Action ... nicht erreichbar`).

## Interaktive Checkliste (vom CLI abgefragt, JEDE Frage muss explizit
## mit "ja" beantwortet werden -- jede andere Antwort bricht sofort ab)

1. **Ist der Armraum um Pepper vollständig frei?** Keine Person, kein
   Gegenstand innerhalb der maximalen Armreichweite (~80cm um Pepper).
2. **Ist ein Bediener direkt am Not-Aus/Not-Stopp positioniert?** Die
   Person, die den Test durchführt, muss den Not-Stopp OHNE
   Positionswechsel erreichen können.
3. **Ist Pepper sicher aufgestellt?** Auf ebenem Boden, nicht auf einer
   Rampe/Kante, Ladekabel nicht im Bewegungsraum der Arme.
4. **Wurde die Geste bereits per `gesturectl dry-run` erfolgreich
   geprüft?** (Compiler-/Beschleunigungs-/Geschwindigkeitsprüfung muss
   fehlerfrei durchgelaufen sein, siehe `docs/GESTURE_TRANSPORT.md`.)

Eine einzige Antwort ungleich exakt `ja` (Groß-/Kleinschreibung
unerheblich) bricht den gesamten Ablauf ab -- KEINE Bewegung wird
ausgelöst.

## Ablauf nach bestätigter Checkliste

1. **Erster Durchgang IMMER mit `speed_scale <= 0.4`** (vom CLI
   erzwungen, nicht überschreibbar außer über `--full-speed`).
2. Bewegung wird über die reguläre `PlayGesture`-Action der laufenden
   Bridge ausgelöst (derselbe Codepfad -- inkl. Ausführungsrichtlinie,
   Validator, Aktuator-Lease, Watchdog, Cancel-Behandlung und
   Ressourcen-Quarantäne -- wie im Produktivbetrieb, siehe
   `docs/GESTURE_TRANSPORT.md`) -- NICHT über einen separaten
   "Testmodus"-Codepfad und NICHT über einen direkten Transport-Aufruf.
3. Nach erfolgreichem, unauffälligem ersten Durchgang: optional
   `gesturectl live-test <name> --full-speed`, um mit
   `speed_scale_default` (oder einem expliziten `--speed-scale`, max.
   `MAX_SPEED_SCALE_V2 = 1.5`) zu wiederholen.
4. Bei jeder Auffälligkeit (unerwartete Bewegung, Geräusch, Berührung
   eines Hindernisses): **sofort Not-Stopp**, Test abbrechen, NICHT
   wiederholen, bevor die Ursache geklärt ist.

## Nach dem Test

`gesturectl live-test` setzt **NIEMALS automatisch**
`tested_status: live_validated` in der YAML -- das bleibt ein bewusster,
manueller Schritt, um kein versehentlich "still als getestet markiert"
zu riskieren. Nach einem erfolgreichen, beaufsichtigten Test (BEIDE
Durchgänge, langsam UND mit voller Geschwindigkeit) trägt der Bediener
von Hand in `config/gestures/<name>.yaml` ein:

```yaml
tested_status: live_validated
tested_date: "<Datum des Tests>"
test_note: "Live getestet: <kurze Beschreibung, wer/was beobachtet wurde>"
```

## Ehrlicher Stand dieser Session

In keiner Session bis einschließlich Entwicklungsauftrag 04-B, AP8
(Commit 11/14) war ein Pepper angeschlossen -- `gesturectl live-test`
wurde nicht gegen echte Hardware ausgeführt. Der Katalog umfasst
mittlerweile 24 Gesten (`t_pose` `live_validated` -- historischer
v1-Sonderfall, v1 bleibt strukturell aus `production` gesperrt; 6
weitere `dry_run_validated`; der Rest `draft`) -- die aktuelle,
automatisch erzeugte Übersicht steht in
`docs/GESTURE_CATALOG_INVENTORY.md` (Reproduktionsbefehl:
`python3 scripts/generate_gesture_inventory.py`). Diese Checkliste ist
vorbereitet, aber weiterhin in keiner Session durchlaufen worden.
