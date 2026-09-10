# Personeninteraktions-Lebenszyklus

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 10/11.
Implementierung: `ihk_pepper_behavior_tree/trees/pepper_main.xml`
(`PersonInteractionLifecycleSubtree`, `EndInteractionSubtree`),
`bt_nodes.hpp`/`bt_nodes.cpp`, `InteractionLifecycleState.msg`
(`ihk_pepper_interaction/interaction_lifecycle_state.py`).

## `PersonInteractionLifecycleSubtree`

Fasst `GreetAndApproachSubtree` (Begrüßen/Annähern, siehe
`docs/BEHAVIOR_TREE.md`) und `DialogueSubtree` (Gespräch) unter einem
`ReactiveFallback` zusammen, OHNE beide neu zu bauen. Ersetzt im
Root-`ReactiveFallback` die bisherigen zwei getrennten Einträge durch
einen benannten -- funktional identisch (verschachtelte Fallbacks
verhalten sich wie flache Fallbacks), macht den vollständigen
Lebenszyklus aber als EIN Konzept im Baum sichtbar:

```
Begrüßen → Annähern (+ CaptureOriginPose) → Gespräch →
Verabschieden → ReturnToOrigin → Aufräumen → IDLE
```

Kein zweites, paralleles Verwalten derselben Person möglich: beide
Zweige teilen denselben `target_track_id`-Blackboard-Eintrag, und
`IsConversationInactive`/`IsConversationReady` schließen sich
gegenseitig aus (derselbe `/interaction_state` kann nicht gleichzeitig
`IDLE` und `CONVERSATION_READY` sein).

## `InteractionLifecycleState.msg`

Sitzungs-Zustand (eine konkrete Person/Gruppe) mit 16 Werten (`IDLE`
… `ERROR`), unabhängig vom groben Supervisor-Zustand
(`InteractionState.msg`) -- unterschiedliche Granularität, beide
bestehen nebeneinander. Aktuell im Baum selbst noch NICHT aktiv
gesetzt/gelesen (siehe "Nicht Teil von AP7" unten) -- der Vertrag
existiert, die Verdrahtung folgt in einem künftigen Arbeitspaket.

## Nicht Teil von AP7 (Stand AP7-Abschluss -- inzwischen größtenteils
## durch AP7.1 geschlossen, siehe Abschnitt unten)

- ~~Codewort-/Rollen-/Gruppen-Routing ist NICHT in den Baum
  verdrahtet.~~ **AP7.1, Commit 6/7/10**: `CodewordInterruptSubtree`/
  `FollowCommandSubtree`/`GroupConversationSubtree` verbinden
  `command_router_node.py`/`group_tracking_node.py`/`FollowPerson`
  jetzt mit dem Baum.
- ~~Die volle Prioritätskette ... ist nur TEILWEISE im Baum
  abgebildet.~~ **AP7.1**: siehe "Aktualisierte Priorität" unten.
- ~~`MonitorParticipants`/Gruppenverlust-Behandlung ist nicht
  umgesetzt.~~ **AP7.1, Commit 7/10**: `MonitorParticipants` ist
  implementiert, siehe `GROUP_CONVERSATION_RUNTIME.md`.
- ~~Kein neuer BT-Knoten löst `FollowPerson` selbst aus.~~
  **AP7.1, Commit 6/10**: `StartAuthorizedFollow`, siehe
  `COMMAND_FOLLOW_LIFECYCLE.md`.

## AP7.1: vollständige Interaktionsorchestrierung

### Aktualisierte Priorität

Root-`ReactiveFallback` (`pepper_main.xml`): Safety > Battery >
**CodewordInterrupt** > **FollowCommand** > PersonInteractionLifecycle >
**GroupConversation** > Interaction > Presentation > IdleAttract.
Fett = neu in AP7.1. `GroupConversation` bewusst NACH
`PersonInteractionLifecycle` (siehe `GROUP_CONVERSATION_RUNTIME.md`
für die Begründung).

Priorität ist ausschließlich über die Tick-Reihenfolge/Präemption des
`ReactiveFallback` erzwungen -- kein LLM kann diese Reihenfolge
verändern (kein Code-Pfad von `ihk_pepper_llm_contracts` zum Baum).

### Origin-Bindung an die Interaktionsart (Abschnitt 3.4/16)

`OriginRecord`/`OriginStore` (`origin_session.py`) tragen seit Commit
8/10 zusätzlich `interaction_id`, `reason`, `map_generation_id`. Ein
Ursprung aus einer Follow-Sitzung (`interaction_id="authorized_follow"`)
kann strukturell NIE für eine Einzelgesprächs-Rückkehr
(`interaction_id="single_person_conversation"`) verwendet werden --
`validate()` lehnt einen Mismatch mit
`"ursprung_gehoert_anderer_interaktion"` ab. `map_generation_id` ist ein
rein lokaler Generationszähler (KEIN echter Kartenserver in dieser
Sitzung), erhöht bei jedem `invalidate_all()`-Aufruf -- Verteidigung in
der Tiefe zusätzlich zum bereits bestehenden vollständigen Löschen
aller Ursprünge bei Kartenwechsel/Neulokalisierung.

### Sichtbarer Fehlerzustand (Abschnitt 16 "Fehlerbehandlung")

`InteractionLifecycleState.msg` (in AP7 Commit 9/23 nur als Vertrag
definiert) wird seit Commit 8/10 tatsächlich veröffentlicht -- neuer
BT.CPP-Knoten `PublishInteractionLifecycleState` auf
`/interaction/lifecycle_state`. Bisher NUR für `state_name="ERROR"`
bei einem fehlgeschlagenen `ReturnToOriginViaBT` verdrahtet (in
`EndInteractionSubtree` UND `FollowCommandSubtree`, jeweils VOR dem
`AlwaysSuccessIdle`-Fallback-Zweig) -- macht einen bisher
stillschweigend absorbierten Fehler für Betriebspersonal sichtbar
(inkl. dem tatsächlichen `abort_reason`, neuer Output-Port auf
`ReturnToOriginViaBT`). Der Systemablauf selbst bleibt unverändert:
Basis bleibt stehen (`_drive_to_pose`s `finally`-Block, unverändert
seit AP2 AP10), keine Endlos-Wiederholschleife (BT.CPP-Sequence-mit-
Gedächtnis tickt `ReturnToOriginViaBT` pro Durchlauf genau einmal).
**Keine vollständige Zustandsübergangs-Nachbildung aller 16
Enum-Werte** -- weiterhin offen.

## Ehrlicher Stand (AP7.1)

`colcon test --packages-select ihk_pepper_behavior_tree`: unverändert
23 Tests, 0 Fehler, 0 Failures, 4 übersprungen über die Commits 6-8/10
hinweg (reine Knoten-Registrierungs-/Verdrahtungs-Commits, keine neuen
gtests nötig -- `PositionForGroup`/`ReturnToOriginViaBT` teilen sich den
bereits getesteten `waitForBoundedCancelConfirmation()`-Pfad). Mehrere
Live-Rauchtests (`bt_executor_node`, `person_approach_node`,
`face_identity_node`, `command_router_node` gemeinsam gestartet) pro
Commit bestätigt, siehe `DEVELOPMENT_ORDER_04_B_REPORT.md`. Kein echter
Pepper, kein echtes Gespräch, keine echte Nav2-Fahrt in dieser Sitzung.
