# NUC bootstrappen

Bereitet einen frischen Ubuntu-24.04-NUC für IHK-Pepper vor (Auftrag
Abschnitt 4). Idempotent -- mehrfaches Ausführen ändert nach dem ersten
erfolgreichen Lauf nichts mehr (`changed=0`).

**Wichtig**: Alle `ansible`/`ansible-playbook`/`ansible-vault`-Befehle
unten werden aus dem `ansible/`-Verzeichnis heraus ausgeführt (`cd
ansible` zuerst) -- sonst wird `ansible.cfg` nicht automatisch geladen
und Rollen/Inventory werden nicht gefunden (Fehler `The role 'base' was
not found in: .../ansible/playbooks/roles:...`, siehe
`docs/troubleshooting.md`).

## Voraussetzungen

- NUC mit frisch installiertem Ubuntu 24.04 (Server oder Desktop)
- SSH-Zugriff mit einem Benutzer, der `sudo`-Rechte hat
- Ansible auf dem Entwicklungsrechner installiert:
  ```bash
  pip3 install --user ansible
  cd ansible
  ansible-galaxy collection install -r requirements.yml
  ```

## 1. Inventory anlegen

```bash
cd ansible   # falls noch nicht dort
cp inventory/production.example.yml inventory/production.yml
```

`ansible/inventory/production.yml` bearbeiten:

```yaml
all:
  children:
    pepper_nuc:
      hosts:
        nuc:
          ansible_host: "<NUC-IP-ODER-HOSTNAME>"
          ansible_user: "<SSH-BENUTZER-MIT-SUDO>"
          ansible_python_interpreter: /usr/bin/python3
          pepper_qi_host: "<PEPPER-IP-IM-LAN>"
```

Diese Datei bleibt lokal (siehe `.gitignore`) -- sie enthält
Standort-spezifische, aber nicht geheime Werte.

## 2. Geheimnisse anlegen

```bash
cd ansible   # falls noch nicht dort
cp inventory/group_vars/vault.yml.example inventory/group_vars/vault.yml
# echte Werte eintragen, dann:
ansible-vault encrypt inventory/group_vars/vault.yml
```

Vault-Passwort sicher aufbewahren (Passwort-Manager, NICHT im Repo,
NICHT im Klartext auf dem NUC). Beim Verschlüsseln fragt
`ansible-vault` das Passwort zweimal ab (Eingabe + Bestätigung) -- bei
"Passwords do not match" einfach den Befehl erneut ausführen und
beide Male exakt dasselbe eintippen.

## 3. Erreichbarkeit prüfen

```bash
cd ansible   # falls noch nicht dort
ansible pepper_nuc -i inventory/production.yml -m ping --ask-vault-pass
```

## 4. Bootstrap ausführen

```bash
cd ansible   # falls noch nicht dort
ansible-playbook -i inventory/production.yml \
  playbooks/bootstrap.yml --ask-vault-pass
```

Das Playbook installiert (siehe `ansible/roles/base`, `ros2_jazzy`,
`pepper_dependencies` für die genauen Aufgaben):

- Grundpakete (Git, Python3, Build-Tools)
- Unprivilegierten Laufzeitbenutzer `pepper` (Gruppen: audio, video,
  plugdev, dialout)
- Projekt-/Konfigurations-/Daten-/Log-Verzeichnisse
  (`/opt/ihk-pepper`, `/etc/ihk-pepper`, `/var/lib/ihk-pepper`,
  `/var/log/ihk-pepper`)
- ROS2 Jazzy (`ros-base`, **kein** Desktop/RViz -- das läuft auf dem
  Entwicklungsrechner) + `rosdep`/`colcon`
- Audio-/Kamera-Systempakete (PulseAudio-Werkzeuge, `ffmpeg`,
  `v4l-utils`) -- der bestehende PulseAudio-Audio-Workaround (siehe
  `STATUS.md`) wird dabei **nicht** verändert, nur die dafür nötigen
  Pakete/Rechte sichergestellt
- Optional RealSense-SDK (nur wenn `realsense_enabled: true`)

## 5. Zweiter Lauf (Idempotenz-Nachweis)

```bash
cd ansible   # falls noch nicht dort
ansible-playbook -i inventory/production.yml \
  playbooks/bootstrap.yml --ask-vault-pass
```

Erwartung: `changed=0` (oder nahe null -- z.B. `apt update` meldet
`changed` nur bei tatsächlich neuer Paketliste).

## Danach

Weiter mit `docs/deployment.md` für das erste Deployment.
