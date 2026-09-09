# ReSpeaker Core v2.0: Transportanalyse und Vertrag

Stand: 2026-09-09. Entwicklungsauftrag 04-B, AP6, Abschnitt 4.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_audio/ihk_pepper_audio/
respeaker_transport.py`. Siehe auch `docs/RESPEAKER_CORE_V2_INTEGRATION.md`
für die Gesamtarchitektur, `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md` für
den Status der tatsächlichen Hardwareprüfung.

## Ehrlicher Hinweis vorab

**Kein ReSpeaker Core v2.0 ist in dieser Session physisch erreichbar.**
Alles in diesem Dokument, was das Gerät selbst betrifft (Betriebssystem,
Kernel, ALSA-Gerätename, Kanalreihenfolge, Onboard-Algorithmen), stammt
aus öffentlich zugänglicher Herstellerdokumentation (Seeed Studio) und
allgemeinem Wissen über dieses Produkt -- **NICHT** aus einer Live-Abfrage
in dieser Session (kein `arecord -l`, kein `ssh` auf ein echtes Gerät
möglich). Jede Angabe hier ist mit `hwverificationrequired` zu behandeln,
bis sie am realen Gerät verifiziert wurde (siehe Abschnitt "Was noch zu
verifizieren ist" unten und `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`,
Phase A).

## Was der ReSpeaker Core v2.0 (nach Herstellerangaben) ist

Anders als ein einfaches USB-Mikrofon-Array (z.B. ReSpeaker Mic Array
v2.0, das als gewöhnliches USB-Audiogerät erscheint) ist der **Core
v2.0** ein **eigenständiger Einplatinencomputer** mit eigenem
Betriebssystem (Debian-/Buildroot-basiertes Linux auf ARM), eigenem
6/8-Kanal-Mikrofonarray, eigenem Lautsprecherausgang und -- je nach
Firmware-Konfiguration -- eigener Onboard-Signalverarbeitung
(Herstellerbibliothek für Beamforming/DoA/AEC/NS, historisch auf
Python 2/älteren Debian-Ständen aufgesetzt). Das bedeutet konkret für
dieses Projekt:

- Der ReSpeaker erscheint dem NUC **nicht automatisch** als
  `/dev/snd/*`-ALSA-Gerät wie ein normales USB-Mikrofon -- er ist ein
  eigener Netzwerk-/USB-Gadget-Endpunkt, kein reines Audio-Peripheriegerät.
- Rohe Mehrkanaldaten (die für eigenes GCC-PHAT-Beamforming gebraucht
  werden) liegen primär **auf dem ReSpeaker selbst** vor (über dessen
  eigene ALSA-Karte, herstellerseitig häufig unter einem Namen wie
  `seeed-8mic-voicecard` registriert -- dieser Kartenname ist allerdings
  ursprünglich von den Raspberry-Pi-HAT-Varianten (4-/6-Mic-Array)
  bekannt; ob der Core v2.0 exakt denselben Treiber/Kartennamen verwendet,
  ist **nicht verifiziert** und muss am realen Gerät geprüft werden).
- Um diese Rohdaten zum NUC zu bekommen, muss entweder (a) ein kleiner
  Capture-Prozess AUF dem ReSpeaker laufen, der die Daten über das
  Netzwerk streamt (SSH-Pipe oder ein dediziertes Netzwerkprotokoll),
  oder (b) der ReSpeaker im USB-Audio-Gadget-Modus konfiguriert werden
  (falls die Firmware das unterstützt), sodass er dem NUC gegenüber wie
  ein normales USB-Mikrofon auftritt -- **beides ist eine
  Konfigurationsfrage der jeweiligen ReSpeaker-Firmware, nicht
  softwareseitig in diesem Projekt entscheidbar, ohne das reale Gerät zu
  prüfen.**

## Die vier Transportarten (`ReSpeakerAudioTransport`)

Da der tatsächliche Verbindungsweg vor Ort variieren kann (und in dieser
Session nicht verifizierbar ist), definiert dieses Projekt eine
gemeinsame, austauschbare Schnittstelle -- die Entscheidung, WELCHE
Transportart tatsächlich zum Einsatz kommt, verschiebt sich dadurch auf
einen reinen Konfigurationsparameter (`audio.transport`), keine
Codeänderung:

```text
ReSpeakerAudioTransport (abstrakte Basis)
├── LocalAlsaTransport    -- ReSpeaker im USB-Audio-Gadget-Modus,
│                            erscheint auf dem NUC als normales
│                            ALSA-Gerät (z.B. ueber sounddevice/PyAudio).
├── SshPcmTransport       -- Capture-Prozess auf dem ReSpeaker selbst
│                            (siehe unten), Rohdaten per SSH-Pipe zum
│                            NUC gestreamt (gleiches Haertungsmuster wie
│                            apps/web/pepper/qicli.py: RejectPolicy,
│                            kein AutoAddPolicy, begrenzte Lesezeiten).
├── NetworkPcmTransport   -- ein dediziertes Netzwerkprotokoll (z.B. ein
│                            einfacher TCP-Stream oder RTP), falls die
│                            ReSpeaker-Firmware das anbietet -- NICHT
│                            verifiziert, ob der Core v2.0 das
│                            unterstuetzt.
└── MockPcmTransport      -- deterministische synthetische Mehrkanal-
                             daten fuer Tests, keine Hardware/kein
                             Netzwerk.
```

Jede Implementierung liefert dieselbe Schnittstelle
(`connect()`/`read_block() -> RawAudioBlock`/`close()`/`is_connected()`),
sodass `ReSpeakerCoreV2Source` (siehe `audio_source.py`) den
tatsächlichen Transport austauschen kann, ohne selbst etwas über SSH/
ALSA/Netzwerk zu wissen (gleiches "Logik von Transport trennen"-Muster
wie `MotionTransport` in `docs/GESTURE_TRANSPORT.md`).

## Kontrollierter Capture-Prozess auf dem ReSpeaker (für `SshPcmTransport`)

Falls Rohdaten nur über einen auf dem ReSpeaker laufenden Prozess
verfügbar sind, ist dieser Prozess bewusst **minimal** gehalten
(vorbereitet als Ansible-Systemd-Unit-Vorlage, siehe
`docs/RESPEAKER_CORE_V2_INTEGRATION.md`, Abschnitt Ansible): liest die
lokale ALSA-Karte per `arecord` (oder direktem ALSA-PCM-Zugriff) und
schreibt Rohdaten auf `stdout`, NICHTS sonst. Er enthält **keine
Dialoglogik, kein LLM, keine Bewegungssteuerung** -- exakt wie vom
Auftrag gefordert. `SshPcmTransport` verbindet sich zu diesem Prozess
über eine gehärtete SSH-Verbindung (siehe `ssh_hardening.py`, unten) und
liest den rohen PCM-Stream blockweise.

## SSH-Härtung (`ssh_hardening.py`, neues Modul)

Wiederverwendet exakt das in `apps/web/pepper/qicli.py`
(Entwicklungsauftrag 4, AP2) etablierte Muster -- eigenständige Kopie
(gleiches "deliberate duplicate over cross-package dependency"-Idiom
wie `safety_topics.py`, da `ihk_pepper_audio` kein Paket außerhalb des
ROS2-Workspace importieren kann): `paramiko.RejectPolicy()` als
Standard, System- UND projekteigene `known_hosts`-Datei, KEIN
`AutoAddPolicy`, `HostKeyChangedError`/`UnknownHostKeyError` bei
Abweichung/unbekanntem Key, begrenzte Kanal-Lesezeiten
(`channel.settimeout()`).

**Bestehender Fund, im selben Zug behoben**: `audio_source.py::
PepperPulseAudioSource.connect()` verwendete bisher
`paramiko.AutoAddPolicy()` -- genau das, was der Auftrag für neue
ReSpeaker-Verbindungen explizit verbietet, und was in `qicli.py` bereits
seit Entwicklungsauftrag 4 behoben ist. Auf dasselbe gehärtete Muster
umgestellt (siehe Commit-Historie in
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP6).

## Was noch zu verifizieren ist (Hardware-Checkliste)

Diese Liste bleibt bis zu Phase A (`docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`)
vollständig offen -- keiner dieser Punkte ist in dieser Session geprüft
worden:

- ReSpeaker-Betriebssystem/Kernel-Version.
- Tatsächlicher ALSA-Kartenname (`arecord -l` auf dem ReSpeaker selbst,
  NICHT auf dem NUC).
- Tatsächliche Kanalzahl/-reihenfolge (8 Rohkanäle wie in der
  Konfigurationsvorlage angenommen, oder anders?).
- Ob die Firmware einen USB-Audio-Gadget-Modus unterstützt
  (`LocalAlsaTransport` wäre dann nutzbar) oder ausschließlich
  Netzwerkzugriff bietet.
- Zeitstempelung/Uhrensynchronisation zwischen ReSpeaker und NUC (NTP?
  freilaufende Uhr? -- relevant für `monotone Zeitstempel`, siehe
  `docs/AUDIO_FOCUS_AND_BEAMFORMING.md`).
- Reconnect-Verhalten bei WLAN-Aussetzern.
- Ob herstellerseitige Onboard-DoA/Beamforming-Algorithmen (XMOS- oder
  vergleichbarer DSP-Chip) tatsächlich über eine stabile, dokumentierte
  Schnittstelle abgreifbar sind (`ReSpeakerVendorBackend`, siehe
  `docs/AUDIO_FOCUS_AND_BEAMFORMING.md`) oder ob nur der CPU-Fallback
  (`GccPhatDelayAndSumBackend`) praktisch nutzbar ist.

## Getestet

`MockPcmTransport` (deterministische synthetische Mehrkanaldaten) ist
vollständig unit-getestet. `LocalAlsaTransport`/`SshPcmTransport`/
`NetworkPcmTransport` sind gegen Fakes/Mocks getestet (kein reales
Gerät) -- als `hwverificationrequired` markiert, siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md` für die genaue Testliste.
