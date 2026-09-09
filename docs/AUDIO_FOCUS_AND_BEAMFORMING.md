# Audiofokus und Beamforming

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6, Abschnitte 6/10.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_audio/ihk_pepper_audio/
directional_audio.py` (Richtungsschätzung/Beamforming), `audio_focus.py`
+ `audio_focus_node.py` (Gesprächsfokus-Zustandsmaschine).

## Wichtige Formulierung (Auftrag Abschnitt 10)

> Der Aufnahmebereich wird auf die ausgewählte Person fokussiert;
> Geräusche außerhalb des Zielkorridors werden soweit möglich gedämpft.

Nirgends in Code/Dokumentation dieses Projekts wird "alle anderen Töne
ausblenden" behauptet -- jede `valid`/`reason`-Kombination in
`DirectionalAudioResult`/`AudioFocusStateData` ist so gestaltet, dass
eine NICHT erreichte Dämpfung/Zuordnung ehrlich als `valid=False`
sichtbar bleibt, nie als stillschweigend erfolgreich vorgetäuscht wird.

## DirectionalAudioBackend-Familie

Siehe `docs/RESPEAKER_TRANSPORT.md` für die Einordnung ins Gesamtbild.
Vier Implementierungen:

- **`PassthroughTestBackend`**: extrahiert Kanal 0, schätzt KEINE
  Richtung (`valid=False`, ehrlich). Für Launch-Modi, in denen der
  Audiopfad end-zu-Ende getestet werden soll, ohne dass ein DoA-Backend
  überhaupt beteiligt ist (`respeaker_offline_test`).
- **`GccPhatDelayAndSumBackend`**: der tatsächliche CPU-Fallback.
  Standard-GCC-PHAT (Generalized Cross Correlation mit Phase Transform)
  zwischen zwei konfigurierten Mikrofonkanälen (`microphone_channels[0]`/
  `[1]`) für die Richtungsschätzung, plus ein einfaches ganzzahliges
  Sample-Delay-and-Sum über ALLE konfigurierten Kanäle für das
  verbesserte Mono-Signal. **Wichtige Einschränkung**: liefert nur eine
  Zwei-Mikrofon-Halbebenen-Schätzung (Vorne/Hinten bei einem linearen
  Mikrofonpaar mehrdeutig) -- KEINE volle 360-Grad-Auflösung über alle
  6-8 Kanäle kombiniert. Getestet gegen synthetische, künstlich
  verzögerte Signale (`test_gcc_phat_backend.py`), NICHT gegen echte
  ReSpeaker-Hardwaredaten.
- **`MockDirectionalBackend`**: fest injizierbares Ergebnis für Tests.
- **`ReSpeakerVendorBackend`**: dokumentierter `NotImplementedError`-
  Platzhalter -- die Herstellerbibliothek wurde NICHT ungeprüft
  übernommen (historisch auf älteren Python-2-/Debian-Ständen, siehe
  `docs/RESPEAKER_TRANSPORT.md`).

Die Konfidenzformel in `GccPhatDelayAndSumBackend` ist **ausdrücklich
nicht kalibriert** -- ein Startpunkt, keine physikalisch hergeleitete
Kennzahl. Siehe `docs/RESPEAKER_CALIBRATION.md` für den vorgesehenen
Kalibrierungsablauf am realen Gerät.

## Konversationsfokus-Zustandsmaschine (`audio_focus.py`)

```
IDLE_WIDE -> WAKEWORD_DETECTED -> ORIENTING_TO_SOUND ->
VISUAL_CONFIRMATION -> CONVERSATION_FOCUS <-> PEPPER_SPEAKING ->
RETURNING_TO_IDLE -> (zurück zu IDLE_WIDE)
```

`AUDIO_DEGRADED` ist ein Nebenzustand: wird gesetzt, wenn die
ausgewählte Person länger als `target_loss_timeout_s` (Standard 2.0s)
nicht mehr aktualisiert wurde, während `CONVERSATION_FOCUS`/
`PEPPER_SPEAKING` aktiv war -- `snapshot().valid` wird dann `False`,
fail-closed: kein falsches Fortsetzen eines Gesprächs mit einer
verschwundenen Person. Bleibt der Ziel-Track doppelt so lange verloren,
kehrt die Maschine endgültig zu `IDLE_WIDE` zurück (kein ewiges
"degraded"-Hängenbleiben).

`on_target_track_update(track_id, azimuth_rad)` ignoriert Updates für
eine ANDERE `track_id` als die aktuell ausgewählte (gibt `False`
zurück) -- verhindert, dass ein fremder Track versehentlich zum neuen
Fokus wird.

### Ehrlicher Stand: nicht vollständig automatisch verdrahtet

`audio_focus_node.py` treibt die Maschine nur über Signale, die
BEREITS auf ROS2-Topics verfügbar sind (`WakewordEvent`,
`/pepper_bridge/speaking`, `/interaction_state`). Die BT-internen
Zwischenschritte (`OrientToSound`-Erfolg, `FindPersonNearSoundRay`-
Bestätigung mit konkreter `track_id`/Richtung) sind NICHT als eigene
Topics sichtbar -- der Übergang von `WAKEWORD_DETECTED`/
`ORIENTING_TO_SOUND` zu `CONVERSATION_FOCUS` ist deshalb vereinfacht:
er reagiert auf `/interaction_state == CONVERSATION_READY`, kennt dabei
aber nicht die konkrete, von `FindPersonNearSoundRay` bestätigte
`track_id`/Richtung (`selected_track_id` bleibt in diesem Fall `-1`).
`on_person_confirmed()`/`on_target_track_update()` sind vollständig
implementiert und getestet, aber aktuell nicht automatisch von einem
Topic aus aufgerufen.

**Empfohlener nächster Schritt**: die BT-Knoten `OrientHeadToSound`/
`FindPersonNearSoundRay` (oder `orient_to_sound_node.py`/
`audiovisual_association_node.py` selbst) könnten kleine Ereignis-Topics
veröffentlichen, die `audio_focus_node.py` zusätzlich abonniert, um die
Zustandsmaschine mit der tatsächlichen `track_id`/Richtung zu füttern.

## Getestet

`test_gcc_phat_backend.py` (9), `test_directional_audio.py` (9, aus
Commit 1), `test_audio_focus.py` (13), `test_audio_focus_node.py` (6).
Kein Test gegen echte ReSpeaker-Hardware.
