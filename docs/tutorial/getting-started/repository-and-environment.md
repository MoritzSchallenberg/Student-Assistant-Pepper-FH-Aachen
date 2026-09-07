# Repository und Umgebung

{{ foundation }}

## Was diese Seite ist

Der Weg vom frischen Checkout zu einer Umgebung, in der du den
ROS-2-Workspace baust und die Testsuite ausführst — vollständig offline,
ohne Pepper oder RealSense.

## Repository-Layout

```text
apps/web/          Flask-Weboberfläche, Sprechen, LLM-Anbindung, STT,
                    Tablet-UI (venv: apps/web/venv)
vision/             YOLO-Pose-Erkennung/Nachahmung (venv: vision/venv)
ros2/robot_model/   Pepper-URDF/Meshes für RViz
ros2/autonomy_ws/   Das eigentliche Autonomiesystem -- 11 ROS2-Pakete
                    unter src/ (ihk_pepper_*)
ansible/            NUC-Bootstrap und Deployment
docs/               Bestehende Projektdokumentation (Status, Architektur,
                    Entwicklungsauftrags-Berichte) -- siehe
                    [Referenz](../reference/index.md) für die Verweise
docs/tutorial/      Dieses Tutorial (Sphinx/MyST, eigener Build)
```

## Der Autonomie-Workspace: `ros2/autonomy_ws/src/`

Elf Pakete, siehe [ROS 2](../ros2/index.md) für den vollständigen
Überblick:

```text
ihk_pepper_interfaces      Messages/Services/Actions
ihk_pepper_bridge          Pepper-Steuerung als ROS2-Actions (Say,
                            PlayGesture), Gestenkatalog, Kinematik-Compiler
ihk_pepper_perception      Personen-Tracking, Interessens-Score,
                            Winkgesten-Erkennung
ihk_pepper_navigation      RealSense-Diagnose, RTAB-Map-Anbindung,
                            Annäherungsgeometrie
ihk_pepper_interaction     Interaktions-FSM, Sicherheits-Supervisor,
                            Motion Guard
ihk_pepper_llm_contracts   Drei-LLM-Pipeline (Verträge + Laufzeit)
ihk_pepper_person_memory   Identity Registry + Vector Memory (SQLite)
ihk_pepper_dialog          Dialog-FSM, FAQ-Cache, RunDialogue-Action-Server
ihk_pepper_presentation    Tagesthema/Video/Quiz
ihk_pepper_behavior_tree   BehaviorTree.CPP-Baum (C++)
ihk_pepper_bringup         Start-Launch-Dateien für alle Modi
ihk_pepper_tests           384 pytest-Tests
```

## Workspace bauen

`ihk_pepper_dialog` braucht ein eigenes virtuelles Environment
(`venv_dialog`, wegen `sentence-transformers`) und wird deshalb beim
Standard-Build übersprungen:

```bash
cd ros2/autonomy_ws
colcon build --symlink-install --packages-skip ihk_pepper_dialog
```

**Erwartetes Ergebnis**: alle verbleibenden zehn Pakete bauen fehlerfrei
(nur Deprecation-Warnungen, keine Fehler) — siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md` für den zuletzt dokumentierten
Lauf.

## Testsuite ausführen

Der ROS2-Workspace muss überlagert sein, bevor `pytest` die
`ihk_pepper_*`-Pakete importieren kann:

```bash
source /opt/ros/jazzy/setup.bash
cd ros2/autonomy_ws
source install/setup.bash
python3 -m pytest src/ihk_pepper_tests/test/ -q
```

**Tatsächlich ausgeführt und bestätigt** (für dieses Tutorial, nicht nur
aus dem Bericht übernommen): **384/384 grün** in 3,71s.
Kein einziger dieser Tests benötigt Pepper- oder RealSense-Hardware —
sie prüfen reine Logik-Module (z.B. `motion_guard.py`,
`coverage_analysis.py`, `gesture_catalog.py`) und, wo ROS2 involviert
ist, echte Node-Starts gegen Mock-/Dry-Run-Gegenstellen.

Der C++-Verhaltensbaum wird separat getestet:

```bash
colcon test --packages-select ihk_pepper_behavior_tree
colcon test-result --verbose
```

**Tatsächlich ausgeführt und bestätigt**: **17 Tests, 0 Fehler, 0
Failures, 3 übersprungen** (unverändert seit Entwicklungsauftrag 1).

## Bekannte Umgebungs-Eigenheit

Nach mehreren `colcon build --packages-select`-Läufen kann
`AMENT_PREFIX_PATH` für ein einzelnes Paket fehlen, sodass `ros2 run`/
`ros2 launch` es nicht findet, obwohl `colcon build`/`pytest` fehlerfrei
liefen (dokumentiert in `docs/DEVELOPMENT_ORDER_02_REPORT.md`,
AP4-Nebenbefund, seither wiederkehrend beobachtet). Abhilfe: sauberer
Voll-Build aller Pakete statt einzelner `--packages-select`-Läufe, oder
`source install/setup.bash` erneut ausführen.

## Nächster Schritt

[Systemarchitektur](../architecture/index.md).
