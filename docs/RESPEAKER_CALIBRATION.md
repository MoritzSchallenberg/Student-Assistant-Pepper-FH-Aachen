# ReSpeaker-Kalibrierung

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6, Abschnitt 21.

**Ehrlicher Hinweis vorab**: nichts in diesem Dokument wurde am realen
Gerät durchgeführt -- kein ReSpeaker Core v2.0 in dieser Session
erreichbar. Dieses Dokument beschreibt den VORGESEHENEN
Kalibrierungsablauf und die Startwerte, die im Code bereits als
konfigurierbare Parameter hinterlegt sind (keine davon ist als
"kalibriert" markiert).

## Was kalibriert werden muss, und wo der Wert im Code steht

| Größe | Parameter/Konstante | Datei |
|---|---|---|
| Mikrofonabstand (fürs GCC-PHAT-Zeitfenster) | `mic_spacing_m` | `directional_audio.py::GccPhatDelayAndSumBackend` |
| Welche zwei Kanäle für GCC-PHAT | `microphone_channels[0]`/`[1]` | dito, `audio_node.py`-Parameter `respeaker_microphone_channels` |
| Mechanischer Montagewinkel (ReSpeaker relativ zu `base_link`) | -- | **noch nicht als TF-Transform implementiert**, siehe `docs/RESPEAKER_CORE_V2_INTEGRATION.md`, Abschnitt TF |
| Wakeword-Mindestkonfidenz | `wakeword_min_confidence` | `audio_node.py` |
| Wakeword-Cooldown | `wakeword_cooldown_s` | `audio_node.py`/`wakeword_gate.py::WakewordGate` |
| DoA-Mindestkonfidenz | `min_confidence` | `directional_audio.py::GccPhatDelayAndSumBackend` |
| Kopf-Ausrichtungsgeschwindigkeit | `ORIENT_SPEED_SCALE` | `orient_to_sound_node.py` |
| Operative Kopf-Grenzen | `HEAD_YAW/PITCH_OPERATIONAL_*` | `bridge_node.py` |
| Winkelkorridor für Personenzuordnung | `maximum_angular_error_deg` | `audiovisual_association.py` |
| Mehrdeutigkeits-Sicherheitsabstand | `minimum_ambiguity_margin_deg` | `audiovisual_association.py` |
| Ziel-Verlust-Timeout (Gesprächsfokus) | `target_loss_timeout_s` | `audio_focus.py` |

## Vorgesehener Ablauf (Phase A/B aus docs/RESPEAKER_HARDWARE_ACCEPTANCE.md)

1. **Kanalreihenfolge verifizieren**: `arecord -l`/`arecord -D <Karte>
   -f S16_LE -r 16000 -c 8 test.wav` DIREKT auf dem ReSpeaker (nicht
   auf dem NUC) ausführen, jeden Kanal einzeln durch Ansprechen aus
   einer bekannten Richtung identifizieren.
2. **Mikrofonabstand messen**: physischer Abstand zwischen den beiden
   für GCC-PHAT gewählten Mikrofonen, in Metern, in `mic_spacing_m`
   eintragen.
3. **Medianfehler der Schallrichtung messen**: definierte Testpositionen
   (0°, ±30°, ±60°, ±90°) in ruhiger Umgebung ansagen lassen, Azimut-
   Schätzung gegen die bekannte wahre Richtung vergleichen -- Zielwert
   aus dem Auftrag: höchstens 15° Medianfehler in ruhiger Umgebung,
   höchstens 25° bei moderatem Störgeräusch.
4. **Konfidenzschwelle kalibrieren**: `min_confidence` so einstellen,
   dass die in Schritt 3 gemessenen korrekten Schätzungen als
   `valid=True` durchgehen, aber offensichtliches Rauschen/Stille
   `valid=False` bleibt.
5. **Wakeword-Schwelle kalibrieren**: `wakeword_min_confidence` gegen
   eine Serie von echten "Pepper"-Aussprachen UND Fremdwörtern
   einstellen (Ziel: möglichst wenige Falschauslösungen pro Teststunde,
   siehe Auftrag Abschnitt 21).
6. **Montagewinkel bestimmen**: sobald die TF-Transformation
   implementiert ist (siehe `docs/RESPEAKER_CORE_V2_INTEGRATION.md`),
   den mechanischen Offset zwischen ReSpeaker-Vorwärtsrichtung und
   `base_link`-Vorwärtsrichtung messen und als statische Transformation
   eintragen.
7. **Seitliche Dämpfung messen**: Referenzperson vorne, Störsprecher
   seitlich -- Pegeldifferenz zwischen `output_rms_dbfs` (fokussiert)
   und einer unbeamformten Referenzaufnahme messen. Zielwert: mindestens
   6 dB messbare Dämpfung.

## Status

**Keiner der obigen Schritte wurde durchgeführt.** Alle Parameter
stehen auf dokumentierten, plausiblen Startwerten (siehe Tabelle oben),
nicht auf kalibrierten Werten. Vor jedem Live-Einsatz mit echten
Nutzern MUSS diese Kalibrierung nachgeholt werden.
