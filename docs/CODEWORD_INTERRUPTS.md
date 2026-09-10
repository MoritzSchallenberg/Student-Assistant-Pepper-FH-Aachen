# Codeword Interrupts ("Eisenbahn") (AP7.1)

Ergänzt `docs/PRIVILEGED_VOICE_COMMANDS.md` (AP7, Router-Grundkonzept)
um die BT-seitige Verdrahtung (AP7.1.8/Commit 6/10).

## Eigenschaften

Das Codewort ("Eisenbahn"/`interrupt_and_look`) muss auch **während
eines aktiven Gesprächs** erkannt werden. Es ist **kein LLM-Befehl** --
die Erkennung ist deterministisch und läuft VOR jeder normalen
Dialogverarbeitung (`command_router_node.py`, wie jeder andere
Steuerbefehl auch). Es ist **rollenfrei**
(`authorization_status == "not_required"`, siehe `roles.py`) -- selbst
eine unbekannte Person kann es auslösen (bewusst, siehe
`test_scenario_c_codeword_works_during_an_active_conversation_for_anyone`
in `test_ap7_1_e2e_scenarios.py`).

## Bei gültiger Erkennung

Laufende LLM-Anfrage/`Say`/Geste/Follow-/Nav2-Aktion werden kontrolliert
abgebrochen (über den zentralen Aktuator-Arbiter, AP5B), betroffene
Leases sauber behandelt, Basisstillstand mit Timeout bestätigt, eine
FRISCHE Schallrichtung geprüft, der Kopf über `OrientToSound`
ausgerichtet, eine neue Personenzuordnung versucht, der vorherige
Gesprächskontext beendet -- Wechsel zu Begrüßung oder Idle je nach
Ergebnis.

**Das Codewort löst NIE eine direkte Fahrt aus.** Bei veralteter/
mehrdeutiger/nicht transformierbarer Schallrichtung bleibt der Kopf in
sicherer Position, Pepper reagiert nur neutral. Original-Audio-
Zeitstempel werden bis zum Behavior Tree durchgereicht (nicht durch den
BT-Tick-Empfangszeitpunkt ersetzt, siehe `WaitForFreshWakeword`s
`measured_at_sec`-Fund aus AP6.1).

## Behavior-Tree-Umsetzung

Neuer Knoten `WaitForAuthorizedInterruptCommand` (SyncActionNode)
liefert **dasselbe Portformat** (`event_id`, `azimuth_rad`,
`measured_at_sec`) wie das bestehende `WaitForFreshWakeword` --
dadurch können die bereits existierenden, getesteten Knoten
`OrientHeadToSound`/`FindPersonNearSoundRay`
**unverändert wiederverwendet** werden, kein neuer Kopforientierungs-/
Zuordnungscode nötig.

`CodewordInterruptSubtree`: `Sequence(WaitForAuthorizedInterruptCommand
→ IsHeadOrientationAllowed → OrientHeadToSound →
FindPersonNearSoundRay)`. Steht im Root-`ReactiveFallback` **über**
`FollowCommandSubtree`/`PersonInteractionLifecycleSubtree` --
der `ReactiveFallback` prüft diesen Zweig jeden Tick neu und
präemptiert (über `onHalted()`) eine laufende Follow-Fahrt/ein
laufendes Gespräch/eine laufende Geste, sobald das Codewort erkannt
wird -- exakt dasselbe Präemptionsprinzip wie `SafetySubtree`.

Exactly-once über `event_id` (begrenzter Cache, gleiches Muster wie
`WaitForFreshWakeword`) -- ein bereits verarbeitetes Codewort-Ereignis
löst nie ein zweites Mal aus.

## Verwandte Dokumente

`docs/PRIVILEGED_VOICE_COMMANDS.md`, `SCOPED_AUTHORIZATION.md`,
`INTERACTION_LIFECYCLE.md`.
