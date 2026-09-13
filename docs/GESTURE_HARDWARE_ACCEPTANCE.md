# Hardware-Abnahme: Gesten, Kopf, Systemgesten im Dialog

Stand: 2026-09-13. Entwicklungsauftrag 04-B, AP8.9, Commit 14/14.
Neues Dokument -- vorbereitet, in KEINER Session bis einschließlich
diesem Commit gegen echte Hardware durchlaufen (kein Pepper in dieser
Session erreichbar). Siehe auch `docs/GESTURE_LIVE_TEST_CHECKLIST.md`
(Ablauf für einen einzelnen `gesturectl live-test`-Aufruf),
`docs/RESPEAKER_HARDWARE_ACCEPTANCE.md` (Kopf-/Audio-Abnahme, Phase
A-D), `docs/NAVIGATION_SAFETY_ACCEPTANCE.md` (Nav2/production-Gate).

Dieses Dokument bündelt die Punkte, die für eine VOLLSTÄNDIGE
Hardware-Abnahme des Dialog-Gesten-Pfads (System-Gesten
`acknowledge_nod_small`/`thinking_loop_subtle` UND thematische v2-Gesten
im beaufsichtigten Dialog) tatsächlich einzeln nachgewiesen werden
müssen -- keiner dieser Punkte ist durch Offline-/Mock-Tests ersetzbar,
alle bleiben bis zu ihrem jeweiligen Test `hwverificationrequired`.

## Voraussetzung: Startmodus

Nur `mode=pepper_gesture_test` (isoliert, kein Perception/Dialog/BT --
ausschließlich einzeln per Action ausgelöste Gesten) oder
`mode=navigation_dry_run` (Dialog+Gesten real, Fahrt auf Sink umgebogen)
über `interaction_full_safe.launch.py`, jeweils MIT
`i_confirm_gesture_test_supervised:=true` (seit AP8.9 -- vorher hatten
beide Modi trotz `bridge_dry_run=false` KEINE Bestätigungshürde, siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP8.9). `mode=production`
verlangt zusätzlich `i_confirm_hardware_acceptance_complete:=true` nach
vollständiger, separater Abnahme (`docs/NAVIGATION_SAFETY_ACCEPTANCE.md`).
`navigation_live.launch.py` wird für KEINEN Punkt dieses Dokuments
gestartet.

## Abnahmepunkte (jeder einzeln `hwverificationrequired`, bis nachgewiesen)

1. **Rein lesendes Capture** (`gesturectl capture-sequence`/
   `capture-pose`): reales Gelenkwinkel-Auslesen über
   `PepperJointStateSource`, KEINE Bewegung. Nachweis: aufgezeichnete
   Sequenz zeigt plausible, mit einer manuellen Bewegung Peppers
   korrelierende Werte; `test_read_never_reaches_a_movement_method`
   bleibt strukturell gültig, ersetzt aber keinen echten Lesetest.
2. **Sichere erste v2-Testtrajektorie**: eine NEUE oder geänderte
   v2-Geste zuerst mit `speed_scale <= 0.4` (siehe
   `docs/GESTURE_LIVE_TEST_CHECKLIST.md`), NUR nach erfolgreichem
   `gesturectl dry-run`.
3. **Tatsächliches qicli-/NAOqi-Trajektorienverhalten**: entspricht die
   reale Bewegung der kompilierten Zeitachse (Start-/Endpose, grobe
   Geschwindigkeit)? Kein Ruckeln/keine Kollision mit dem eigenen Körper.
4. **Startpose und normale Beendigung**: Geste startet aus der
   dokumentierten Startpose (explizit/Capture-Metadaten/
   `NEUTRAL_STAND_POSE`), endet in der erwarteten Endpose;
   `restore_after: true` kehrt tatsächlich sichtbar zur Startpose zurück.
5. **Cancel mit `on_cancel: hold`**: ein während der Bewegung gesendetes
   Cancel hält Pepper tatsächlich in der aktuellen (nicht der
   ursprünglichen) Pose, KEIN automatisches Zurückfahren.
6. **Zulässiger normaler Cancel + separat geprüftes Restore**: ein
   `NORMAL_USER_CANCEL` (siehe `docs/GESTURE_CANCELLATION_AND_RESTORE.md`
   für die exakte Matrix) erlaubt anschließend ein separates,
   EIGENSTÄNDIG ausgelöstes Restore -- dieses Restore selbst wird als
   EIGENE Bewegung nach denselben Regeln geprüft (Startpose-Prüfung,
   Compiler/Timing), nicht blind vertraut.
7. **Codewortpräemption** ("Eisenbahn" über den bestehenden
   `/interaction/authorized_command`-Pfad, `command: interrupt_and_look`):
   bricht eine laufende Geste/Sprache tatsächlich ab, KEIN Restore danach
   (siehe Matrix), Kopf richtet sich wie dokumentiert aus.
8. **Not-Stopp/Bumper ohne Restore**: `emergency_stop`/`bumper_active`
   bricht sofort ab, NIE gefolgt von einem automatischen Restore,
   unabhängig vom Zustand davor.
9. **Unabhängiger Interrupt-Kanal**: `PepperInterruptChannel` (zweite
   SSH-Verbindung) reagiert nachweislich SCHNELLER als der Hauptkanal,
   wenn Letzterer gerade in einem langen `exec_command()` hängt.
10. **Reale Reaktionszeit und physischer Stillstand**: gemessene Zeit
    zwischen Cancel-Anforderung und tatsächlichem Stillstand (Stoppuhr/
    Video, keine geschätzten Werte); erst hier wird "Stufe 5" (physischer
    Stillstand, hardwarebestätigt, siehe
    `docs/DIALOGUE_GESTURE_LIFECYCLE.md` Abschnitt 7) tatsächlich
    erreicht -- kein Offline-Test darf das je behaupten.
11. **Arm-/Tablet-/Torso-Abstände**: reale Mindestabstände während JEDER
    neuen/geänderten Trajektorie (kein Kontakt mit Tablet-Halterung,
    Torso, Kabeln).
12. **RealSense-/ReSpeaker-Ausrichtung bei Kopfbewegung**: nach jeder
    Kopfbewegung (System- oder Katalog-Geste) liefern Kamera/Mikrofon-
    Array weiterhin plausible, korrekt ausgerichtete Daten (kein
    verkipptes Sichtfeld/keine falsch interpretierte Richtungsschätzung).
13. **Breathing-Verhalten**: die bestehende Atemroutine pausiert/setzt
    korrekt rund um jede Gestenausführung fort, OHNE die
    Restore-Matrix-Sperren (Punkt 6-8) zu umgehen.
14. **Systemgesten im beaufsichtigten Dialog**: `acknowledge_nod_small`/
    `thinking_loop_subtle` real im Dialog ausgelöst -- Zeitpunkt,
    Wiederholung, sichtbares Abbrechen bei Cancel (siehe
    `docs/DIALOGUE_GESTURE_LIFECYCLE.md` Abschnitt 2) MIT echter
    Hardware beobachtet, nicht nur simuliert.

## Protokoll je tatsächlich durchgeführtem Test

Für jeden der obigen Punkte, sobald er tatsächlich ausgeführt wird, ist
mindestens Folgendes festzuhalten (kein Punkt gilt ohne vollständiges
Protokoll als abgenommen):

| Feld | Beispiel |
|---|---|
| Datum und Bediener | `2026-XX-XX, <Name>` |
| Pepper-Modell und Firmware | `Pepper 1.8a, NAOqi 2.5.10.x` |
| getesteter Commit | `git rev-parse HEAD` zum Testzeitpunkt |
| Datei-Hash und Plan-Fingerprint | `sha256sum config/gestures/<name>.yaml`, kanonischer Fingerprint aus `gesturectl verify-offline` |
| Testmodus und Freigaben | z.B. `pepper_gesture_test`, `i_confirm_gesture_test_supervised=true` |
| Startpose und Speed-Scale | z.B. `neutral_stand_pose`, `speed_scale=0.4` |
| Beobachtung | Freitext, ehrlich (auch Auffälligkeiten) |
| Cancel-/Stopp-Ergebnis | z.B. "Cancel bei t=1.2s, Stillstand bei t=1.4s (Video)" |
| Auffälligkeiten | z.B. "keine" / genaue Beschreibung |
| dokumentierte Statusentscheidung | z.B. `tested_status` NICHT geändert / auf `live_validated` gesetzt |

**Nie behaupten**: ein konkreter Mid-Servo-Stopp sei bereits bewiesen,
nur weil Punkt 10 grob "schnell genug" wirkte -- die tatsächliche
Transport-/Hardware-Granularität (Keyframe-/Segment-Ebene vs. echter
Mid-Servo-Stopp) muss für JEDE neue/geänderte Geste separat geprüft
werden, ein einzelner Test verallgemeinert sich nicht automatisch auf
alle anderen.

## Aktueller Stand

Alle 14 Punkte oben sind `hwverificationrequired` -- keiner wurde in
dieser oder einer früheren Session gegen echte Hardware nachgewiesen
(kein Pepper erreichbar). Dieses Dokument ersetzt keine Freigabe --
es macht nur explizit, WAS konkret noch fehlt, bevor irgendeine der 14
Aussagen als hardwareverifiziert gelten darf.
