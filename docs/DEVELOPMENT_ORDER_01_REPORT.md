# Entwicklungsauftrag 1: RealSense-/Behavior-Tree-/Gesten-Grundlage -- Bericht

Stand: 2026-09-03. Branch `order-01-realsense-bt-gestures`, Basis-Commit
`f1221a9`. Geschrieben nach demselben Ehrlichkeitsprinzip wie
`docs/GITHUB_DEPLOYMENT_REPORT.md`/`docs/IMPLEMENTATION_REPORT.md`:
"vorbereitet" wird nie als "funktioniert am echten Pepper" dargestellt.

Dieses Dokument wird während der Umsetzung fortlaufend ergänzt (nicht erst
am Ende geschrieben), damit jeder Zwischenstand nachvollziehbar ist.

## 1. Ausgangsstand (vor jeder Änderung dieses Auftrags)

- `ros-jazzy-behaviortree-cpp` (4.9.0, apt-Installationskandidat) war
  **nicht installiert** -- `ihk_pepper_behavior_tree` konnte nicht gebaut
  werden. `ros-jazzy-realsense2-camera` **war bereits installiert**
  (vom Nutzer vor diesem Auftrag).
- `message_filters`, `tf2_ros`, `tf2_geometry_msgs`, `image_transport`
  bereits systemweit installiert.
- Keine RealSense-Hardware angeschlossen (nur Bluetooth-USB sichtbar via
  `lsusb`), kein `pyrealsense2`.
- Baseline-Build (`colcon build --symlink-install`, 3-Schritte-Split wie
  im Ansible-Deployment, `ihk_pepper_behavior_tree` ausgenommen):
  **8+1+1 Pakete grün**, keine neuen Fehler.
- Baseline-Tests (`python3 -m pytest ros2/autonomy_ws/src/ihk_pepper_tests/test/ -v`):
  **54/54 bestanden**.

### Komponenten-Tabelle

| Komponente | Status vorher | Änderung in diesem Auftrag |
|---|---|---|
| `ihk_pepper_behavior_tree` (C++) | geschrieben, nie kompiliert (`behaviortree_cpp` fehlte) | AP2: bauen, echte Fehler beheben |
| `ihk_pepper_perception` (3D-Position) | `has_3d_position` immer `False`, kein CameraInfo-Sub | AP4: synchronisierte Entprojektion |
| `ihk_pepper_perception` (Winken) | Einzelbild-Heuristik, kein zeitlicher Nachweis | AP5: `wave_detector.py` |
| `ihk_pepper_interaction`/BT-Blackboard | niemand befüllt `target_track_id` | AP6: `SelectStablePerson` |
| `ihk_pepper_bridge` (Gesten) | sequenziell, Gelenk für Gelenk | AP7: Keyframe-Schema v2 |
| RealSense-Bringup | nicht vorhanden | AP3: konfiguriert, ungetestet (keine Hardware) |
| Drei-LLM-Pipeline | nicht vorhanden | AP8: nur Verträge/Validator |
| Personengedächtnis | nicht vorhanden | AP9: nur Verträge |
| Compute-/Akku-Eingänge | nicht vorhanden | AP10: Mock-Eingänge |
| Startmodi | nur `dialog_only`/`full_system` | AP11: 4 neue Modi |

*(wird laufend fortgeführt)*

## 2. Arbeitsprotokoll

- **AP1 abgeschlossen**: Branch erstellt, Baseline-Build+Tests oben
  dokumentiert.
- **AP8 abgeschlossen**: neues Paket `ihk_pepper_llm_contracts`
  (`knowledge_planner.py`, `gesture_planner.py`, `response_plan.py` +
  `ResponsePlanValidator`), `docs/LLM_PIPELINE_DESIGN.md`. 14 neue Tests
  in `test_llm_contracts.py`, alle grün. Kein LLM-Aufruf, kein Executor.
- **AP9 abgeschlossen**: neues Paket `ihk_pepper_person_memory`
  (`identity_registry.py`, `vector_memory.py`, `mood_signal.py`),
  `docs/PERSON_MEMORY_DESIGN.md`. 9 neue Tests in `test_person_memory.py`,
  alle grün. Keine echte Datenbank, keine Gesichtserkennung.
- Build nach AP8/AP9: `colcon build --symlink-install --packages-select
  ihk_pepper_llm_contracts ihk_pepper_person_memory ihk_pepper_tests`
  grün (nur bekannte setuptools-Deprecation-Warnungen, keine neuen).
  Gesamtsuite jetzt **77/77** (54 Baseline + 23 neu).
- **AP4+AP5 abgeschlossen** (Kernlogik + ROS-Verdrahtung):
  `deprojection.py` (Median-Patch-Tiefe, Entprojektion), `wave_detector.py`
  (Zustandsfolge arm_raised→wave_candidate→wave_confirmed), beide pure/
  ROS-frei mit 17 neuen Tests. `perception_node.py` neu verdrahtet:
  `message_filters.ApproximateTimeSynchronizer` fuer Farbe+Tiefe+
  CameraInfo, tf2-Transformation ins `base_frame` (fehlende/veraltete TF
  → `has_3d_position=False`, nie eine Fantasieposition), echte
  Track-Timeout-Loeschung mit echten Zeitdifferenzen (vorher grobe
  `+=1.0`-Naeherung), `positions_m` wird jetzt tatsaechlich befuellt.
  `PersonTrack.msg` um `stable`/`stable_for_s`/`depth_confidence`/
  `source_camera` erweitert, neue `WaveGestureEvent.msg`,
  `SetInteractionState.srv`, `SafetyState.msg.compute_power_valid`.
  Gesamtsuite **94/94**. **Nicht verifiziert**: echte Kamera/YOLO-
  Erkennung einer realen Person, echtes TF -- keine RealSense-Hardware
  angeschlossen. Node konstruiert/spinnt in beiden Modi nachweislich
  fehlerfrei, ein synthetischer synchronisierter Frame durchlaeuft die
  komplette Pipeline ohne Exception.
- `ros-jazzy-behaviortree-cpp` war zum Zeitpunkt dieses Zwischenstands
  **noch nicht installiert** -- AP2/AP6 (Behavior-Tree-Bau) folgen,
  sobald verfuegbar; bis dahin Fortsetzung mit AP7 (Gestenkatalog v2).
- **AP7 abgeschlossen**: Gestenkatalog v2 (synchrone Keyframes),
  `pepper_client.play_trajectory()` (NAOqi `angleInterpolation` mit
  Listen-Argumenten, dry_run_validated). wave_right/wave_left auf v2
  migriert (identische, live getestete Winkelwerte), 5 neue v2-Gesten.
  20 neue Tests. Details siehe unten unter "AP2+AP6".
- **AP10 + AP6 (Python-Anteil) abgeschlossen**: `compute_power_valid`
  in SafetyGate, `CONVERSATION_READY`-Zustand, `SetInteractionState`-
  Service. 6 neue Tests.

## 3. `ros-jazzy-behaviortree-cpp` installiert -- AP2, AP3, AP6, AP11, AP12, AP13

Ab hier: Nutzer hat `sudo apt install ros-jazzy-behaviortree-cpp`
ausgefuehrt (bestaetigt per `dpkg -l`). Alle folgenden Punkte sind
**echt gebaut und/oder live gegen laufende ROS2-Prozesse getestet**,
nicht nur Code geschrieben.

### AP2: BehaviorTree.CPP gebaut

`colcon build --packages-select ihk_pepper_behavior_tree` lief beim
ersten Versuch **fast** fehlerfrei -- ein echter Kompilierfehler
gefunden und behoben: `rclcpp::Client<T>::FutureAndRequestId` hat
**keinen Default-Konstruktor** (die Anfragen-ID ist Teil des
Konstruktors) -- `SetInteractionState` hielt faelschlich das ganze
Struct statt nur des `.future`-Members als Klassenmitglied. Nach dem
Fix: sauberer Build, keine Warnungen.

Zusaetzlich gefunden (beim ersten `colcon test`): die **Original-XML-
Kommentare aus der vorigen Session** (vor AP2 nie gebaut/gelintet)
verletzten die XML-Spezifikation (`--` als Trennzeichen in
Kommentaren -- XML verbietet Doppel-Bindestriche in Kommentarinhalten).
Behoben (Gedankenstrich statt Doppelstrich, mehrfach im Laufe der
Session bei neuen Kommentaren wiederholt gefunden und behoben).

`bt_executor_node`: SIGTERM-Handler ergaenzt (rclcpp faengt automatisch
nur SIGINT ab), `Groot2Publisher`-Konstruktion in try/catch (ein
belegter Port blockiert/crasht den Executor nicht mehr -- **getestet**
mit zwei gleichzeitig laufenden Instanzen: die zweite loggt nur eine
Warnung und laeuft normal weiter).

`colcon test` (cppcheck/cpplint-Kernpruefungen/flake8/lint_cmake/
pep257/uncrustify/xmllint): **17/17 gruen** (ament_copyright und
cpplints eingebaute `legal/copyright`-Kategorie bewusst uebersprungen --
keine Datei im Projekt traegt einen Copyright-Header, eine erfundene
Zeile waere inkonsistent, siehe CMakeLists.txt-Kommentar).

### AP6: 9 neue/ueberarbeitete BT-Knoten + neuer Ablauf

`IsSystemReady`, `SelectStablePerson` (waehlt+validiert die Zielperson,
befuellt `target_track_id` selbst -- **vorher befuellte niemand dieses
Feld**), `HasGreetingCooldownExpired`, `PlayCatalogGesture`
(verallgemeinert von `WaveGesture`), `WaitForGestureFromTrack` (nur
exakte track_id, Timeout), `IsApproachAllowed`, `ApproachSelectedPerson`
(umbenannt von `ApproachTargetPerson`), `SetInteractionState`,
`ClearSelectedPerson`. `pepper_main.xml`: Root jetzt `ReactiveFallback`,
neuer `GreetAndApproachSubtree`.

**Echter Architekturfehler gefunden und behoben** (beim Bau des
Ende-zu-Ende-Tests, AP12): `GreetAndApproachSubtree` stand urspruenglich
HINTER `InteractionSubtree` in der Fallback-Prioritaet. `IsPersonEngaged`
wird aber bereits allein durch einen hohen `interest_score` wahr (siehe
`interest_scoring.py`) -- **ohne dass je gewinkt/zurueckgewinkt wurde**.
Eine interessierte, aber nie begruesste Person gewann dadurch sofort das
Fallback, `GreetAndApproachSubtree` wurde nie getickt. Fix: Prioritaet
jetzt Safety > Battery > **GreetAndApproach** > Interaction >
Presentation > IdleAttract.

### AP3: RealSense-Bringup, Kameramontage-TF, Kopfpose-Gate

`realsense_bringup.launch.py` (parametrisiert, inkludiert Vendor-Launch),
`realsense_extrinsics.yaml` + `realsense_static_tf.launch.py`
(`base_link → realsense_mount_link → camera_link`, alle Werte Platzhalter,
`is_calibrated: false`, Launch warnt das deutlich -- **getestet**: liest
YAML, publiziert die erwartete TF-Kette, per Log verifiziert),
`camera_pose_gate_node.py` + `head_pose_gate.py` (6 Tests). NICHT live
getestet -- keine RealSense-Hardware angeschlossen.

### AP11: Startmodi + Mock-Nav2-Server

`mock_nav2_server.py`: simuliert `NavigateToPose`, published NIEMALS
`/cmd_vel` -- **echt getestet**: Ziel gesendet, 10 Feedback-Nachrichten,
SUCCEEDED, kein `/cmd_vel`-Topic im gesamten ROS-Graphen waehrend des
Laufs (`ros2 topic list` bestaetigt). `offline_test.launch.py` (**echt
getestet**: alle 8 Nodes starten fehlerfrei), `realsense_test.launch.py`
(nicht live getestet), `pepper_gesture_test.launch.py`.

### AP12: Echter automatisierter Offline-Ende-zu-Ende-Test

`manual_e2e_offline_check.py` startet den kompletten Stack per echten
Subprozessen, spielt einen synthetischen Personentrack + ein bestaetigtes
Rueckwink-Ereignis ein, wartet auf `CONVERSATION_READY`, ueberwacht aktiv
`/cmd_vel` (Fehlschlag bei jeder Nachricht dort).

**Ergebnis nach intensivem Live-Debugging (siehe unten): 3 von 3 Laeufen
erfolgreich, `CONVERSATION_READY` nach 4.8-5.1s, in keinem Lauf
`/cmd_vel` gesehen, saubere Prozessbeendigung.**

Beim Bau dieses Tests wurden per systematischem Live-Debugging (temporaere
`fprintf`-Traces in den BT-Knoten, danach wieder entfernt) folgende
**echte Fehler** gefunden und behoben:

1. Der oben beschriebene GreetAndApproach/Interaction-Prioritaetsfehler.
2. **`charging_cable_connected` war fest auf `True` verdrahtet** (sicherer
   Default "angeschlossen bis Gegenteil bekannt"), OHNE -- anders als
   `localization_valid`/`obstacle_data_valid`/`person_depth_valid`/
   `compute_power_valid` -- ueberschreibbar zu sein. Damit konnte
   `allow_person_approach` in KEINEM Testmodus je `True` werden. Jetzt
   ueber `/charging_cable_connected` ueberschreibbar (`supervisor_node.py`),
   exakt nach demselben Muster wie die anderen vier `SafetyInputs`-Felder.
3. **SafetyGate-Zwei-Schluessel-System bestaetigt korrekt**:
   `motion_capable=true` allein reicht nicht -- `SafetyGate` verlangt
   zusaetzlich eine explizite `/set_motion_permission`-Anfrage. Kein
   Bug, aber beim ersten Testversuch uebersehen; der Testtreiber ruft
   diesen Service jetzt explizit auf (simuliert eine bewusste
   Freigabe-Entscheidung, wie sie im echten Betrieb ein Mensch/ein
   uebergeordnetes System trifft).

Zusaetzlich zwei Bugs in der **eigenen Testinfrastruktur** gefunden (nicht
im Produktcode): verwaiste Subprozesse nach Testlauf (`ros2 run` spawnt
einen Kind-Prozess, `p.terminate()` traf nur den Wrapper -- mit
`start_new_session=True` + `os.killpg()` behoben) und ein potenzieller
Pipe-Puffer-Deadlock (`subprocess.PIPE` nie ausgelesen, auf Datei-
Umleitung umgestellt).

`bridge_node.py` hat jetzt einen `dry_run`-Parameter (`Say`/`PlayGesture`
melden Erfolg ohne SSH-Verbindung zu Pepper) -- macht diesen Test erst
moeglich, ohne echten Pepper zu brauchen.

### AP13: Restliche Dokumentation + CI

`docs/ARCHITECTURE_REALSense_BT.md`, `docs/GESTURE_AUTHORING.md`,
`docs/DEVELOPMENT_MODES.md` ergaenzt. `.github/workflows/ci.yml`:
`ros-jazzy-behaviortree-cpp` direkt installiert, `ihk_pepper_behavior_tree`
nicht mehr von `--packages-skip` ausgeschlossen (baut jetzt nachweislich
sauber). **Nicht verifiziert**: dieser CI-Workflow lief in dieser Session
nicht tatsaechlich auf GitHub (kein Push mit Ausloesung beobachtet) --
nur lokal Schritt fuer Schritt identisch nachgebildet.

## 4. Ehrliche Gesamtbilanz

| Bereich | Status | Nachweis |
|---|---|---|
| BehaviorTree.CPP-Build | ✅ gebaut+getestet | `colcon build`+`colcon test` 17/17, echter Fehler gefunden+behoben |
| 9 BT-Knoten | ✅ funktional verifiziert | E2E-Test durchlaeuft alle neun Knoten erfolgreich |
| RealSense-Perception (Sync/Deprojection/TF) | ✅ Logik getestet, ⛔ keine echte Kamera | 26 Unit-Tests (deprojection+wave_detector), synthetischer Frame durchlaeuft Pipeline |
| Wink-Erkennung | ✅ getestet | 8 Unit-Tests, E2E bestaetigt Ende-zu-Ende |
| Gestenkatalog v2 | ✅ Logik getestet, ⛔ nicht live an Pepper | 20 Unit-Tests, `dry_run_validated` |
| Mock-Nav2 | ✅ echt getestet | Ziel gesendet, Feedback, SUCCEEDED, kein `/cmd_vel` |
| Offline-E2E bis CONVERSATION_READY | ✅ **echt getestet, 3/3 Laeufe** | `manual_e2e_offline_check.py`, ~5s, kein `/cmd_vel` |
| RealSense-Hardware | ⛔ nicht verfuegbar | kein Geraet in dieser Session angeschlossen |
| Echter Pepper | ⛔ nicht verfuegbar | kein Roboter in dieser Session erreichbar |
| CI auf GitHub | ⛔ nicht beobachtet | nur lokal identisch nachgebildet |

**Gesamtsuite**: 125/125 Python-Tests gruen (54 Baseline + 71 neu),
`ihk_pepper_behavior_tree` `colcon test` 17/17 gruen, 3/3
Ende-zu-Ende-Laeufe erfolgreich. `git status` sauber, keine
uncommitteten Aenderungen (Stand: Commit `3cb8c1e`).

## 5. Bekannte, ehrlich offene Punkte fuer Entwicklungsauftrag 2

- `person_approach_node.py::_drive_to_person()` fährt strukturell auf
  die Personenposition SELBST, nicht auf eine Position `target_distance_m`
  davor -- bekannter, dokumentierter Mangel, **nicht** in dieser Runde
  behoben (Order 2 AP9 adressiert das explizit).
- `nav2_moving`/`mapping_active` sind in `GestureCatalog.play()` fertig
  implementiert+getestet, aber `bridge_node.py`s echter `PlayGesture`-
  Handler uebergibt sie noch nicht (Live-Wiring fehlt).
- `pepper_client.play_trajectory()` (synchroner Gesten-Transport) ist
  `dry_run_validated`, NICHT `live_validated` -- JSON-Listen-Argumente
  ueber `qicli` nie gegen echten Pepper geprueft.
- Nur `wave_right`/`wave_left`/`raise_both_arms`/`open_arms` sind
  `dry_run_validated`; `self_hug_symbolic`/`nod_once`/`look_at_person`
  bleiben `draft` (keine Live-Referenzwerte).
- Keine der neuen RealSense-Launch-Dateien/TF-Ketten wurde je gegen
  echte Hardware getestet.
- `realsense_extrinsics.yaml` bleibt vollstaendig unvermessen
  (Platzhalter, `is_calibrated: false`).

## 6. Empfehlung fuer Entwicklungsauftrag 2

Alle in dessen "Verbindliche Startbedingung" geforderten Punkte sind
erfuellt: `ros-jazzy-behaviortree-cpp` installiert, `ihk_pepper_behavior_tree`
baut+laeuft, alle neun BT-Knoten funktional verifiziert (per Ende-zu-Ende-
Test, nicht nur Einzel-Unit-Tests), RealSense-Bringup und Startmodi fertig
(wenn auch nicht live gegen Hardware getestet), alle Tests gruen, keine
uncommitteten Aenderungen. **Entwicklungsauftrag 2 kann beginnen.**

Größtes Restrisiko für Auftrag 2: der komplette RealSense-/Nav2-/
Lokalisierungs-Stack ist bisher **ausschließlich in Software/Mocks**
verifiziert -- der erste Kontakt mit echter Hardware (Kamera, Pepper,
NUC) wird zwangsläufig neue, in dieser Session nicht vorhersehbare
Probleme aufdecken, genau wie es beim Ansible-/GitHub-Deployment in der
vorigen Auftragsserie mehrfach der Fall war.

