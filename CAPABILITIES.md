# Pepper-Fähigkeiten-Inventar

Grundlage für ein Flussdiagramm / Behavior Tree. Pepper: Modell "Pepper 1.8",
NAOqi-Version `2.9.5.172`, Robotername `pepper`.

**Architektur-Entscheidung (2026-08-18)**: Steuerung läuft über SSH +
`qicli` (genau wie im ursprünglichen `flask_wrapper`-Projekt) — kein Root
nötig. Ein Versuch, das per direkter `qi`-Python-Verbindung (Port 9503)
ganz ohne SSH zu machen, scheiterte an einem TLS-Zertifikatsproblem und
wurde bewusst nicht weiterverfolgt, da der SSH-Weg bereits alles leistet
und komplett auf dem PC läuft (SSH ist nur der Transportweg, die ganze
Logik/Verarbeitung passiert in `pepper/qicli.py` auf dem PC).

**Alle Fähigkeiten unten sind jetzt als fertige, wiederverwendbare
Python-Methoden in `flask_wrapper/pepper/qicli.py` verfügbar** — direkt
nutzbar als Bausteine für Behavior-Tree-Knoten:

```python
from pepper.qicli import qicli
c = qicli("192.168.100.50", "nao", "<PEPPER_QI_PASSWORD>")
c.connect()
c.get_battery()        # -> 100
c.wave(side="R")        # -> winkt mit rechtem Arm
```

Externe ROS2-Verbindung (`naoqi_driver2`): **`nao_port:=9503`** verwenden,
nicht 9559 (siehe STATUS.md).

Stand: 2026-08-18.

## Update 2026-08-20: ROS2-Actions/Services statt Direktaufruf

Die obigen `qicli.py`-Methoden sind jetzt zusätzlich (nicht anstatt)
über ROS2 nutzbar, siehe `pepper_autonomy_ws/src/ihk_pepper_bridge/`:
- `Say`-Action (`ros2 action send_goal /pepper_bridge/say ...`) statt
  `qicli.say()` direkt
- `PlayGesture`-Action mit YAML-Gesten-Katalog (`wave_left`, `wave_right`,
  `t_pose`) statt hartcodierter `wave()`/`raise_arms_sideways()`-Logik
- `SystemHealth`-Topic (Akku, Erreichbarkeit) statt manuellem `get_battery()`-Polling

Noch nicht als ROS2-Interface exponiert (nur intern in `pepper_client.py`
verfügbar): Lautstärke, Sprache, LEDs, Tablet-URL, Touch-Status,
Autonomous-Life-Status -- siehe `IMPLEMENTATION_REPORT.md`, Abschnitt
"Bekannte Bugs/Limitierungen".

Vollständiger Kontext (neue Pakete für Dialog/Wahrnehmung/Interaktion/
Präsentation/Navigation, was getestet ist und was nicht): siehe
`IMPLEMENTATION_REPORT.md`.

## Aktions-Knoten (Roboter tut etwas)

| Fähigkeit | Python-Methode (`qicli.py`) | Status | Anmerkung |
|---|---|---|---|
| Vorwärts/seitwärts/drehen fahren | `moveTo(x, y, theta)` | ✅ getestet | **Nur wenn Ladekabel NICHT dran ist** (Fahr-Interlock). Vor jedem Fahrbefehl Kamera prüfen! |
| Zu Navigationsziel fahren (Karte) | — (noch kein Wrapper, ROS `/move_base_simple/goal` oder `ALNavigation.computePathInMap`) | ✅ als aufrufbar bestätigt, nicht live ausgeführt | Bewusst nicht in vollgestelltem Raum getestet |
| Einzelnes Gelenk bewegen | `set_angle(gelenk, winkel_rad, dauer_s)` | ✅ getestet, zuverlässig | Absolute Zielwinkel, blockiert bis fertig |
| Mehrere Gelenke merken/zurücksetzen | `snapshot_joints(liste)`, `restore_joints(snapshot)` | ✅ getestet | Standard-Muster: vor jeder Geste snapshotten, danach restaurieren |
| Arme seitlich ausstrecken (T-Pose) | `raise_arms_sideways(winkel=1.3, dauer=2.5)` + `lower_arms(snapshot)` | ✅ getestet | **Hält nur ~10s**, fällt danach von selbst zurück — als kurze Geste nutzen, nicht dauerhaft |
| Winken | `wave(side="R"/"L", repeats=3)` | ✅ getestet | |
| Steifigkeit setzen | `set_stiffness(kette, wert)` | ✅ getestet | z.B. `set_stiffness("LArm", 1.0)` |
| Posen einnehmen (Stand, Sitz, etc.) | `set_posture(name, speed)`, lesen: `get_posture()` | ✅ getestet | Nur "StandInit" (aktuelle Pose) getestet; andere Posen vermutlich ebenso, aber größere Bewegung — vorher Platz prüfen |
| Sprechen (Text-to-Speech) | `say(text)` ODER ROS `/speech` (std_msgs/String) | ✅ beide getestet | ROS-Weg braucht keine SSH-Verbindung während Betrieb. **Nebenbefund**: `ALSpeakingMovement` ist aktiv (contextual) — Pepper gestikuliert vermutlich schon automatisch beim Sprechen |
| Sprache wechseln (Ausgabe) | `setLanguage(sprache)` (ALTextToSpeech) | ✅ vorhanden im Code | |
| Sprache wechseln (Erkennung) | — (noch kein Wrapper, `ALSpeechRecognition.setLanguage`) | ✅ getestet (roh) | Verfügbar: Chinese, English, German, Japanese |
| Augen-/Ohren-LEDs färben | `set_led_color(gruppe, farbe, dauer)`, `reset_led(gruppe)` | ✅ getestet | Auch `rotateEyes`, `earLedsSetAngle`, Gruppen via `createGroup` (noch kein Wrapper) |
| Sound-/Musikdatei abspielen | `play_sound(pfad, loop=False)` | ✅ getestet | Pfad muss auf Pepper liegen; Systemsounds unter `/opt/aldebaran/share/naoqi/{wav,ogg}/` |
| Autonomous Life umschalten | `set_autonomous_life_state(state)`, lesen: `get_autonomous_life_state()` | ✅ getestet (interactive↔solitary) | "disabled" nicht getestet — vorsichtig, könnte Steifigkeit verlieren lassen |
| Basic Awareness an/aus | — (noch kein Wrapper, `BasicAwareness.setEnabled`) | ⚠️ nur Status gelesen | |
| Auf Person zugehen / interagieren | — (noch kein Wrapper, `HumanAwareness.makeApproachHuman`/`makeEngageHuman`) | ✅ als aufrufbar bestätigt, nicht live ausgeführt | Bewegt Roboter autonom — bewusst nicht im vollgestellten Raum getestet |
| Dialog-Skripte (Wenn-Dann-Antworten) | — (noch kein Wrapper, `ALDialog.loadTopic`/`activateTopic`) | ✅ Methode bestätigt | Braucht eigenes QiChat-Skript (.top-Datei), noch keins vorhanden |
| Webseite auf Tablet anzeigen | `showURL(url)`, `hideWebview()` | ✅ getestet | |
| Bild auf Tablet anzeigen | `showImage(url)` | ✅ vorhanden im Code | |

## Sensor-/Wahrnehmungs-Knoten (Roboter nimmt etwas wahr)

| Fähigkeit | Python-Methode (`qicli.py`) | Status | Anmerkung |
|---|---|---|---|
| Hören + Sprache verstehen (frei, per Whisper/LLM) | `flask_wrapper/stt/listen_loop.py` (eigenes Skript, nicht in qicli.py) | ✅ getestet, funktioniert | Kein `naoqi_driver2`/ROS nötig, nur SSH (PulseAudio-Umweg) |
| Hören (eingebaut, NAOqi) | — (`ALSpeechRecognition`, kein Wrapper) | ⚠️ Sprachen getestet, Erkennung selbst nicht | Nur feste Vokabelliste, kein freies Sprachverstehen |
| Kamera (Front/Unten/Tiefe/Stereo) | ROS-Topics `/camera/{front,bottom,depth,stereo}/image_raw` | ✅ getestet | ~1 Hz, 320x240 |
| Personen/Gesichter erkennen (Rohdaten) | — | ⚠️ blockiert | `HumanPerception`-Signale weder per `qicli` noch `ALMemory` abrufbar — bräuchte echte `qi`-Signal-Subscription, die am TLS-Problem hängt. **Bewusst nicht weiterverfolgt** (siehe Architektur-Entscheidung oben) |
| Personen-Stimmung (Valence/Attention) | `get_mood()` | ✅ getestet | dict mit Konfidenzwerten; leer wenn niemand erkannt |
| Peppers eigene "Stimmung" | `get_robot_mood()` | ✅ getestet | z.B. `{pleasure: positive, excitement: calm}` |
| Skelett/Pose einer Person (Kamerabild) | `vision_ws/pose_watch.py`, `vision_ws/mimic_arms.py` (eigenes YOLOv8-Skript) | ✅ getestet, funktioniert gut | Unabhängig von NAOqi, nutzt nur Kamera-Topics |
| Laser-Entfernungsmesser (Basis) | ROS-Topic `/laser` (sensor_msgs/LaserScan) | ✅ getestet | Siehe Sensor-Bewertung in STATUS.md |
| Sonar vorne/hinten | ROS-Topics `/sonar/front`, `/sonar/back` | ✅ getestet | Nur 1 Wert pro Richtung, kein Scan |
| Berührung (Kopf, Hände, Bumper) | `get_touch_status()` ODER ROS `/bumper`, `/hand_touch`, `/head_touch` | ✅ getestet | |
| Touch-Gesten (mehr als an/aus) | `get_tactile_gestures()` | ✅ getestet | Eingebaut: SingleTap, DoubleTap, TheClaw, ZoomIn/Out, Caress, SecretCode u.a. |
| IMU (Lage/Balance) | ROS-Topics `/imu/base`, `/imu/torso` | ✅ getestet | Quaternion |
| Odometrie (Position seit Start) | ROS-Topic `/odom` | ✅ getestet | |
| Akkustand | `get_battery()` | ✅ getestet | Gibt `int` (Prozent) zurück |
| Gelenkstellungen (aktuell) | `get_angle(gelenk)` / `get_angles(liste)` ODER ROS `/joint_states` | ✅ getestet | |
| Gesamt-Diagnose (Temperatur/Stiffness/Limits pro Gelenk) | ROS-Topic `/diagnostics` | ✅ getestet | Braucht Geduld beim Abonnieren (>10s Fenster) |
| Eigene Kartenerstellung | — (`Mapping.makeMap()`, kein Wrapper) | ⚠️ Service bestätigt, nicht ausgeführt | Würde Roboterbewegung zum Kartieren brauchen |

## Bekannte Einschränkungen (wichtig fürs Behavior-Tree-Design)
- **Hand-Gesten**: Peppers Hand hat nur 1 Motor (auf/zu) — keine einzelnen Finger, keine Peace-Zeichen o.ä. möglich
- **Fahren**: blockiert komplett, solange das Ladekabel dran ist
- **NAOqi-Fernzugriff**: Port 9559 ist NAOqi-intern (nur localhost) — externe Verbindungen (z.B. `naoqi_driver2`) müssen `nao_port:=9503` verwenden
- **Sensoren generell langsam**: Kamera ~1Hz, Laser/Sonar ~1.1-1.2Hz — für Verhalten, das schnelle Reaktion auf Bewegung braucht, ist das ein Flaschenhals
- **Gehaltene Posen (z.B. T-Pose) werden von "Breathing"/anderen Idle-Mechanismen verzogen**: `raise_arms_sideways()` deaktiviert Breathing schon automatisch, trotzdem hält die Pose nur ~10s (anderer, nicht identifizierter Mechanismus greift danach ein). Für kurze Gesten nutzen, nicht zum Dauerhalten.
- **Rechter Arm etwas ungenauer als linker** bei Gelenkbewegungen (kleine mechanische Kalibrierungs-Differenz dieser Einheit)
- **Gesichts-/Personenerkennung (Rohdaten)**: aktuell nicht erreichbar (siehe Tabelle oben) — bewusste Architektur-Entscheidung, SSH/qicli-Weg beizubehalten statt TLS-Problem zu lösen

## Für den Behavior Tree: grobe Knoten-Kategorien
- **Bedingungen** (Sensor-Checks): `get_touch_status()`, `get_battery() < X`, Wort/Satz erkannt (Whisper-Pipeline), Hindernis nah (Laser/Sonar-Topics), `get_mood()`
- **Aktionen**: `say()`, `set_angle()`/`wave()`/`raise_arms_sideways()`, `set_led_color()`, `showURL()`/`showImage()`, `set_posture()`, `setLanguage()`, `play_sound()`
- **Zusammengesetzt**: "Höre zu -> Wenn Text erkannt -> An LLM schicken -> `say()` die Antwort" (Kern-Loop, noch zu verdrahten, siehe STATUS.md)

Siehe auch `STATUS.md` für: den Port-9503-Fix, die Sensor-Bewertung fürs
Mapping/Lidar-Vorhaben, und den Ausblick auf Möglichkeiten mit stärkerer
Onboard-Rechenleistung.
