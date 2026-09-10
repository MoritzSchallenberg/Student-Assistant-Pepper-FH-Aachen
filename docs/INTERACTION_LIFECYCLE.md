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

## Nicht Teil von AP7 (ehrlich offen)

- **Codewort-/Rollen-/Gruppen-Routing ist NICHT in den Baum
  verdrahtet.** `command_router_node.py`/`group_tracking_node.py`/
  `FollowPerson` bleiben eigenständige, einzeln getestete ROS2-Nodes
  außerhalb des Baums (`audio_focus_node.py`/`person_approach_node.py`
  konsumieren deren Ausgaben bereits direkt, der Baum selbst nicht).
- Die volle Prioritätskette (Not-Halt > Akku > Nutzer-Stopp >
  Codewort-Unterbrechung > laufender Follow-/Return-Ablauf > laufendes
  Gespräch > Wakeword-Begrüßung > Präsentation > Idle) ist nur
  TEILWEISE im Baum abgebildet (Safety/Battery/
  PersonInteractionLifecycle/Interaction/Presentation/IdleAttract) --
  Codewort-Unterbrechung und ein laufender Follow-Ablauf haben aktuell
  KEINE eigene Priorität im Baum.
- `MonitorParticipants`/Gruppenverlust-Behandlung (`GROUP_LOST`) ist
  nicht umgesetzt -- Gruppentracking läuft eigenständig, ohne dass der
  Baum auf einen Gruppenverlust reagiert.
- Kein neuer BT-Knoten löst `FollowPerson` selbst aus (z.B. nach dem
  Codewort "Pepper komm mal mit") -- die Aktion existiert und ist
  autorisiert/getestet (`docs/FOLLOW_PERSON_RUNTIME.md`), aber nichts
  im Baum ruft sie derzeit auf.

Empfohlene nächste Schritte: siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7-Abschnitt "Empfehlung für
das nächste Arbeitspaket".

## Ehrlicher Stand

Reiner C++/XML-Commit, `colcon test` 7/7 bestanden
(uncrustify/cppcheck/flake8/xmllint sauber), `bt_executor_node` manuell
4s laufen lassen: Baum lädt fehlerfrei, alle drei neuen Knotentypen
werden von der Factory aufgelöst, sauberes Herunterfahren per SIGTERM.
Kein echter Pepper, kein echtes Gespräch in dieser Session.
