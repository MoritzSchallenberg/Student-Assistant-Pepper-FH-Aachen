# Pepper-Projekt: Status (Stand 2026-08-17)

## Netzwerk
- Pepper feste IP: **192.168.100.50** (DHCP-Reservierung auf MAC `00:13:95:1f:49:1b`,
  eingerichtet via `setup_pepper_dhcp.sh`, NetworkManager "shared"-Modus auf `eno1`)
- Dieser PC auf dem Kabel: **192.168.100.1**
- Pepper SSH/NAOqi-Login: User `nao`, Passwort `<PEPPER_QI_PASSWORD>`
- Bei Verbindungsproblemen: fail2ban sperrt Port 22 kurzzeitig nach falschen
  Login-Versuchen (ein paar Minuten warten)
- **Falls das Kabel abgesteckt wird**: Pepper braucht dann WLAN (SSID
  vermutlich der Name des Makerspace-WLANs, WLAN-Passwort vermutlich
  identisch mit dem SSH-Passwort -- noch nicht konfiguriert/
  getestet). Ohne Kabel-Verbindung laeuft nichts hier Beschriebenes live weiter,
  nur der Code kann offline weiterentwickelt werden.

## Was funktioniert
- **ROS2 Jazzy + naoqi_driver2**: gebaut in `ros2_ws/`, laeuft gegen Pepper.
  Start: `ros2 launch naoqi_driver naoqi_driver.launch.py nao_ip:=192.168.100.50
  network_interface:=eno1 password:=<PEPPER_QI_PASSWORD> qi_listen_url:=tcp://192.168.100.1:0`
- **Sprechen**: ueber SSH/`qicli` (`apps/web/pepper/qicli.py`, gefixter
  keyboard-interactive-Auth-Bug) UND ueber ROS-Topic `/speech` (std_msgs/String)
- **Bewegen (Arme/Kopf)**: `ALMotion.angleInterpolation <Gelenkname> <Winkel>
  <Zeit> <1|0>` per qicli/SSH. WICHTIG: Bool-Parameter als `1`/`0`, nicht
  `true`/`false`. Liste-Argumente (`[...]`) funktionieren nicht zuverlaessig,
  lieber Skalare pro Gelenk einzeln senden.
- **Fahren (`ALMotion.moveTo x y theta`)**: funktioniert, ABER nur wenn
  **kein Ladekabel** an Pepper haengt (Ladekabel = Fahr-Interlock).
  Immer vorher mit Kamera pruefen, ob der Weg frei ist!
- **Kamera**: `/camera/front/image_raw`, `/camera/bottom/image_raw`,
  `/camera/depth/image_raw`, `/camera/stereo/image_raw` -- alle liefern Bilder,
  ca. 1 Hz, Aufloesung 320x240.
- **YOLOv8-Pose-Skeletterkennung + Nachahmung**: `vision/pose_watch.py`
  (nur Analyse/Log) und `vision/mimic_arms.py` (Pepper macht Armhoehe
  nach). Eigenes venv (`vision/venv`, `--system-site-packages`).
  ACHTUNG: `numpy` MUSS `<2` sein (`pip install "numpy<2"`), sonst Segfault
  durch ABI-Konflikt mit `cv_bridge`.

## Audio/Hoeren -- GELOEST (Umweg, funktioniert)
Zwei Wege liefern **keine** Daten (Ursache ungeklaert, vermutlich
naoqi_driver2-Bug bzw. NAOqi-API-Problem auf dieser Einheit):
- ROS-Topic `/audio` ueber naoqi_driver2 (`qi_listen_url` korrekt gesetzt,
  `ROS-Driver-Audio`-Service auf Pepper sichtbar, Port erreichbar -- aber
  Pepper baut nie eine Verbindung dahin auf)
- `ALAudioDevice.startMicrophonesRecording()`/`openAudioInputs()` (geben
  `null`/Erfolg zurueck, schreiben aber nie eine Datei)

**Funktionierender Workaround**: Das Mikrofon-Hardware (`wm8860`-Codec) ist
technisch aktiv -- gehalten von **PulseAudio** (nicht vom kritischen NAOqi-
Kernprozess, also unbedenklich). PulseAudio-Source `"microphone"` (4ch,
48kHz, RUNNING) liefert zuverlaessig Audio per `parecord`:
```
parecord --device=microphone --file-format=wav /home/nao/irgendwas.wav
```
Datei per SFTP holen, mit `faster-whisper` (lokal, CPU) transkribieren.

- **`stt/listen_loop.py`** -- GETESTET, funktioniert: nimmt wiederholt
  kurze Fenster auf (Default 3s), holt sie per SFTP, transkribiert. Robust,
  aber kein echtes Ende-der-Aeusserung-Erkennen (Saetze werden manchmal an
  Fenstergrenzen zerschnitten).
- **`stt/listen_pulse.py`** -- NICHT fertig: sollte per Live-SSH-Stdout-
  Stream + eigener RMS-Lautstaerke-Erkennung echtes VAD (Sprechpausen
  erkennen) machen, damit Pepper schnell reagieren kann sobald jemand
  aufhoert zu reden. Haengt sich aktuell auf (`stdout.read()` bekommt nie
  Daten von `parecord ... --raw ... -` im nicht-interaktiven SSH-Kanal --
  vermutlich ein Buffering-/TTY-Problem von `parecord` ueber `exec_command`).
  **TODO fuer zuhause**: alternativen Streaming-Weg finden, z.B. `parecord`
  in eine benannte Pipe/FIFO schreiben lassen und die separat per SFTP/
  zweitem SSH-Kanal lesen, oder mit `paramiko`s `get_pty=True` probieren,
  oder `nc`/Netcat-basiertes Streaming statt SSH-Stdout.
- **`stt/listen.py`** -- aeltestes Skript, nutzt den kaputten ROS-`/audio`-
  Weg, funktioniert nicht. Kann geloescht/ignoriert werden, sobald
  `listen_pulse.py` fertig ist.

## GELOEST (2026-08-18): NAOqi-Port-9559-Blocker
**Ursache gefunden per Recherche**: Bekanntes NAOqi-2.9-Verhalten (nicht
unser Setup/WLAN/Interfaces-Problem!), siehe
[naoqi_driver2 Issue #5](https://github.com/ros-naoqi/naoqi_driver2/issues/5#issuecomment-1934253818)
und [naoqi_driver Issue #162](https://github.com/ros-naoqi/naoqi_driver/issues/162).
Port 9559 ist bei NAOqi 2.9 nur noch NAOqi-intern (localhost). Der externe,
oeffentlich erreichbare Zugangspunkt ist stattdessen **Port 9503**
(Prozess `qi-secure`, bindet auf `*:9503`).

**Fix**: beim `naoqi_driver2`-Start `nao_port:=9503` statt des Default-Werts
(9559) verwenden:
```
ros2 launch naoqi_driver naoqi_driver.launch.py nao_ip:=192.168.100.50 \
  nao_port:=9503 network_interface:=eno1 password:=<PEPPER_QI_PASSWORD> \
  qi_listen_url:=tcp://192.168.100.1:0
```
Kein Root, kein WLAN-Aus, kein Kabel-Timing-Trick noetig -- alles davor
Ausprobierte war eine Sackgasse, aber jetzt dokumentiert falls in Zukunft
doch mal relevant.

## Sensor-Bewertung (RViz/ROS-Topics, 2026-08-18)
Fuer Mapping/SLAM-Einschaetzung (Pepper hat kein echtes Lidar, nur:):
- **`/laser`** (`sensor_msgs/LaserScan`): FOV 240° (±120°), ~61 Punkte
  (Winkelaufloesung ~3.9°), Reichweite 0.1-3.0m, **nur ~1.1 Hz** Update-Rate.
  Vereinzelt Werte über `range_max` (z.B. 7.08m bei max=3.0m) als
  "kein Echo"-Kodierung -- beim Verarbeiten filtern.
- **`/sonar/front`, `/sonar/back`**: je 1 Wert (kein Scan), FOV 30°,
  Reichweite 0.25-2.55m, ~1.1-1.2 Hz.
- **Einschaetzung**: Winkelaufloesung und Update-Rate sind deutlich
  grober als ein "echtes" Lidar (typisch 5-40Hz, <1° Aufloesung). Für
  langsames/statisches Mapping (Roboter steht still, dreht sich, baut
  Karte auf) nutzbar; für dynamisches SLAM waehrend der Fahrt eher
  ungeeignet ohne Sensor-Fusion mit der Tiefenkamera (`/camera/depth/image_raw`).

## Architektur-Entscheidung (2026-08-18): SSH+qicli statt direktem qi-Python
Versucht: eine direkte `qi`-Python-Verbindung vom PC zu Pepper (Port 9503,
kein SSH), um Text-Parsing zu vermeiden und Signal-Subscription (für
`HumanPerception`-Gesichtserkennung) zu ermoeglichen. `qi`-Paket per `pip
install qi` installierbar (v3.1.5, offizielles PyPI-Paket), verbindet auf
TCP-Ebene, **scheitert aber am TLS-Handshake** (`RuntimeError: disconnected`).
Bestaetigt per `openssl s_client`: Port 9503 nutzt ein echtes,
selbstsigniertes Aldebaran-TLS-Zertifikat (`qi.private.aldebaran.lan`),
das der `qi`-Python-Client nicht vertraut -- keine dokumentierte Option
gefunden, das zu umgehen. `nao`-User hat kein `sudo` (getestet, explizit
verweigert) -- fuer eine Root-Loesung braeuchte man das echte Root-Passwort
von Pepper oder Zugriff via SoftBank-Robotics-Account + offizieller
"Robot Settings"-Software.

**Entscheidung**: Nicht weiterverfolgt. Der schon vorhandene Weg des
urspruenglichen `apps/web`-Autors -- SSH-Login als normaler `nao`-User
(kein Root noetig) + `qicli`-CLI-Kommandos -- reicht fuer alles, was
gebraucht wird, und laeuft bereits komplett PC-seitig (SSH ist nur der
Transportweg, die eigentliche Logik ist Python-Code in
`apps/web/pepper/qicli.py` auf dem PC). Root/TLS waere nur fuer die
rohe `HumanPerception`-Signal-Subscription noetig gewesen (siehe
`CAPABILITIES.md`), was ein Nice-to-have ist, kein Blocker.

**`pepper/qicli.py` wurde entsprechend ausgebaut**: viele neue, saubere
Python-Methoden (`get_battery()`, `get_angle()`/`set_angle()`,
`raise_arms_sideways()`, `wave()`, `get_mood()`, `set_led_color()`,
`play_sound()`, `get_touch_status()`, u.v.a.) statt Einweg-SSH-Strings --
direkt nutzbar als Bausteine fuer Behavior-Tree-Knoten. Vollstaendige Liste
mit Status in `CAPABILITIES.md`.

## Frueherer Blocker (2026-08-17, nach Aus-/Wiedereinschalten): NAOqi-Port 9559 nur auf localhost
Nach einem Aus-/Wiedereinschalten (loeste zusaetzlich ein ~15min Firmware-
Update des Faceboards aus -- **beim Reboot also Geduld haben, nicht
unterbrechen!**) bindet `qilaunch`/NAOqi Port 9559 nur noch auf
`127.0.0.1`, nicht mehr extern auf `192.168.100.50`. Symptom: `ros2 launch
naoqi_driver ...` gibt `Connect error: 111: Connection refused`, obwohl
Pepper per Ping/SSH erreichbar ist.
- Diagnose: `lsof -i :9559` auf Pepper zeigt `localhost.localdomain:9559
  (LISTEN)` statt `*:9559`. (`ss`/`netstat` funktionieren auf Pepper nicht
  richtig -- `lsof` nutzen!)
- `systemctl --user restart naoqi.service` behebt es NICHT (mehrfach
  getestet).
- Die Service-Datei (`/nao/etc/systemd/user/naoqi.service`, ExecStart mit
  `--qi-listen-url :9559`) gehoert `root`, koennen wir mit `nao`-User nicht
  editieren.
- SSH-Tunnel als Workaround (`ssh -L 9559:127.0.0.1:9559`) scheitert:
  Peppers sshd hat `AllowTcpForwarding` deaktiviert
  ("Administratively prohibited").
- **Noch nicht probiert / naechste Schritte**: Root-Zugriff besorgen (z.B.
  vom Betreuer) und entweder die Service-Datei anpassen (`--qi-listen-url
  0.0.0.0:9559`) oder AllowTcpForwarding in `/etc/ssh/sshd_config`
  aktivieren; oder ausprobieren, ob ein **vollstaendiger** Neustart (nicht
  nur `systemctl restart`) das Problem behebt (bisher 2x probiert, half
  nicht, aber ev. mehr Geduld noetig); oder Betreuer fragen, ob kuerzlich
  eine Sicherheitshaertung an diesem Pepper vorgenommen wurde.

## Noch nicht angefangen
- Echtes VAD/Streaming ohne Fenster-Zerschneiden (siehe `listen_pulse.py`-TODO oben)
- Text -> AnythingLLM -> Antwort aussprechen (letzter Baustein fuer den
  vollen "hoeren -> verstehen -> antworten"-Kreis). `llm/anythingllm.py`
  existiert schon und ist fertig fuer die Anbindung. `stt/listen_loop.py`
  muesste im Erkennungs-Block einfach noch `anyllm.send_chat_message(...)`
  und danach `c.exec_command('qicli call ALAnimatedSpeech.say "..."')`
  aufrufen.
- WLAN-Konfiguration von Pepper (fuer kabelloses Arbeiten)

## Zukunftsmöglichkeiten mit diesem Pepper (NAOqi 2.9.5.172)
Recherchiert/verifiziert am 2026-08-18 per `qicli info` -- alles unten
existiert wirklich auf diesem Roboter, ist aber (falls nicht anders
vermerkt) noch nicht gebaut/getestet.

### Architektur-Verbesserung: ALMemory statt Polling
Aktuell fragen wir Zustände per einzelnen `qicli call`-Kommandos ab
(Polling). NAOqi hat dafür eigentlich ein zentrales Event-System:
**`ALMemory`** mit `subscribeToEvent(name, callback_module, callback_method)`
-- Ereignisse feuern automatisch, kein Abfragen nötig. Bestätigte
Beispiel-Events (via `ALMemory.getEventList`):
`WordRecognized`, `TouchChanged`, `FrontTactilTouched`,
`HandLeftBackTouched`, `LastWordRecognized`, u.v.a.
**Für den Behavior Tree ist das der sauberere Weg**: Bedingungs-Knoten
könnten auf diese Events reagieren statt aktiv zu pollen. Braucht aber
echte `qi`-Python-Bindings (nicht nur SSH/`qicli`), da Signale/Events
nicht über einzelne Kommandozeilen-Aufrufe abonniert werden können.

### Eigenes Mapping/Navigations-Modul (direkt für dein Lidar-Vorhaben relevant!)
Pepper hat **eingebaute** NAOqi-Module dafür, unabhängig von ROS:
- **`Mapping`**: `makeMap()`, `mapFrame()`, `chargingStationFrame()`,
  `makeFreeFrame()` -- NAOqi kann selbst Karten aus seinen Sensoren bauen
- **`ALNavigation`**: `computePathInMap()` -- Pfadplanung auf einer
  vorhandenen Karte
Das ist eine Alternative (oder Ergänzung) zu einem ROS2-Nav2-basierten
Ansatz mit den `/laser`+`/sonar`-Topics. Lohnt sich zu vergleichen: NAOqi-
eigenes Mapping vs. ROS2-Nav2-Stack mit unseren Sensor-Topics.

### Personen-/Stimmungserkennung
- **`ALMood`**: `currentPersonState()`, `currentPersonDescriptor()` --
  liefert (vermutlich) Alter/Geschlecht/Stimmung einer erkannten Person
- **`ALRobotMood`**: Peppers eigener "Gemütszustand", beeinflusst
  Idle-Verhalten
- Kombiniert mit `HumanPerception` (Gesichter/Körper, siehe
  `CAPABILITIES.md`) ließe sich ein Verhalten bauen, das erkennt, WER da
  ist und WIE die Person gestimmt ist, nicht nur DASS jemand da ist

### Tablet als Interaktions-Fläche
**`ALTabletService`**: `showWebview(url)`, `hideWebview()` -- kann
beliebige Webseiten auf Peppers Brust-Tablet anzeigen. Ließe sich mit dem
schon laufenden `apps/web`-Server kombinieren (eigene UI/Bilder/
Status-Anzeige direkt am Roboter, nicht nur am PC)

### Dialog-System als schnelle Ergänzung zum LLM
**`ALDialog`** (QiChat-Skripte, siehe auch `CAPABILITIES.md`) für
Standard-Antworten mit praktisch 0 Latenz (kein Whisper+LLM-Umweg nötig),
LLM nur für alles, was nicht in ein festes Muster passt -- Hybrid-Ansatz
für niedrigere Reaktionszeit bei häufigen Fragen

### Mit einem stärkeren Rechner auf Peppers Rücken
Aktuell läuft die ganze Rechenlast (Whisper, YOLO, ROS2-Verarbeitung,
Flask) auf diesem PC, verbunden per Kabel/WLAN. Wird das durch einen
eigenen, mitgeführten Rechner ersetzt/ergänzt, ändert sich Grundlegendes
-- aber nicht alles. Rein spekulativ (nichts davon ist gebaut/getestet),
aber auf Basis der heute gemessenen Fakten eingeordnet:

**Was sich NICHT ändert (wichtig für Erwartungshaltung):**
Die Sensor-Update-Raten (Kamera ~1Hz, Laser/Sonar ~1.1Hz) kommen aus
NAOqi/der Hardware selbst, nicht aus fehlender Rechenleistung beim
Empfänger. Ein stärkerer Rechner lässt Pepper nicht öfter Bilder/Scans
liefern -- er verarbeitet nur das, was ankommt, schneller/besser.

**Was neu möglich wird:**
- **Kabellose Autonomie**: kein Tether zu einem Desktop-PC mehr nötig --
  Pepper wird zum eigenständigen, mobilen System (nur noch WLAN zur
  eigenen NAOqi-Instanz, kein externer Rechner in Reichweite nötig)
- **Größere/genauere lokale Modelle**: aktuell läuft Whisper "small" und
  YOLOv8n (nano, kleinstes Modell) auf CPU, weil sie schnell genug sein
  müssen. Mit echter GPU-Leistung an Bord: Whisper "medium"/"large"
  (deutlich bessere Erkennung, v.a. bei Hintergrundlärm/Akzenten),
  größere YOLO-Varianten, ggf. sogar mehrere Modelle gleichzeitig
  (Pose-Erkennung + Gesichtserkennung + Objekterkennung parallel, statt
  nacheinander)
- **Eigenes lokales LLM statt/neben AnythingLLM**: mit genug GPU-Speicher
  ein Modell direkt an Bord laufen lassen (z.B. über Ollama) -- keine
  Abhängigkeit mehr von einem separaten LLM-Server im Netz, geringere
  Latenz, funktioniert auch ganz ohne Internet/Netzwerk-Infrastruktur
- **Echtes VAD/Streaming ohne den SSH-Umweg**: der gescheiterte Ansatz aus
  `listen_pulse.py` (Audio-Stream live verarbeiten) wird realistischer,
  wenn Aufnahme UND Verarbeitung auf demselben Gerät passieren -- kein
  Netzwerk-Overhead, kein SSH-Kanal als Flaschenhals
- **SLAM-Kartenerstellung/Loop-Closure onboard**: rechenintensive Teile
  von Nav2/RTAB-Map o.ä. laufen lokal, ohne Latenz durchs Netzwerk zu
  einem externen PC -- bleibt aber weiterhin durch die ~1Hz Sensor-Rate
  begrenzt (siehe oben)
- **Eigener Webserver/Dashboard direkt am Roboter**: `apps/web`
  könnte auf dem Onboard-Rechner laufen statt hier -- von jedem Gerät im
  Netz erreichbar, nicht an diesen PC gebunden

**Praktisch zu bedenken, bevor du einen Rechner montierst:**
- **Stromversorgung**: eigener Akku/Powerbank nötig, oder Abzweig von
  Peppers eigenem Akku (Kapazität/Belastbarkeit vorher prüfen -- könnte
  Peppers eigene Laufzeit verkürzen)
- **Gewicht/Balance**: Pepper ist ein Rad-Roboter mit begrenzter
  Zuladung; zusätzliches Gewicht am Rücken verschiebt den Schwerpunkt,
  kann Fahrverhalten/Kippsicherheit beeinflussen -- vorher Belastungs-
  grenzen recherchieren, nicht einfach draufschrauben
- **Kühlung**: ein leistungsfähiger Rechner (v.a. mit GPU) erzeugt Abwärme,
  aktive Kühlung (Lüfter) am beweglichen Roboter nötig
- **Anbindung**: der Onboard-Rechner würde vermutlich genauso wie dieser
  PC heute per WLAN mit Peppers `wlan0` sprechen (Port 9503, siehe oben)
  -- keine grundlegend andere Netzwerk-Architektur nötig, nur "näher dran"
- **Befestigung**: Pepper hat keine offizielle Rücken-Befestigung ab
  Werk -- Halterung wäre Marge-Eigenbau/3D-Druck

**Realistische Hardware-Klasse** (grobe Einordnung, keine konkrete
Empfehlung): Für "größere Modelle + evtl. LLM" braucht es echte GPU-
Rechenleistung, kein reiner Mini-PC -- Geräte wie ein NVIDIA-Jetson-Modul
(geringer Stromverbrauch, für Robotik verbreitet) oder ein kleiner PC mit
dedizierter GPU sind die typischen Kandidaten für sowas, abhängig von
Budget/Stromverbrauchs-Anforderungen.

### Klare Grenzen (nicht möglich, unabhängig vom Aufwand)
- Feingliedrige Handgesten (nur 1 Motor/Hand, siehe `CAPABILITIES.md`)
- Schnelle Sensor-Reaktion auf Bewegung (Kamera/Laser/Sonar alle ~1Hz,
  hardwarebedingt/durch NAOqi vorgegeben, nicht per Software behebbar)
- Autonomes Fahren bei angeschlossenem Ladekabel (Sicherheits-Interlock)

## Verzeichnisse
- `apps/web/` -- Sprechen, LLM-Anbindung, STT (venv: `apps/web/venv`)
- `ros2_ws/` -- naoqi_driver2 + Abhaengigkeiten (System-ROS2 Jazzy)
- `vision/` -- YOLO-Pose-Erkennung/Nachahmung (venv: `vision/venv`)
- `ros2/autonomy_ws/` -- Autonomiesystem (Dialog/Interaktion/Navigation),
  siehe naechster Abschnitt
- `setup_pepper_dhcp.sh` -- Netzwerk-Setup-Skript (einmalig ausgefuehrt)

## Autonomiesystem `ros2/autonomy_ws/` (Stand 2026-08-20)

Umsetzung des Entwicklungsauftrags "Autonomes Dialog-, Interaktions- und
Navigationssystem" (8 Arbeitspakete). Vollstaendiger, ehrlicher Statusbericht
(was getestet ist, was nur vorbereitet ist, bekannte Bugs, Sicherheits-
hinweise, Startbefehle) steht in **`IMPLEMENTATION_REPORT.md`** -- hier nur
die Kurzfassung.

**11 neue ROS2-Pakete** unter `ros2/autonomy_ws/src/`:
`ihk_pepper_interfaces` (Messages/Services/Actions), `ihk_pepper_bridge`
(Pepper-Steuerung als ROS2-Actions, ersetzt/ergaenzt `qicli.py`-Direktnutzung),
`ihk_pepper_audio` (Ringpuffer+VAD+Whisper+Halbduplex), `ihk_pepper_dialog`
(FAQ-Cache+AnythingLLM+Dialog-FSM), `ihk_pepper_perception`
(YOLO-Personen-Tracking+Interessens-Score), `ihk_pepper_interaction`
(Interaktions-FSM+Sicherheits-Supervisor mit `motion_capable`-Kill-Switch),
`ihk_pepper_presentation` (Tagesthema/Video/Quiz), `ihk_pepper_navigation`
(Laser-Filter/Zonen/Personen-Ansteuerung/Nav2-Vorbereitung, **Nav2 selbst
ist auf diesem Rechner nicht installiert**), `ihk_pepper_bringup`
(Gesamtstart-Launch-Dateien), `ihk_pepper_tests` (54 pytest-Tests, alle gruen),
`ihk_pepper_behavior_tree` (BehaviorTree.CPP-Baum, in Groot2 oeffenbar --
C++-Executor NICHT kompiliert/getestet, `behaviortree_cpp` fehlt, siehe
`ihk_pepper_behavior_tree/README.md`).

Ausserdem neu: erweiterte **Tablet-UI** in `apps/web/tablet_ui.py` +
`templates/tablet.html` (11 Bildschirme: Start/Attract/Listening/
Transcribing/Thinking/Answer/Presentation/Quiz/Navigation/Error/Offline),
live per ROS2-Hintergrund-Thread an das Autonomiesystem angebunden.

**Sicherheit**: `motion_capable` ist ueberall Standard `false` -- Fahren/
Personen-Ansteuerung sind erst nach explizitem Launch-Parameter UND
gueltigen Lokalisierungs-/Hindernis-/Tiefendaten moeglich (mehrfach live
getestet, siehe `IMPLEMENTATION_REPORT.md`).

**Getestet ohne angeschlossenen Pepper** (Pepper war die ganze Session
aus) -- Software-Verhalten/Zustandsmaschinen/Sicherheitslogik sind real
verifiziert, echte SSH/qicli-Kommunikation mit dem Roboter NICHT.

## ReSpeaker Core v2.0/Wakeword (Entwicklungsauftrag 04-B, AP6+AP6.1, Stand 2026-09-09)

Neue Fähigkeit: Wakeword-gesteuerte Begrüßung ("Pepper" sagen → Kopf
dreht sich vorsichtig zur groben Schallrichtung → RealSense bestätigt
eine eindeutige Person → erst dann winkt Pepper). Vollständige
Architektur/ehrlicher Stand: **`docs/RESPEAKER_CORE_V2_INTEGRATION.md`**.

**Kein ReSpeaker Core v2.0 und kein Pepper in dieser Session
erreichbar** -- alle neuen Module (`ihk_pepper_audio/respeaker_transport.py`,
`directional_audio.py`, `wakeword_gate.py`, `audio_focus.py`,
`ihk_pepper_interaction/orient_to_sound_node.py`,
`ihk_pepper_perception/audiovisual_association.py`, die neuen
Behavior-Tree-Knoten) sind ausschließlich gegen Fakes/Mocks/synthetische
Signale getestet. Fünf Hardware-Testphasen definiert, KEINE davon
durchgeführt -- siehe `docs/RESPEAKER_HARDWARE_ACCEPTANCE.md`.

**AP6.1 (Nachfolgeauftrag) hat die in AP6 offen dokumentierte
TF-Transformations-Lücke vollständig geschlossen**: die Schallrichtung
wird jetzt tatsächlich von `respeaker_link` nach `base_link`
transformiert (`sound_direction_transform_node.py`, dynamische TF-Kette
aus `robot_state_publisher`+`/joint_states`), das audiovisuelle
Zuordnungsergebnis erreicht `audio_focus_node.py` jetzt echt (nicht
mehr immer `selected_track_id=-1`), Wakeword-Ereignisse werden im
Behavior Tree exactly-once verarbeitet, und die front/back-mehrdeutige
Zwei-Mikrofon-Schätzung darf nie mehr ohne explizite,
in Produktion gesperrte Freigabe eine Kopfbewegung auslösen. Details:
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, Abschnitt AP6.1. Weiterhin
offen: alle fünf Hardware-Testphasen, echte Vermessung der
ReSpeaker-/RealSense-Montage, front/back-Mehrdeutigkeit selbst
(strukturell markiert, nicht aufgelöst).

## Rollen, Codewörter, Gruppengespräche, sicheres Personenfolgen (Entwicklungsauftrag 04-B, AP7, Stand 2026-09-10)

Neue Fähigkeiten: ein Rollenmodell (STUDENT/EMPLOYEE/ADMIN,
ausschließlich per lokalem `peoplectl`-CLI setzbar, nie per ROS2-Service
oder LLM), einwilligungsgebundene Gesichtsidentität mit strikt
getrennten transienten (Gruppengespräch) und persistenten Pfaden, ein
deterministischer Codewort-Router ("Eisenbahn" → Unterbrechung, "Pepper
komm mal mit" → Autorisierungsanfrage fürs Folgen), stabile
Mehrpersonen-Gruppenverfolgung mit sicherer Beobachtungspose und
gruppenbewusster Richtmikrofonie, eine ECHTE autorisierte
`FollowPerson`-Fahrt (ersetzt den bisherigen, nie fahrenden Stub) und
Ursprungspose-Erfassung/-Rückkehr, jetzt auch im Behavior Tree als
`PersonInteractionLifecycleSubtree` eingebettet. Vollständige
Architektur/ehrlicher Stand je Thema:
**`docs/PERSON_ROLES_AND_AUTHORIZATION.md`**,
**`docs/FACE_IDENTITY_AND_PRIVACY.md`**,
**`docs/PRIVILEGED_VOICE_COMMANDS.md`**,
**`docs/GROUP_CONVERSATION.md`**, **`docs/FOLLOW_PERSON_RUNTIME.md`**,
**`docs/RETURN_TO_ORIGIN.md`**, **`docs/INTERACTION_LIFECYCLE.md`**.

**Kein ReSpeaker Core v2.0, kein echtes Nav2, kein Pepper in dieser
Session erreichbar** -- alle neuen Module sind ausschließlich gegen
Mocks/Duck-Typing-Fakes/synthetische Signale getestet (+312 Tests,
1297/1300 Python-Tests gesamt, BT.CPP `colcon test` weiterhin 7/7).
Vier neue, rein softwarebasierte Launch-Modi
(`role_authorization_offline_test`, `group_interaction_offline_test`,
`follow_person_dry_run`, `interaction_lifecycle_dry_run`) real
gestartet, keine echte Hardware. Vollständige offene Checkliste:
`docs/AP7_HARDWARE_TEST_CHECKLIST.md`.

**Wichtigste ehrlich offene Lücke (AP7-Stand)**: `ihk_pepper_identity`
war ein fertiges, getestetes Gesichtsidentitäts-Backend OHNE ROS2-Node.
Codewort-/Rollen-/Gruppen-Routing war NICHT in den Behavior Tree
verdrahtet. Details: `docs/DEVELOPMENT_ORDER_04_B_REPORT.md`,
AP7-Abschnitt.

## Identity-Laufzeit, sichere Rollenautorisierung, vollständige Interaktionsorchestrierung (Entwicklungsauftrag 04-B, AP7.1, Stand 2026-09-10)

Schließt die oben genannte AP7-Lücke: `face_identity_node.py` ist jetzt
ein echter, ausführbarer ROS2-Node (Face-Detector-/Identity-Backend
getrennt, 10-stufige Verarbeitungspipeline, fail-closed ohne Modell).
Die alte, global geteilte `/authorization/secondary_confirmation`-Bool-
Nachricht ist vollständig entfernt, ersetzt durch eine ereignisgebundene
Anfrage/Antwort-Autorisierung (`ScopedAuthorizationStore`,
`AuthorizationRequest`/`AuthorizationDecision`/`ConfirmAuthorization`).
Codewort ("Eisenbahn"), autorisiertes `FollowPerson`
("Pepper, komm mal mit") und Gruppengespräch sind jetzt erstmals in den
Behavior Tree eingebunden (`CodewordInterruptSubtree`/
`FollowCommandSubtree`/`GroupConversationSubtree`) statt nebeneinander
zu laufen. Ursprungspose-Objekte sind jetzt zusätzlich an die Art der
Interaktion gebunden (`interaction_id`) -- ein Ursprung aus einer
Follow-Sitzung kann nicht mehr für eine Einzelgesprächs-Rückkehr
verwendet werden. Ein fehlgeschlagenes `ReturnToOriginViaBT` wird jetzt
über `/interaction/lifecycle_state` sichtbar gemacht, statt
stillschweigend zu verschwinden. Vier neue Launch-Modi
(`identity_offline_test`, `authorization_tablet_test`,
`command_follow_dry_run`, `group_interaction_dry_run`) und
Produktionsfreigaben für die persistente Zuordnung
(`production_readiness.py`, sieben Gates).

**Kein echtes ONNX-Modell, kein echtes Mikrofon, kein echtes Nav2, kein
Pepper in dieser Session erreichbar** -- alle neuen Module ausschließlich
gegen Mocks/synthetische Daten getestet (+147 Tests seit AP7-Abschluss,
1454/1457 Python-Tests gesamt, BT.CPP `colcon test` weiterhin 23/0/0/4).
`identity_offline_test`/`authorization_tablet_test` real per `ros2
launch` gestartet (kein Absturz), reine Software-Verdrahtungsprüfung.
Vollständige offene Checkliste: `docs/AP7_1_HARDWARE_TEST_CHECKLIST.md`.
Architektur je Thema: `docs/IDENTITY_RUNTIME.md`,
`docs/FACE_TRACK_ASSOCIATION.md`,
`docs/BIOMETRIC_ENROLLMENT_AND_DELETION.md`,
`docs/SCOPED_AUTHORIZATION.md`, `docs/COMMAND_FOLLOW_LIFECYCLE.md`,
`docs/CODEWORD_INTERRUPTS.md`, `docs/GROUP_CONVERSATION_RUNTIME.md`,
`docs/INTERACTION_LIFECYCLE.md` (aktualisiert).

**Wichtigste ehrlich offene Lücke (AP7.1-Stand)**: kein echtes
ONNX-Modell/keine echte biometrische Datenbank angelegt -- jede Aussage
zur echten Gesichtserkennung bleibt bei "Backend fail-closed getestet".
Keine unabhängige Prioritätsauflösung zwischen aktivem
Einzelgespräch und neu geformter Gruppe. Details:
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7.1-Abschnitt.

## AP8-R1: Laufzeitdurchsetzung, sichere Cancellation, Trajektorienfreigabe

Neun bestätigte Laufzeitlücken in der bereits bestehenden
AP8.1-8.3-Struktur geschlossen (Details:
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, Abschnitt "AP8 corrective
runtime review"): `speed_scale` wird jetzt an genau einer Stelle
aufgelöst (`gesture_execution_policy.py::resolve_speed_scale()`) und
danach nirgends mehr unabhängig neu berechnet; die Startpose wird bei
jeder v2-Hardwaregeste unabhängig von `restore_after` gelesen; ein
Laufzeit-Watchdog prüft Safety/Nav2/Mapping/Interaktion/Erreichbarkeit/
Lease/Zeitdeckel periodisch während der gesamten Ausführung, nicht nur
davor; 14 strukturierte Cancellation-Gründe (`gesture_cancellation.py`)
ersetzen den bisherigen bloßen `threading.Event`; ein nach der
Cancel-Grace-Zeit noch laufender Hintergrund-Thread führt nie zu einer
Erfolgsmeldung oder einer sofortigen Lease-Freigabe; das
Lease-Revocation-Race zwischen Erwerb und Transportstart ist
geschlossen; der Standard-`TrajectorySafetyValidator` ist ohne echtes
Kollisions-Backend jetzt strukturell `inconclusive`, nicht `pass`;
`schema_version 1`-Gesten sind in `production` strukturell gesperrt.

Python-Tests: 1600 bestanden, 3 übersprungen (Ausgangsstand vor AP8-R1:
1548/3 -- 52 neue/umbenannte Tests, davon 9 als benannte Offline-E2E-
Szenarien A-H in `test_ap8r1_offline_e2e.py`). BT.CPP `colcon test`
unverändert 23/0/0/4.

**Ehrlich offen (`hwverificationrequired`)**: kein echtes
Kollisions-/Vorwärtskinematik-Backend installiert -- `production`
kann deshalb aktuell **keine** Geste ausführen, bis ein solches Backend
real verfügbar ist (der Mechanismus selbst ist getestet, siehe
`test_production_profile_succeeds_once_a_real_collision_proof_backend_is_injected`).
`t_pose.yaml` bleibt `live_validated` für den historischen v1-Ablauf,
kann diesen Status aber nicht mehr als Bypass für die neue
v1-production-Sperre nutzen. Kein Hardwaretest in dieser Session
durchgeführt, keine Livebewegung, kein Push.
