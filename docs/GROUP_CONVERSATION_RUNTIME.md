# Group Conversation Runtime (AP7.1)

Bindet die in AP7 gebaute, getestete Gruppenlogik
(`group_tracking_node.py`/`group_speaker_selection.py`/
`audio_focus_node.py`) erstmals in den Behavior Tree ein (AP7.1.9/
Commit 7/10). Ergänzt `docs/GROUP_CONVERSATION.md` (AP7,
Gruppenerkennung/-geometrie).

## Neue BT.CPP-Knoten (genau die im Auftrag geforderte Mindestliste)

| Knoten | Rolle |
|---|---|
| `SelectConversationGroup` | Liest `/perception/conversation_groups`, SUCCESS nur bei einer frischen, stabilen Gruppe (≥2 Mitglieder) -- **keine eigene Gruppenbildungslogik** |
| `PlanGroupObservationPose` | Ruft `/plan_group_observation_pose` (reine Planung, KEINE Fahrt) |
| `PositionForGroup` | Ruft `/position_for_group`-Action (`person_approach_node.py`, dieselbe Nav2-/Lease-/Cancel-Kette wie `ApproachPerson`/`ReturnToOrigin`) |
| `MonitorParticipants` | Condition-artig: Gruppe noch stabil + ≥ Mindestmitgliederzahl? |
| `UpdateActiveSpeaker` | Liest den von `audio_focus_node.py::ActiveSpeakerSelector` bestätigten aktiven Sprecher aus `/audio/focus_state` -- **keine eigene Sprecherauswahl-Logik** |
| `EndGroupInteraction` | Räumt `group_id`/`active_speaker_track_id` auf, immer SUCCESS |

## Neue Interfaces

`PlanGroupObservationPose.srv` (reine Momentaufnahme -- `PositionForGroup`
berechnet die tatsächliche Fahrzielpose beim Start ERNEUT frisch, kein
Vertrauen auf eine zwischengespeicherte Pose). `PositionForGroup.action`
(Goal `group_id`; fährt ausschließlich über dieselbe Sicherheitskette
wie `ApproachPerson`/`ReturnToOrigin`).

## Ablauf (`GroupConversationSubtree`)

Einmalig auswählen (`SelectConversationGroup`) → Beobachtungspose planen
(`PlanGroupObservationPose`) → **genau einmal** positionieren
(`PositionForGroup` -- der Aufrufer darf dies laut Auftrag NICHT
während eines laufenden Gesprächs wiederholen) → solange die Gruppe
stabil bleibt (`KeepRunningUntilFailure` um eine `ReactiveSequence` aus
`MonitorParticipants` + `UpdateActiveSpeaker`) mit dem jeweils
bestätigten aktiven Sprecher das **bereits bestehende**
`RunDialogueViaBT` führen -- kein zweiter, eigener
Dialog-Implementierungspfad für Gruppen. Endet kontrolliert
(`EndGroupInteraction`), sobald keine stabile Gruppe mehr besteht.

## Priorität

`GroupConversationSubtree` steht im Root-`ReactiveFallback` **nach**
`PersonInteractionLifecycleSubtree` -- eine bereits laufende
Einzelinteraktion wird nicht von einer sich zeitgleich bildenden Gruppe
unterbrochen (bewusste, konservative Wahl; eine unabhängige
Prioritätsauflösung zwischen beiden ist NICHT Teil dieses Standes,
siehe Commit-7/10-Nachricht).

## Gating-Regeln (aus `group_tracking_node.py`/AP7, hier nur konsumiert)

Mindestens 2 stabile Tracks, über mehrere Frames stabile Gruppierung,
gültige Tiefe, kein Verstoß gegen Keepout-Zonen, gültige
Beobachtungspose, Gruppe nicht zu groß fürs Sichtfeld (siehe
`group_observation_pose.py`). Unbekannte Gruppenmitglieder werden NIE
automatisch biometrisch gespeichert -- Gruppentracking ist rein
`track_id`-basiert, keine Identitätszuordnung.

## Verwandte Dokumente

`docs/GROUP_CONVERSATION.md`, `docs/AUDIO_FOCUS_AND_BEAMFORMING.md`,
`INTERACTION_LIFECYCLE.md`.
