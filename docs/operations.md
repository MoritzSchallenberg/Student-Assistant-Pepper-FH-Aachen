# Betrieb (SSH/`pepperctl`)

Der Betrieb nach dem Deployment läuft ausschließlich über SSH und das
Bedienwerkzeug `pepperctl` (Auftrag Abschnitt 8) -- kein Ansible mehr
nötig für den Alltag.

```bash
ssh <benutzer>@<nuc>
```

## Dienste starten/stoppen

```bash
pepperctl start      # startet ihk-pepper-ros2.service + ihk-pepper-web.service
pepperctl stop
pepperctl restart
```

`start`/`stop`/`restart` rufen intern `sudo systemctl ...` auf -- der
SSH-Benutzer braucht dafür `sudo`-Rechte (normale `sudo`-Passwortabfrage,
**keine** passwortlose Sonderregel eingerichtet, siehe
`GITHUB_DEPLOYMENT_REPORT.md`).

## Status und Logs

```bash
pepperctl status     # kein sudo noetig
pepperctl logs        # letzte 100 Zeilen beider Dienste
pepperctl logs -f      # live mitverfolgen
pepperctl logs 500      # letzte 500 Zeilen
```

## Diagnose (passiv, löst nie eine Bewegung aus)

```bash
pepperctl doctor
```

Prüft: ROS2-Setup vorhanden, Workspace gebaut, Konfiguration vorhanden,
NAOqi-Port erreichbar (nur informativ), freier Speicherplatz,
Dienststatus.

Für eine ausführlichere, über Ansible laufende Diagnose (u.a. RealSense/
Mikrofon-Erkennung, GitHub-Erreichbarkeit):

```bash
ansible-playbook -i ansible/inventory/production.yml \
  ansible/playbooks/healthcheck.yml --ask-vault-pass
```

## Version anzeigen

```bash
pepperctl version
```

## Direkte ROS2-Befehle

```bash
pepperctl ros topic list
pepperctl ros node list
pepperctl ros service list
pepperctl ros action list
pepperctl ros topic echo /safety_state
```

`pepperctl ros ...` lädt automatisch `/opt/ros/jazzy/setup.bash` und
den Workspace-Overlay, bevor es `ros2 "$@"` ausführt -- alle Argumente
werden sicher als Array weitergereicht (kein `eval`, keine
String-Verkettung, siehe `pepperctl`-Quelltext).

## Autostart aktivieren (optional, standardmäßig AUS)

In `ansible/inventory/group_vars/all.yml` bzw. `production.yml`:

```yaml
enable_autostart: true
```

Dann erneut deployen oder gezielt `pepper_services`-Rolle ausführen.
**`allow_motion` bleibt davon unberührt** -- Autostart bedeutet nur,
dass die Dienste nach einem Boot laufen, nicht, dass Bewegung erlaubt
ist (siehe `docs/configuration.md`).

## Backups vor Datenbank-Migrationen

```bash
sudo cp -a /var/lib/ihk-pepper/faq_cache /var/lib/ihk-pepper/faq_cache.bak-$(date +%Y%m%d)
```

## Bekannte Betriebs-Einschränkungen

Siehe `GITHUB_DEPLOYMENT_REPORT.md`, Abschnitt "Bekannte
Einschränkungen" -- insbesondere: nichts davon wurde gegen einen
echten NUC/Pepper getestet (kein Testgerät in dieser Session
verfügbar).
