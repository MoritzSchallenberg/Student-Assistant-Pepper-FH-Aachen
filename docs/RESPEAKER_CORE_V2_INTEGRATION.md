# ReSpeaker Core v2.0: Gesamtarchitektur

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6.
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
| 3. Aktivierungswort + Richtung erkannt | `directional_audio.py` (`PassthroughTestBackend`/`GccPhatDelayAndSumBackend`) + `audio_node.py` veröffentlicht `WakewordEvent` auf `/audio/wakeword_event` |
| 4. Kopf dreht sich vorsichtig | BT: `WaitForFreshWakeword` → `IsHeadOrientationAllowed` → `OrientHeadToSound` → `orient_to_sound_node.py` → `SetHeadPose`-Action (`bridge_node.py`, HEAD-Lease) |
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

## TF/Koordinatensysteme -- ehrlicher, unvollständiger Stand

Der Auftrag (Abschnitt 11) verlangt eine vollständige TF-Kette
(`base_link → head_link → camera_link → camera_depth_optical_frame`,
`head_link → respeaker_link`) und einen expliziten Ablauf: Schallstrahl
im `respeaker_link` erfassen → mit der zum Messzeitpunkt gültigen
Kopfpose nach `base_link` transformieren → erst danach den Kopf bewegen
→ RealSense-Tracks danach mit demselben Strahl vergleichen.

**Diese TF-Transformation ist in AP6 NICHT implementiert.** Die
Schnittstellen (`WakewordEvent.azimuth_rad`, `OrientToSound.
azimuth_rad_base_link`, `AssociatePersonWithSound.sound_azimuth_rad`)
sind bereits so benannt/geschnitten, dass ein späterer TF-Transformations-
schritt dazwischengeschoben werden kann, OHNE die bestehenden
Schnittstellen zu ändern -- aktuell wird der vom `DirectionalAudioBackend`
gelieferte Rohwinkel (relativ zur mechanischen Vorwärtsrichtung des
Mikrofonarrays) UNVERÄNDERT als "bereits in base_link" weitergereicht.
Das ist nur dann exakt korrekt, wenn `respeaker_link` und `base_link`
dieselbe Yaw-Ausrichtung haben UND der Kopf zum Messzeitpunkt in
Neutralstellung war -- beides ist am realen Aufbau nicht verifiziert.

**Empfohlener nächster Schritt** (nicht Teil dieses Arbeitspakets):
ein neuer, kleiner ROS-Knoten (oder eine Erweiterung von `audio_node.py`),
der bei Erhalt eines `WakewordEvent` sofort `tf2_ros::Buffer::
lookupTransform("base_link", "respeaker_link", event_stamp)` aufruft
und NUR bei erfolgreicher, aktueller Transformation ein `WakewordEvent`
mit `direction_valid=true` erzeugt (fehlender/zu alter TF → `direction_valid=false`,
fail-closed wie überall sonst in diesem Projekt). Die
`respeaker_link`/`head_link`-`static_transform_publisher`-Einträge
(mechanischer Montagewinkel, siehe `docs/RESPEAKER_CALIBRATION.md`)
müssten dafür ebenfalls noch in der URDF/den Launch-Dateien ergänzt
werden -- aktuell nicht vorhanden.

## Datenschutz

Kein vollständiges Whisper-Transkript im Idle-Modus (siehe
`audio_node.py::_handle_utterance()` -- Whisper wird erst nach einem
gültigen `WakewordGate`-Ereignis aufgerufen). Keine dauerhafte
Speicherung der Idle-Aufnahme (Ringpuffer bleibt flüchtig, siehe
`ring_buffer.py`, unverändert seit Auftrag 1). Kein rohes Audiosignal
wird standardmäßig als ROS-Topic veröffentlicht (`/audio/sound_direction`/
`/audio/wakeword_event`/`/audio/focus_state` enthalten nur Zahlen/Strings,
keine PCM-Daten).

## Getestet / nicht getestet

Alle in dieser Datei referenzierten Module sind gegen Fakes/Mocks
unit-getestet (siehe `docs/DEVELOPMENT_ORDER_04_B_REPORT.md` für die
vollständige Testliste). **Kein Test in dieser Session lief gegen
echte ReSpeaker-/Pepper-Hardware** -- siehe
`docs/RESPEAKER_HARDWARE_ACCEPTANCE.md` für den genauen, ehrlichen
Stand jeder der vier Hardware-Testphasen (alle NICHT durchgeführt).
