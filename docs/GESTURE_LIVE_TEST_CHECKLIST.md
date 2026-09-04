# Checkliste: Beaufsichtigter Live-Test einer Geste

Stand: 2026-09-04. Entwicklungsauftrag 3, AP14.
Werkzeug: `ros2 run ihk_pepper_bridge gesturectl live-test <name>` (siehe
`ihk_pepper_bridge/gesturectl.py`).

## Voraussetzungen (vom CLI selbst geprüft/erzwungen)

1. Die Geste ist `schema_version: 2` (v1-Gesten liefen bereits in
   früheren Aufträgen live, `live-test` deckt aktuell nur v2 ab).
2. `pepper_client.is_reachable()` liefert `True` -- ohne erreichbaren
   Pepper bricht der Befehl sofort ab, OHNE eine der folgenden Fragen zu
   stellen.
3. Die Geste wurde vorher erfolgreich mit `gesturectl dry-run <name>`
   geprüft (keine Compiler-/Validierungsfehler).

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
2. Bewegung wird über `QicliTrajectoryTransport` ausgeführt (derselbe
   Transport wie im Produktivbetrieb, siehe
   `docs/GESTURE_TRANSPORT.md`) -- NICHT über einen separaten
   "Testmodus"-Codepfad.
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

In dieser Session ist kein Pepper angeschlossen -- `gesturectl live-test`
konnte nicht ausgeführt werden. Alle 20 Kataloggesten bleiben bei
`draft`/`dry_run_validated` (siehe `docs/GESTURE_AUTHORING.md` für die
vollständige Tabelle). Diese Checkliste ist vorbereitet, aber nicht in
dieser Session durchlaufen worden.
