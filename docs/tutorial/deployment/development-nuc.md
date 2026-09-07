# Entwicklung auf dem allgemeinen NUC

{{ documented }}

## Was diese Seite ist

Der heutige Entwicklungsstand (ein allgemeiner Rechner, kein dedizierter
Pepper-NUC) und der vollständig vorbereitete, aber bisher nie gegen
echte Zielhardware ausgeführte Ansible-Weg dorthin.

## Heute: Entwicklung auf einem allgemeinen Rechner

Die gesamte Rechenlast (Whisper, YOLO, ROS2-Verarbeitung, Flask) läuft
auf dem Entwicklungsrechner, verbunden mit Pepper per Kabel/WLAN (siehe
[Netzwerk und Zugriff](../pepper-platform/network-and-access.md)). Das
ist der Stand, gegen den auch dieses Tutorial selbst entwickelt und
geprüft wurde.

## Der vorbereitete Weg: dedizierter Pepper-NUC

```text
/opt/ihk-pepper/
├── current -> releases/<commit-id>
├── releases/
│   ├── <commit-id-1>/
│   └── <commit-id-2>/
└── shared/
    └── venv_dialog/   (bleibt ueber Releases hinweg erhalten)
```

### 1. Bootstrap (einmalig, idempotent)

```bash
cd ansible
cp inventory/production.example.yml inventory/production.yml
# inventory/production.yml bearbeiten: NUC-IP, SSH-Benutzer, Pepper-IP
ansible-playbook -i inventory/production.yml \
  playbooks/bootstrap.yml --ask-vault-pass --ask-become-pass
```

Installiert: Grundpakete, einen unprivilegierten Laufzeitbenutzer
`pepper` (Gruppen `audio`/`video`/`plugdev`/`dialout`), Projekt-
/Konfigurations-/Daten-/Log-Verzeichnisse
(`/opt/ihk-pepper`, `/etc/ihk-pepper`, `/var/lib/ihk-pepper`,
`/var/log/ihk-pepper`), **ROS2 Jazzy ros-base ohne Desktop/RViz** (das
läuft auf dem Entwicklungsrechner), Audio-/Kamera-Systempakete, optional
das RealSense-SDK (nur bei `realsense_enabled: true`).

**Zweiter Lauf zum Idempotenz-Nachweis**: erwartet `changed=0`.

### 2. Deployment (versioniert, rücksetzbar)

```bash
cd ansible
ansible-playbook -i inventory/production.yml \
  playbooks/deploy.yml -e deploy_revision=main \
  --ask-vault-pass --ask-become-pass
```

Vierzehn Schritte, siehe `ansible/roles/pepper_deploy/tasks/`:
Betriebssystem/Speicherplatz prüfen, Commit auschecken, Requirements
installieren, `colcon build`, `pytest`-Suite ausführen, **passiver
Healthcheck** (löst keine Bewegung aus) -- **erst danach** wird
`current` atomar umgeschaltet, dann laufende Dienste kontrolliert neu
gestartet.

**Bei einem Fehler in den ersten zehn Schritten bleibt die zuvor aktive
Version unverändert aktiv.** Laufzeitdaten (FAQ-Cache, Karten, Modelle)
liegen unter `/var/lib/ihk-pepper/` — außerhalb jedes Release-
Verzeichnisses, ein Deployment/Rollback berührt sie nie.

## `realsense_enabled`: bewusst `false` als Default

`ansible/roles/pepper_dependencies/defaults/main.yml` enthält ein
`realsense_enabled`-Flag (Default `false`), das die RealSense-APT-
Repository-Einrichtung und den zugehörigen Healthcheck gattert --
**bewusst nicht auf `true` voreingestellt**: ob eine Zielmaschine
tatsächlich physisch eine RealSense montiert hat, kann keine Ansible-
Rolle von sich aus wissen. Explizit vom Nutzer/der Inventory beim
tatsächlichen Deployment zu setzen.

## Nach dem Deployment

```bash
ssh <benutzer>@<nuc>
pepperctl status
pepperctl logs
```

## Verifikationsstand, Sicherheit und Einschränkungen

{{ documented }} Die Ansible-Rollen und Playbooks sind real vorhanden
und in `docs/nuc-bootstrap.md`/`docs/deployment.md` (Wurzelverzeichnis)
detailliert beschrieben. **Kein Bootstrap und kein Deployment wurde für
dieses Tutorial gegen einen echten NUC ausgeführt** --
{{ hwverificationrequired }}. Syntaktische Prüfung
(`ansible-playbook --syntax-check`) ist risikofrei ohne Zielsystem
möglich.

## Nächster Schritt

[Referenz](../reference/index.md).
