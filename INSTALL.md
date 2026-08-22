# Installation / Setup

Dieses Repo enthält nur den eigentlichen Code. Große/generierte Sachen
(virtuelle Umgebungen, ROS2-Build-Ordner, heruntergeladene Pakete,
Modell-Gewichte, Screenshots, Logs) sind **nicht** mit hochgeladen — die
werden mit den Befehlen hier neu erzeugt. Auf dem Ursprungsrechner liegen
sie zusätzlich unter `large_files/` (siehe `.gitignore`).

Getestet auf: Ubuntu 24.04 (Noble), ROS2 Jazzy.

## 0. Voraussetzungen
```bash
# ROS2 Jazzy muss bereits installiert sein (ros-base oder desktop):
# https://docs.ros.org/en/jazzy/Installation.html
sudo apt install -y python3-venv python3-pip \
  ros-jazzy-rviz2 \
  ros-jazzy-joint-state-publisher-gui \
  ros-jazzy-robot-state-publisher \
  ros-jazzy-depth-image-proc \
  android-tools-adb
pip3 install --user --break-system-packages vcstool
```

## 1. `flask_wrapper` (Sprechen, LLM-Anbindung, Hören/Whisper)
```bash
cd flask_wrapper
python3 -m venv --system-site-packages venv   # --system-site-packages: rclpy bleibt erreichbar
source venv/bin/activate
pip install flask python-dotenv paramiko requests faster-whisper
```
Danach vor jeder Nutzung: `source /opt/ros/jazzy/setup.bash` UND
`source venv/bin/activate` (Reihenfolge egal), siehe `STATUS.md` für
Beispiel-Befehle.

**Credentials**: `config/config.py` enthält Pepper-IP/Passwort für euer
Setup — beim Klonen ggf. anpassen (aktuelle Werte siehe `STATUS.md`).

## 2. `vision_ws` (Kamera, YOLO-Pose-Erkennung/Nachahmung)
```bash
cd vision_ws
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install ultralytics paramiko
pip install "numpy<2"   # WICHTIG: neueres numpy crasht cv_bridge (ABI-Konflikt), siehe STATUS.md
```
Das YOLO-Modell (`yolov8n-pose.pt`, ~6.6MB) lädt sich beim ersten Start
von `pose_watch.py`/`mimic_arms.py` automatisch herunter, wenn es nicht
im Ordner liegt.

## 3. `ros2_ws` (naoqi_driver2 -- ROS2-Anbindung an Pepper)
Alles darin ist Fremdcode (offizielle ros-naoqi-Pakete), wird per Skript
neu geklont, nicht manuell heruntergeladen:
```bash
mkdir -p ros2_ws/src && cd ros2_ws/src
git clone https://github.com/ros-naoqi/naoqi_driver2.git
~/.local/bin/vcs import < naoqi_driver2/dependencies.repos
cd ..
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```
Dauert ca. 5 Minuten (C++-Build von libqi/libqicore/naoqi_driver).
Danach vor jeder Nutzung zusätzlich zu ROS2 selbst:
`source ros2_ws/install/setup.bash`

**Wichtig**: externe ROS2-Verbindungen zu Pepper brauchen
`nao_port:=9503` (nicht den Default 9559) -- siehe `STATUS.md`, Abschnitt
"GELOEST: NAOqi-Port-9559-Blocker" für den genauen Startbefehl.

## 4. `pepper_model_export` (Offline-Simulation, kein Pepper nötig)
Ist bereits vollständig eigenständig (URDF + Meshes liegen als echte
Dateien bei, kein Download nötig). Nur bauen:
```bash
cd pepper_model_export
source /opt/ros/jazzy/setup.bash
colcon build
source install/setup.bash
ros2 launch pepper_description display_scripted.launch.py   # RViz, offline
# in einem zweiten Terminal:
python3 sim_qicli.py
```

## 5. Netzwerk-Setup (nur falls ihr euch per Kabel mit einem echten Pepper verbindet)
`setup_pepper_dhcp.sh` richtet eine feste IP-Reservierung für Pepper über
NetworkManager ein. Vor dem Ausführen die MAC-Adresse/IP-Range im Skript
an euer Setup anpassen (siehe Kommentare darin und `STATUS.md`, Abschnitt
"Netzwerk").

## 6. `pepper_autonomy_ws` (Dialog-/Interaktions-/Navigationssystem)
```bash
cd pepper_autonomy_ws
source /opt/ros/jazzy/setup.bash
pip3 install --user --break-system-packages paramiko PyYAML python-dotenv lap

# Alle Pakete AUSSER ihk_pepper_dialog (numpy<2, kompatibel mit cv_bridge):
colcon build --symlink-install --packages-skip ihk_pepper_dialog
source install/setup.bash

# ihk_pepper_dialog braucht numpy>=2 (sentence-transformers) -- eigenes venv:
python3 -m venv --system-site-packages venv_dialog
source venv_dialog/bin/activate
pip install sentence-transformers
python3 -m colcon build --packages-select ihk_pepper_dialog   # NICHT bare 'colcon'!
deactivate
```
Start (siehe `IMPLEMENTATION_REPORT.md` für die vollständige, getestete
Startreihenfolge):
```bash
set -a && source flask_wrapper/.env && set +a
source /opt/ros/jazzy/setup.bash
source pepper_autonomy_ws/install/setup.bash
ros2 launch ihk_pepper_bringup dialog_only.launch.py
```
**Navigation/Nav2** ist vorbereitet, aber die zugrunde liegenden Pakete
sind **nicht installiert** (kein sudo-Zugriff während der Entwicklung):
```bash
sudo apt install ros-jazzy-navigation2 ros-jazzy-nav2-bringup \
  ros-jazzy-slam-toolbox ros-jazzy-robot-localization \
  ros-jazzy-depthimage-to-laserscan ros-jazzy-twist-mux \
  ros-jazzy-nav2-collision-monitor ffmpeg
```
Fahren bleibt danach trotzdem gesperrt, bis `motion_capable:=true`
**und** gültige Sensordaten vorliegen (Auftrag: keine unbeaufsichtigten
Fahrtests) -- siehe `IMPLEMENTATION_REPORT.md`, Abschnitt "Sicherheit".

## Weiterführende Doku
- **`STATUS.md`** -- vollständiger Projektstand, alle gelösten Probleme,
  Netzwerk-Konfiguration, Sensor-Bewertung, Architektur-Entscheidungen
- **`CAPABILITIES.md`** -- was Pepper alles kann, mit Python-Methode
  (`pepper/qicli.py`) und Teststatus pro Fähigkeit -- Grundlage für den
  Behavior Tree
- **`IMPLEMENTATION_REPORT.md`** -- ehrlicher Statusbericht zum
  Dialog-/Interaktions-/Navigationssystem (`pepper_autonomy_ws/`): was
  fertig+getestet ist, was nur vorbereitet ist, bekannte Bugs,
  Sicherheitshinweise, vollständige Start-/Installbefehle
