# Audiofokus und Beamforming

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6, Abschnitte 6/10;
AP6.1, Abschnitt 5 (echte Steuerung des bestätigten Fokus-Ziels).
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
  `[1]`) für die Richtungsschätzung, plus ein Delay-and-Sum über ALLE
  konfigurierten Kanäle für das verbesserte Mono-Signal. **Wichtige
  Einschränkung**: liefert nur eine Zwei-Mikrofon-Halbebenen-Schätzung
  (Vorne/Hinten bei einem linearen Mikrofonpaar mehrdeutig) -- KEINE
  volle 360-Grad-Auflösung über alle 6-8 Kanäle kombiniert. Deshalb
  `provides_unambiguous_direction = False` (siehe Abschnitt
  "Ambiguitäts-Gate" unten). Getestet gegen synthetische, künstlich
  verzögerte Signale (`test_gcc_phat_backend.py`), NICHT gegen echte
  ReSpeaker-Hardwaredaten.
- **`MockDirectionalBackend`**: fest injizierbares Ergebnis für Tests
  (`provides_unambiguous_direction = True`, Testkomfort -- der
  Testautor kontrolliert das Ergebnis ohnehin vollständig).
- **`ReSpeakerVendorBackend`**: dokumentierter `NotImplementedError`-
  Platzhalter -- die Herstellerbibliothek wurde NICHT ungeprüft
  übernommen (historisch auf älteren Python-2-/Debian-Ständen, siehe
  `docs/RESPEAKER_TRANSPORT.md`).

Die Konfidenzformel in `GccPhatDelayAndSumBackend` ist **ausdrücklich
nicht kalibriert** -- ein Startpunkt, keine physikalisch hergeleitete
Kennzahl. Siehe `docs/RESPEAKER_CALIBRATION.md` für den vorgesehenen
Kalibrierungsablauf am realen Gerät.

## Ambiguitäts-Gate: keine Kopfbewegung auf eine unsichere Peilung (AP6.1)

Bestätigter Fund (AP6.1, Abschnitt 3.7/5/13): eine front/back-mehrdeutige
Zwei-Mikrofon-Schätzung wurde nirgends als unsicher markiert -- eine
Kopfbewegung hätte darauf genauso ausgelöst wie auf eine echte
360-Grad-Peilung. Behoben über:

- `DirectionalAudioBackend.provides_unambiguous_direction` (Default
  `False`, konservativ) -- ein Backend muss EXPLIZIT deklarieren, dass
  es eine echte 360-Grad-Peilung liefert.
- `audio_node.py` verfolgt in `self._direction_source_unambiguous`, ob
  das AKTUELL verbundene Backend diese Deklaration trägt (Default
  `False`, bis der erste Sample eines qualifizierten Backends
  eintrifft).
- `_try_wakeword_activation()` setzt `direction_valid` zurück (NIE die
  Richtung selbst verändert), wenn die Quelle mehrdeutig ist UND kein
  ausdrücklicher Parameter `allow_ambiguous_direction_for_head_orientation`
  (Default `false`) das für Entwicklungs-/Testzwecke übersteuert.
- `production_mode=true` + `allow_ambiguous_direction_for_head_orientation=true`
  ist beim Start hart gesperrt (`RuntimeError`, analog zum bestehenden
  `continuous_development`-Guard) -- eine mehrdeutige Quelle darf in
  Produktion NIE als sichere Grundlage für eine Kopfbewegung gelten.
- `interaction_full_safe.launch.py` setzt `production_mode` seit AP6.1
  Commit 7 tatsächlich auf `true` in `mode=production` (bestätigter
  Fund: vorher blieb dieser Parameter IMMER beim Node-internen Default
  `false`, dieser Guard hätte in der echten Produktions-Launch nie
  gegriffen).

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
"degraded"-Hängenbleiben). Kein automatischer Ersatz durch eine andere
Person -- `selected_track_id` ändert sich nur über eine neue
`on_person_confirmed()`-Bestätigung (ein neues Wakeword-Ereignis).

`on_target_track_update(track_id, azimuth_rad)` ignoriert Updates für
eine ANDERE `track_id` als die aktuell ausgewählte (gibt `False`
zurück) -- verhindert, dass ein fremder/lauterer Sprecher versehentlich
zum neuen Fokus wird.

## Echte Verdrahtung seit AP6.1 (behobener Fund)

Bis AP6.1 Commit 5 trieb `audio_focus_node.py` die Maschine nur über
Signale, die bereits auf ROS2-Topics verfügbar waren (`WakewordEvent`,
`/pepper_bridge/speaking`, `/interaction_state`) -- der Übergang zu
`CONVERSATION_FOCUS` war ein vereinfachter Behelf über
`/interaction_state == CONVERSATION_READY`, IMMER mit
`selected_track_id=-1`. Seit Commit 5 gilt:

- `audio_focus_node.py` abonniert `/audio/visual_target`
  (`AudioVisualTarget.msg`, siehe `docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md`)
  -- das ECHTE Zuordnungsergebnis von `audiovisual_association_node.py`,
  inklusive `track_id`. Nur innerhalb des erwarteten Ablauffensters
  (`ORIENTING_TO_SOUND`/`VISUAL_CONFIRMATION`) wirkt eine eingehende
  Nachricht überhaupt -- ein verspätetes/fremdes Ereignis wird ignoriert.
- Während `CONVERSATION_FOCUS`/`PEPPER_SPEAKING` abonniert der Node
  zusätzlich `/perception_node/person_tracks` und ruft
  `on_target_track_update()` NUR für den bereits bestätigten `track_id`
  auf -- ein anderer/lauterer Sprecher wird strukturell verworfen
  (siehe oben).
- Personenpositionen liegen im `base_frame` vor, das Beamforming
  arbeitet aber im Mikrofonarray-Frame (`respeaker_link`) --
  `transform_person_position_to_azimuth()` (neue reine Funktion in
  `audio_focus_node.py`) führt dafür eine ECHTE Punkt-Transformation
  durch (Translation UND Rotation, im Unterschied zur reinen
  Vektor-Transformation für Schallrichtungen selbst, siehe
  `docs/RESPEAKER_CORE_V2_INTEGRATION.md`). Fehlende/veraltete TF führt
  IMMER zu einer verworfenen Aktualisierung, NIE zu einem erfundenen
  Winkel. `/audio/focus_state.target_azimuth_rad` ist seit diesem
  Commit IMMER im `respeaker_link`-Frame (vorher: zuletzt bekannter
  Wakeword-Wert, noch im `base_frame`).
- `audio_node.py` abonniert `/audio/focus_state` und gibt das
  bestätigte Ziel an das aktuell aktive Backend weiter
  (`self._current_backend`, Cross-Thread-Zugriff nach demselben,
  bereits etablierten Muster wie `self._push_to_talk_active`).

## Echtes Steering (`SteerableDirectionalAudioBackend`, AP6.1)

Neue Schnittstelle `set_focus_target(azimuth_rad, valid_until_monotonic_s)`/
`clear_focus_target()`. `GccPhatDelayAndSumBackend` implementiert sie:
ist ein bestätigtes, frisches Ziel gesetzt UND eine per-Kanal
`microphone_geometry` (`MicrophoneGeometry(channel, x_m, y_m)`)
konfiguriert, wird das Ausgangssignal per echtem, geometriebasiertem
Delay-and-Sum GEZIELT auf diesen festen Winkel ausgerichtet -- über
ALLE konfigurierten Kanäle, nicht nur das GCC-PHAT-Referenzpaar. Die
gemeldete DoA-Messung (`azimuth_rad`/`doa_confidence` im Ergebnis)
bleibt davon UNBERÜHRT (unabhängige Messung, ein Fokus-Ziel kann sie
nie verfälschen). Ohne `microphone_geometry` (Default): unverändertes
altes Verhalten, volle Rückwärtskompatibilität. Konfiguriert über drei
parallele `audio_node`-Parameter (`respeaker_mic_geometry_channels`/
`_x_m`/`_y_m` -- ROS2-Parameter kennen keine Listen von Objekten),
alle drei leer = keine Geometrie, kein Steering.

`valid_until_monotonic_s` wird von `audio_node.py` mit seiner EIGENEN
`time.monotonic()`-Uhr berechnet (Parameter
`focus_target_freshness_margin_s`, Standard 1.0s über
`audio_focus_node.py`s Publikationsintervall von 0.2s) -- verlässt sich
NICHT auf eine geteilte Uhren-Epoche zwischen den getrennten
ROS-Prozessen. Bleibt `/audio/focus_state` länger als die Marge aus
(Absturz von `audio_focus_node`, Netzproblem), fällt das Backend von
selbst auf ungerichtetes Verhalten zurück.

**Noch offen (hwverificationrequired)**: die Kanalgeometrie selbst ist
in keiner Launch-Konfiguration mit echten, vermessenen Werten befüllt
(alle drei Arrays bleiben Default leer) -- ein reales Steering wurde
deshalb NICHT gegen echte ReSpeaker-Hardware verifiziert, nur gegen
synthetische, exakt nach derselben Formel konstruierte Testsignale
(`test_gcc_phat_backend.py`).

## Getestet

`test_gcc_phat_backend.py` (17: 10 aus AP6 + 7 neue Steering-/
Ambiguitäts-Fälle), `test_directional_audio.py` (9), `test_audio_focus.py`
(13, unverändert seit AP6 -- die Zustandsmaschine selbst wurde nicht
geändert), `test_audio_focus_node.py` (grundlegend überarbeitet, 20
Fälle: `/audio/visual_target`, `/perception_node/person_tracks`,
Fremdtrack-Ablehnung, Frame-Validierung, TF-Transformation),
`test_audio_node_wakeword.py` (9 neue Fälle: Ambiguitäts-Gate in beiden
Richtungen, `_on_focus_state`-Weiterleitung). Kein Test gegen echte
ReSpeaker-Hardware.

## Gruppenbewusstes Steering (Entwicklungsauftrag 04-B, AP7)

`audio_focus_node.py` unterscheidet seit AP7 zusätzlich GROUP_WIDE
(Fokus auf das Gruppenzentrum) und ACTIVE_SPEAKER (Fokus auf den per
`ActiveSpeakerSelector`-Hysterese bestätigten aktiven Sprecher
INNERHALB einer bestätigten Gruppe, siehe
`ihk_pepper_perception/group_tracking.py`). Wichtig: `selected_track_id`
(die Sitzungsidentität, siehe oben) wird durch die Gruppenlogik NIE
verändert -- nur der an `on_target_track_update()` übergebene
Azimut-WERT wechselt. Die Fremdtrack-Ablehnungsgarantie aus AP6.1
bleibt dadurch unverändert bestehen. Details:
`docs/GROUP_CONVERSATION.md`. 16 neue Tests
(`group_speaker_selection.py` + `audio_focus_node.py`-Erweiterung),
weiterhin kein Test gegen echte ReSpeaker-Hardware.
