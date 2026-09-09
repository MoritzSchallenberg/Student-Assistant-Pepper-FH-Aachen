# ReSpeaker Core v2.0: Gesamtarchitektur

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6; AP6.1 (echte
Frame-Transformation, siehe Abschnitt "TF/Koordinatensysteme" unten --
ersetzt den in AP6 offen gelassenen Stand vollständig).
Siehe auch (Details je Teilbereich): `docs/RESPEAKER_TRANSPORT.md`
(Hardware-/Transportanalyse, `ReSpeakerAudioTransport`-Familie),
`docs/AUDIO_FOCUS_AND_BEAMFORMING.md` (DoA-Backends, Konversationsfokus),
`docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md` (Schallrichtung -> Person),
`docs/ACTUATOR_ARBITER.md`/`docs/ACTION_CANCELLATION.md` (HEAD-Lease,
SetHeadPose-Cancel), `docs/BEHAVIOR_TREE.md` (Wakeword-Begrüßungsablauf),
`docs/RESPEAKER_CALIBRATION.md`, `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`.

## Gewünschter Ablauf (Auftrag Abschnitt 1) und wo er implementiert ist

| Schritt | Implementiert in |
|---|---|
| 1. Pepper wartet | `/interaction_state == IDLE` (bestehend, Auftrag 1) |
| 2. „Pepper" gesagt | `ihk_pepper_audio/wakeword.py::WakewordDetector` (bestehend) + `wakeword_gate.py::WakewordGate` (neu, AP6) |
| 3. Aktivierungswort + Richtung erkannt | `directional_audio.py` (`PassthroughTestBackend`/`GccPhatDelayAndSumBackend`) + `audio_node.py` veröffentlicht `WakewordEvent` auf `/audio/wakeword_event_raw` (RAW, `frame_id=respeaker_link`) → `sound_direction_transform_node.py` transformiert nach `/audio/wakeword_event` (kanonisch, `frame_id=base_link`, siehe AP6.1-Abschnitt unten) |
| 4. Kopf dreht sich vorsichtig | BT: `WaitForFreshWakeword` (kanonisches Topic, exactly-once, siehe unten) → `IsHeadOrientationAllowed` → `OrientHeadToSound` → `orient_to_sound_node.py` → `SetHeadPose`-Action (`bridge_node.py`, HEAD-Lease) |
| 5. RealSense sucht Person im Bereich | BT: `FindPersonNearSoundRay` → `audiovisual_association_node.py` (`AssociatePersonWithSound`-Service) |
| 6. Eindeutige Bestätigung nötig | `audiovisual_association.py::associate_person_to_sound()` -- Mehrdeutigkeit → keine Auswahl |
| 7. Pepper winkt | BT: bestehende `PlayCatalogGesture gesture_name="wave_right"` (unverändert) |
| 8. Rückwinken + Sicherheitsprüfungen | BT: bestehende `WaitForGestureFromTrack`/`IsApproachAllowed`/`ApproachSelectedPerson` (unverändert, jetzt mit der von Schritt 6 bestätigten `track_id`) |
| 9. Gesprächsfokus auf die Person | `audio_focus.py::AudioFocusStateMachine` (Zustand `CONVERSATION_FOCUS`) |
| 10. Dämpfung seitlicher/rückwärtiger Sprecher | `GccPhatDelayAndSumBackend` (Delay-and-Sum über die konfigurierten Mikrofonkanäle) |
| 11. Rückkehr in den Wartezustand | `audio_focus.py` (`RETURNING_TO_IDLE` → `IDLE_WIDE`), ausgelöst durch `/interaction_state == IDLE` |

## Wichtige Sicherheitsgrenzen, wo durchgesetzt

- **Audio löst nie direkt eine Basisbewegung aus**: `SetHeadPose`
  (bridge_node.py) steuert AUSSCHLIESSLICH `HeadYaw`/`HeadPitch` --
  syntaktisch kann kein Wakeword-Pfad `/cmd_vel` oder eine
  Basis-Aktion erreichen (kein Code-Pfad verbindet `wakeword_gate.py`/
  `orient_to_sound_node.py` mit `person_approach_node.py` direkt; die
  Annäherung läuft ausschließlich über die bestehende, unveränderte
  `ApproachSelectedPerson`-Action NACH bestätigtem Rückwinken).
- **Aktivierungswort verändert nie `allow_motion`**: `WakewordGate`/
  `audio_node.py` schreiben nirgends auf `SafetyState`/`allow_motion` --
  kein Code-Pfad existiert dafür.
- **Erste physische Reaktion ist höchstens eine begrenzte
  Kopfbewegung**: `SetHeadPose` klemmt auf `HEAD_YAW/PITCH_OPERATIONAL_*`
  (enger als die vollen Gelenkgrenzen), erfordert eine `HEAD`-Lease,
  bewegt nie Arme/Basis.
- **Winken erst nach eindeutiger visueller Zuordnung**:
  `FindPersonNearSoundRay` steht in der BT-Sequence VOR
  `PlayCatalogGesture wave_right` -- schlägt die Zuordnung fehl, wird
  nie gewunken.
- **Mehrdeutigkeit → keine Auswahl**: siehe
  `docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md`.
- **Mapping/Nav2 blockieren die Kopfausrichtung**:
  `IsHeadOrientationAllowed` (BT) + `orient_to_sound_node.py::
  _safety_ok_for_orientation()` (serverseitig, vollständig).
- **Ein Wakeword-Ereignis löst höchstens EINEN Ausrichtungsversuch aus**
  (AP6.1, bestätigter Fund behoben): `WaitForFreshWakeword` (BT, C++)
  verarbeitet jede `event_id` GENAU EINMAL (begrenzter Cache
  verbrauchter IDs) und akzeptiert nur Ereignisse mit
  `frame_id==base_frame` -- nach einem gescheiterten Versuch muss die
  Person erneut "Pepper" sagen, kein Wiederverwenden eines alten
  Ereignisses über einen erneuten BT-Tick.

## TF/Koordinatensysteme (AP6.1: implementiert)

Der Auftrag (Abschnitt 11) verlangt eine vollständige TF-Kette und einen
expliziten Ablauf: Schallstrahl im `respeaker_link` erfassen → mit der
zum Messzeitpunkt gültigen Kopfpose nach `base_link` transformieren →
erst danach den Kopf bewegen → RealSense-Tracks danach mit demselben
Strahl vergleichen. **In AP6 war das NICHT implementiert** (der
Rohwinkel wurde unverändert als "bereits in base_link" weitergereicht) --
AP6.1 hat diesen bestätigten Fund vollständig behoben:

**Volle TF-Kette** (dynamisch, aus `robot_state_publisher` +
`/joint_states`, siehe `pepper_robot_state.launch.py`):

```
map -> odom -> base_link -> torso -> Neck -> Head
                                        |
                                        +-> realsense_mount_link -> camera_link (RealSense-Treiber ab hier)
                                        +-> respeaker_link (ReSpeaker-Mikrofonarray)
```

`base_link -> torso` ist FEST (URDF), `torso -> Neck` trägt `HeadYaw`,
`Neck -> Head` trägt `HeadPitch` (beide aus `pepper_description`, dem
ECHTEN, bereits vorhandenen Pepper-URDF im separaten Workspace
`ros2/robot_model` -- bewusst wiederverwendet statt eine zweite,
möglicherweise abweichende Kinematik-Quelle anzulegen).
`Head -> realsense_mount_link`/`Head -> respeaker_link` sind STARR
(Montagepunkte, Werte aktuell Platzhalter, siehe
`docs/RESPEAKER_CALIBRATION.md`/`docs/REALSENSE_CALIBRATION.md`).

**Zweiter, unabhängig gefundener Fund** (analog zum
`actuator_arbiter_node`-Launch-Fund aus AP6): `robot_state_publisher`
wurde in `autonomy_ws` nie gestartet, und KEIN Node hat je
`/joint_states` publiziert -- `camera_pose_gate_node.py`/
`head_pose_gate.py` konsumieren dieses Topic bereits seit
Entwicklungsauftrag 1 fail-closed, `head_navigation_pose_valid` war
dadurch in jedem echten Einsatz vermutlich immer `False`. Behoben:
`bridge_node.py::_publish_joint_states()` liest `HeadYaw`/`HeadPitch`
periodisch über `pepper.get_angle()`.

**Strikte RAW/kanonische Topic-Trennung**: `audio_node.py` publiziert
NUR `/audio/sound_direction_raw` + `/audio/wakeword_event_raw` (immer
`frame_id=respeaker_link`, das reale Mikrofonarray-relative Maß,
UNVERÄNDERT). Der neue `sound_direction_transform_node.py` ist der
EINZIGE Publisher der kanonischen Topics `/audio/sound_direction` +
`/audio/wakeword_event` (`frame_id=base_link`) -- eine reine VEKTOR-
Transformation (`tf2_geometry_msgs.do_transform_vector3`, KEINE
Translation, weil eine Richtung keine Position ist) zum ORIGINALEN
Messzeitpunkt, nicht zum Empfangszeitpunkt. Fail-closed
(`valid=False`/`direction_valid=False`, NIE ein erfundener Winkel) bei:
leerem/unbekanntem Frame, fehlender/veralteter/zukünftiger TF, invalider
Quaternion, nicht-endlichem Ergebnis, zu altem Original-Messzeitpunkt.
`audio_focus_node.py`/`WaitForFreshWakeword` (Behavior Tree) abonnieren
NUR die kanonischen Topics.

Für echte Personenpositionen (KEINE reine Richtung, sondern eine echte
Position mit Translation) verwendet `audio_focus_node.py::
transform_person_position_to_azimuth()` dagegen `do_transform_point`
(Translation UND Rotation) -- transformiert die bestätigte
Personenposition von `base_link` nach `respeaker_link`, bevor sie als
Beamforming-Ziel weitergegeben wird (siehe
`docs/AUDIO_FOCUS_AND_BEAMFORMING.md`).

**Wichtig**: die bestehende Navigationssperre bei abweichender Kopfpose
(`camera_pose_gate_node.py`) bleibt als Verteidigung in der Tiefe
bestehen -- AP6.1 schaltet KEINE automatische Kopfbewegungsfreigabe für
Navigation frei, nur weil die TF-Kette jetzt korrekt ist.

**Noch offen (hwverificationrequired)**: `respeaker_extrinsics.yaml`/
`realsense_extrinsics.yaml` bleiben Platzhalter (Translation 0, Rotation
Identität, `is_calibrated: false`) -- keine echte Vermessung am realen
Aufbau in dieser Session. Die front/back-mehrdeutige Zwei-Mikrofon-
GCC-PHAT-Schätzung selbst bleibt außerdem strukturell als unsicher
markiert (`provides_unambiguous_direction=False`, siehe
`docs/AUDIO_FOCUS_AND_BEAMFORMING.md`) -- eine korrekte TF-Transformation
macht eine mehrdeutige Messung nicht zu einer eindeutigen.

## Datenschutz

Kein vollständiges Whisper-Transkript im Idle-Modus (siehe
`audio_node.py::_handle_utterance()` -- Whisper wird erst nach einem
gültigen `WakewordGate`-Ereignis aufgerufen). Keine dauerhafte
Speicherung der Idle-Aufnahme (Ringpuffer bleibt flüchtig, siehe
`ring_buffer.py`, unverändert seit Auftrag 1). Kein rohes Audiosignal
wird standardmäßig als ROS-Topic veröffentlicht (`/audio/sound_direction(_raw)`/
`/audio/wakeword_event(_raw)`/`/audio/focus_state`/`/audio/visual_target`
enthalten nur Zahlen/Strings, keine PCM-Daten).

## Getestet / nicht getestet

Alle in dieser Datei referenzierten Module sind gegen Fakes/Mocks
unit-getestet (siehe `docs/DEVELOPMENT_ORDER_04_B_REPORT.md` für die
vollständige Testliste). **Kein Test in dieser Session lief gegen
echte ReSpeaker-/Pepper-Hardware** -- siehe
`docs/RESPEAKER_HARDWARE_ACCEPTANCE.md` für den genauen, ehrlichen
Stand jeder der vier Hardware-Testphasen (alle NICHT durchgeführt).
