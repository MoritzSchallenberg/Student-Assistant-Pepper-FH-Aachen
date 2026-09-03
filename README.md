# Pepper-Projekt (IHK Aachen)

Anbindung eines Pepper-1.8-Roboters (NAOqi 2.9.5.172) an einen PC unter
Ubuntu 24.04 / ROS2 Jazzy für autonome soziale Interaktion: Sprechen,
Zuhören, Sehen (Personen-/Posenerkennung), Bewegen, ein FAQ-/LLM-gestütztes
Dialogsystem, Tagesthemen-Präsentationen, eine Tablet-Oberfläche und eine
vorbereitete (nicht standardmäßig aktive) Nav2-Navigation.

**Aktueller Stand**: Grundfunktionen (Sprechen, Hören, Sehen, Bewegen)
sind live gegen den echten Roboter getestet. Das darauf aufbauende
Dialog-/Interaktions-/Navigationssystem (`ros2/autonomy_ws/`) wurde
offline entwickelt und getestet (Pepper war während dieser Entwicklung
nicht angeschlossen) -- der ehrliche, vollständige Status steht in
[`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md).

## Schnellstart

```bash
# 1) Abhängigkeiten installieren, siehe docs/INSTALL.md für Details
# 2) Credentials setzen (nie ins Repo committen):
cp apps/web/.env.example apps/web/.env
# .env mit echten Werten füllen

# 3) Kern-Dialogsystem starten:
set -a && source apps/web/.env && set +a
source /opt/ros/jazzy/setup.bash
source ros2/autonomy_ws/install/setup.bash
ros2 launch ihk_pepper_bringup dialog_only.launch.py

# 4) Tablet-/Admin-Oberfläche (eigenes Terminal):
cd apps/web && ./run.sh
# -> http://<PC-IP>:5000/         Admin-Panel (manuelle Steuerung)
# -> http://<PC-IP>:5000/tablet/  Tablet-Oberfläche (für Peppers Tablet)
```

Vollständige, geprüfte Install-/Startbefehle: siehe
[`docs/INSTALL.md`](docs/INSTALL.md) und [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md).

## Architektur (Kurzüberblick)

```
Pepper (NAOqi) --SSH/qicli--> apps/web/pepper/qicli.py
                                        |
                    +-------------------+-------------------+
                    |                                       |
         apps/web/app.py                  ihk_pepper_bridge (ROS2)
         (manuelle Steuerung,                   (Say/PlayGesture-Actions,
          Tablet-UI-Backend)                     SystemHealth-Topic)
                                                        |
                                        +---------------+----------------+
                                        |               |                |
                              ihk_pepper_audio  ihk_pepper_dialog  ihk_pepper_perception
                              (Zuhören/Whisper)  (FAQ+AnythingLLM)  (YOLO-Personentracking)
                                        |               |                |
                                        +-------+-------+----------------+
                                                |
                                    ihk_pepper_interaction
                                (Interaktions-FSM + Sicherheits-Supervisor,
                                 motion_capable-Kill-Switch)
                                                |
                              +-----------------+------------------+
                              |                                    |
                  ihk_pepper_presentation                ihk_pepper_navigation
                  (Tagesthema/Video/Quiz)         (Laser-Filter/Zonen/Nav2 -- vorbereitet,
                                                    Nav2 selbst nicht standardmäßig aktiv)
```

Alle Pakete unter `ros2/autonomy_ws/src/`, Gesamtstart über
`ihk_pepper_bringup`. Details, Topic-/Service-/Action-Liste und
Testabdeckung: [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md).

## Verzeichnisse

| Verzeichnis | Inhalt |
|---|---|
| `apps/web/` | Sprechen, LLM-Anbindung, Hören (Whisper), Tablet-/Admin-Weboberfläche |
| `vision/` | Kamera, YOLO-Pose-Erkennung/Nachahmung |
| `ros2_ws/` | `naoqi_driver2` -- ROS2-Anbindung an Pepper (Fremdcode) |
| `ros2/robot_model/` | Offline-Simulation (URDF/RViz, kein Pepper nötig) |
| `ros2/autonomy_ws/` | Dialog-/Interaktions-/Navigationssystem (11 ROS2-Pakete) |
| `ansible/` | Bootstrap/Deployment/Rollback/Healthcheck für einen Pepper-NUC |
| `scripts/` | Einmalige Host-Setup-Skripte (z.B. Netzwerk-Konfiguration) |
| `docs/` | Deployment-Dokumentation (GitHub-Setup bis Troubleshooting) |
| `large_files/` | Große/generierte Dateien, per Symlink eingebunden (siehe `.gitignore`) |

## Dokumentation

- [`docs/INSTALL.md`](docs/INSTALL.md) -- Installation/Setup, Schritt für Schritt
- [`docs/STATUS.md`](docs/STATUS.md) -- Vollständiger Projektstand, Netzwerk-Setup,
  Sensor-Bewertung, Architektur-Entscheidungen, gelöste Probleme
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) -- Was Pepper alles kann, mit
  Beispiel-Code und Teststatus je Fähigkeit
- [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md) -- Ehrlicher
  Statusbericht zum Dialog-/Interaktions-/Navigationssystem: was
  fertig+getestet ist, was nur vorbereitet ist, bekannte Bugs,
  Sicherheitshinweise, Next Steps
- [`docs/GITHUB_DEPLOYMENT_REPORT.md`](docs/GITHUB_DEPLOYMENT_REPORT.md) --
  ehrlicher Statusbericht zu GitHub-Repo/Ansible-Deployment/NUC-Betrieb

## Deployment auf einen Pepper-NUC

Das Projekt lässt sich reproduzierbar per Ansible auf einen dauerhaft
mit Pepper verbundenen Intel-NUC ausrollen (versioniert, rücksetzbar,
ohne automatische Bewegung):

```bash
cd ansible
ansible-playbook -i inventory/production.yml playbooks/deploy.yml \
  --ask-vault-pass --ask-become-pass
```

**Wichtig**: Ansible-Befehle müssen aus dem `ansible/`-Verzeichnis
gestartet werden, sonst wird `ansible.cfg` nicht geladen und die
Rollen sind nicht auffindbar (siehe `docs/GITHUB_DEPLOYMENT_REPORT.md`,
Abschnitt "Bekannte Einschränkungen").

Vollständiger Ablauf (Repo anlegen → NUC bootstrappen → deployen →
per SSH/`pepperctl` bedienen → Rollback): siehe [`docs/`](docs/),
Startpunkt [`docs/github-setup.md`](docs/github-setup.md).

## Sicherheit

Autonome Bewegung (Fahren, Personen anfahren/begleiten/verfolgen) ist
**standardmäßig deaktiviert** (`motion_capable:=false`) und erfordert
sowohl einen expliziten Launch-Parameter als auch gültige Lokalisierungs-/
Hindernis-/Tiefendaten zur Laufzeit -- siehe
[`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md), Abschnitt
"Sicherheitsrelevante Hinweise". Keine unbeaufsichtigten Fahrtests am
echten Roboter.
