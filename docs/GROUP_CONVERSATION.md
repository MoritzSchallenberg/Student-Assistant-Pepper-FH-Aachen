# Gruppengespräche

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 5-7/11.
Implementierung: `ihk_pepper_perception/group_tracking.py` +
`group_tracking_node.py`, `ihk_pepper_navigation/group_observation_pose.py`,
`ihk_pepper_audio/group_speaker_selection.py` + `audio_focus_node.py`.

## Stabile Gruppenverfolgung (`group_tracking.py`)

Single-Linkage-transitives Clustering (Union-Find) über
`/perception_node/person_tracks`: zwei Personen gehören zur selben
Gruppe, wenn eine Kette gegenseitig naher Personen sie verbindet (nicht
nur paarweise Nähe zum Anker). Beitritts-/Austritts-Hysterese ist an
den AKTUELLEN Interaktionspartner (Anker-Track) gebunden -- eine
zufällig vorbeigehende Person wird NIE automatisch Teil der Gruppe.
Austritts-Hysterese misst "Zeit seit ZULETZT tatsächlich gesehen"
(`_member_last_present`), nicht "Zeit seit erstmals vermisst" -- Letzteres
war ein realer, testgefundener Bug (bei unregelmäßigen Update-Intervallen
sofort fälschlich erfüllt).

`group_tracking_node.py` veröffentlicht `/perception/conversation_groups`
(`ConversationGroupArray`).

## Sichere Gruppen-Beobachtungspose (`group_observation_pose.py`)

Geschlossene tangentenbasierte Geometrie statt iterativer Suche:
`required_distance = spread_radius / tan(fov/2)` passt die Zielpose so
an, dass die gesamte Gruppe ins Kamera-Sichtfeld passt. Geprüft werden:
zu wenige Mitglieder, Gruppe zu breit für das konfigurierte Fahrbudget
(→ "gruppe_zu_breit", Pepper bittet stattdessen "bitte rückt näher
zusammen"), Fahrdistanz überschritten, Mindestabstand zum NÄCHSTEN
Mitglied (nicht nur zum geometrischen Zentrum -- eine Person am Rand
der Gruppe darf nie zu nah angefahren werden), Keepout-Zonen, optionale
Costmap. Pepper fährt NIEMALS in die Gruppe hinein.

## Gruppenbewusste Richtmikrofonie (`group_speaker_selection.py` + `audio_focus_node.py`)

Zwei Modi:

- **GROUP_WIDE** -- Fokus auf das Gruppenzentrum (für allgemeine
  Ansprache an alle).
- **ACTIVE_SPEAKER** -- Fokus auf den bestätigten aktiven Sprecher
  INNERHALB der bestätigten Gruppe. `ActiveSpeakerSelector` verlangt
  mehrere aufeinanderfolgende bestätigende Frames (Hysterese) und eine
  Mindestmarge gegenüber der zweitwahrscheinlichsten Quelle, bevor ein
  Sprecherwechsel übernommen wird -- kein Springen bei jedem kurzen
  Geräusch.

**Wichtige Sicherheitseigenschaft (per Test nachgewiesen):**
`audio_focus.py`s `selected_track_id` (die Sitzungsidentität, die
bestimmt "wessen Stimme gehört überhaupt zu dieser Konversation")
ändert sich durch die Gruppenlogik NIE -- nur der an
`on_target_track_update()` übergebene Azimut-WERT wechselt zwischen
Gruppenzentrum und aktivem Sprecher. Die aus AP6.1 bestehende
Fremdtrack-Ablehnungsgarantie (ein Track außerhalb der bestätigten
Sitzung kann nie den Fokus übernehmen) bleibt dadurch unverändert
bestehen, ohne `audio_focus.py` selbst anfassen zu müssen.

## Ehrlicher Stand

62 Tests (31 Gruppenverfolgung, 15 Beobachtungspose, 16
Sprecherauswahl/Audio-Integration). Ausschließlich gegen synthetische
Personentrack-/DOA-Daten getestet -- kein echter Raum, keine echte
Gruppe, kein echter ReSpeaker in dieser Session. Rollen-/Identitäts-
Bindung einer Gruppe (`person_id`/`group_id`) ist in `CaptureOriginPose`
(siehe `docs/RETURN_TO_ORIGIN.md`) noch leer -- Gruppen werden aktuell
rein über Track-IDs verwaltet, keine persistente Gruppenidentität.
