# Abschlussbericht: GitHub- und Ansible-Deployment für den Pepper-NUC

Stand: 2026-08-22. Bezieht sich auf den Entwicklungsauftrag "GitHub- und
Ansible-Deployment für den Pepper-NUC". Geschrieben nach demselben
Ehrlichkeitsprinzip wie `IMPLEMENTATION_REPORT.md`: jede Aussage unten
ist tatsächlich geprüft (siehe Abschnitt 7), nichts wurde gegen echte
NUC-/Pepper-Hardware getestet, da beides in dieser Session nicht
verfügbar war.

## 1. Zusammenfassung der umgesetzten Architektur

```
Entwicklungsrechner --git push--> GitHub-Repo --Ansible/SSH--> Pepper-NUC --ROS2/NAOqi:9503--> Pepper
```

- **Ein lokales Git-Repository wurde neu angelegt** (es existierte
  zuvor keins für das Gesamtprojekt, siehe Abschnitt 3) mit einem
  bereinigten ersten Commit.
- **Ansible-Struktur** (`ansible/`) mit 6 Rollen (`base`, `ros2_jazzy`,
  `pepper_dependencies`, `pepper_deploy`, `pepper_services`,
  `pepper_healthcheck`) und 5 Playbooks (`bootstrap`, `deploy`,
  `rollback`, `healthcheck`, `site`) für ein versioniertes,
  release-basiertes Deployment mit atomarem Umschalt und Rollback.
- **systemd-Dienste + `pepperctl`** für den Alltagsbetrieb per SSH,
  ohne dass Ansible dafür erneut laufen muss.
- **GitHub Actions CI** (`.github/workflows/ci.yml`) mit zwei Jobs:
  schnelle statische Prüfungen (Python/YAML/Ansible-Lint,
  Struktur-/Secret-/Großdatei-Scan) und ein echter (Teil-)ROS2-Build +
  `pytest`.
- **Sichere Konfigurationstrennung**: nicht-geheime Werte in
  `ansible/inventory/group_vars/all.yml` (versioniert), Geheimnisse in
  `vault.yml` (verschlüsselt, nicht versioniert), Laufzeitkonfiguration
  auf dem NUC unter `/etc/ihk-pepper/`, Laufzeitdaten unter
  `/var/lib/ihk-pepper/`.

## 2. Angelegte und geänderte Dateien

**Neu angelegt** (Commit-für-Commit siehe Abschnitt 6):
- `.gitignore` (erweitert), `.flake8`, `LICENSE` (Apache 2.0, aus der
  vorgefundenen `flask_wrapper`-Historie übernommen)
- `flask_wrapper/requirements.txt`, `vision_ws/requirements.txt`,
  `pepper_autonomy_ws/requirements.txt` + `requirements-dialog.txt`
- `ansible/` (vollständig, ~30 Dateien: `ansible.cfg`,
  `requirements.yml`, `inventory/`, `playbooks/`, `roles/`)
- `.github/workflows/ci.yml`
- `docs/github-setup.md`, `nuc-bootstrap.md`, `deployment.md`,
  `rollback.md`, `operations.md`, `configuration.md`,
  `troubleshooting.md`
- Dieses Dokument (`GITHUB_DEPLOYMENT_REPORT.md`)

**Geändert**:
- `STATUS.md`, `CAPABILITIES.md`: verbliebene Klartext-Zugangsdaten
  redigiert (siehe Abschnitt 3)
- `IMPLEMENTATION_REPORT.md`: Rotation-Empfehlung korrigiert (verwies
  fälschlich auf eine Git-Historie, die zu diesem Zeitpunkt noch gar
  nicht existierte)
- `pepper_autonomy_ws/src/{ihk_pepper_bridge,ihk_pepper_presentation,
  ihk_pepper_navigation,ihk_pepper_bringup}/package.xml`: fehlende
  rosdep-Abhängigkeiten ergänzt (`python3-yaml`, `ament_index_python`,
  `launch`, `launch_ros` -- im Code genutzt, aber nicht deklariert)
- `flask_wrapper/app.py`: **echter Bug gefunden und behoben** -- 4
  Demo-Routen (`/latest_message`, `/publish_message`, `/call_service`,
  `/add_two_ints`) referenzierten `ros2_node`, das nirgends definiert
  war (garantierter `NameError` bei jedem Aufruf, da
  `initialize_ros2_node()` schon vorher auskommentiert war). Jetzt mit
  klarer 503-Antwort abgesichert. Kein Funktionsverlust -- diese Routen
  waren nie aktiv nutzbar.
- `flask_wrapper/mission/missioncontroller.py`: als toter, nirgends
  importierter Code identifiziert (per `grep` bestätigt) und über
  `.flake8`-`per-file-ignore` dokumentiert statt stillschweigend
  "repariert" oder gelöscht.

## 3. Erkannte Sicherheitsprobleme

1. **`flask_wrapper/` enthielt ein eingebettetes Git-Repository**
   (eigenes `.git`, Remote `git.fh-aachen.de/ihk-pepper/flask_wrapper.git`,
   8 Commits) **mit einer kompromittierten Historie**: Die Commits
   enthielten `QI_PW = "Pepper1224!"` (ein Pepper-SSH-Passwort aus einer
   früheren Projektphase, andere IP-Range als das aktuelle Setup) und
   den AnythingLLM-API-Token `EZ341NG-EACMYQZ-QVN5ZKG-3923Z5M` im
   Klartext, mehrfach über mehrere Commits hinweg.
   - **Vorgehen exakt nach Auftrag Abschnitt 1 (Standardweg)**:
     1. Bestehendes Repository unverändert gesichert:
        `~/pepper_git_history_backups/flask_wrapper_original_git_2026-08-22/`
     2. Eingebettetes `.git` aus dem Arbeitsbaum entfernt (NICHT die
        Dateien selbst -- die sind weiterhin vorhanden und Teil des
        neuen, bereinigten Commits).
     3. Nur der bereinigte Arbeitsstand in das neue Repository
        übernommen (dieses Projekt hatte zuvor ohnehin **kein**
        eigenes Top-Level-Git-Repository, siehe unten).
     4. Betroffene Zugangsdaten als kompromittiert markiert (siehe
        Abschnitt 4).
   - Keine Remote-Historie wurde gelöscht/überschrieben/force-gepusht --
     das alte Repository existiert unverändert in seinem Backup.
2. **Das Gesamtprojekt (Top-Level `/Pepper`) hatte VOR dieser Session
   überhaupt kein Git-Repository** (`git status` bestätigte kein
   `.git`). Der erste Commit dieser Session ist somit tatsächlich der
   erste Commit, keine bereinigte Fortsetzung einer bestehenden
   Historie.
3. **`STATUS.md`/`CAPABILITIES.md` enthielten das aktuell genutzte
   Pepper-SSH-Passwort im Klartext** (aus einer früheren Session als
   Doku-Text eingetragen, nicht als Code). Redigiert (Platzhalter
   `<PEPPER_QI_PASSWORD>`).
4. **`Code Pepper.zip`** (1.5MB Backup-Archiv, 225 Dateien inkl. alter
   `STATUS.md`-Stände) lag unversioniert im Projektordner -- jetzt per
   `.gitignore` (`*.zip`) ausgeschlossen, nicht gelöscht.
5. **Stray-Kopie eines ML-Modells** (`pepper_autonomy_ws/yolov8n-pose.pt`,
   6.8MB, identisch zu `large_files/models/yolov8n-pose.pt`) --
   entstanden durch automatischen YOLO-Download im Arbeitsverzeichnis.
   Per `.gitignore` (`*.pt`) ausgeschlossen.
6. **`flask_wrapper/app.py` hatte keinen Einstiegspunkt und `run.sh`
   sourcte ROS Humble statt Jazzy** -- bereits in der vorigen Session
   (Tablet-UI) gefunden und behoben, hier nur zur Vollständigkeit
   erwähnt, da es dieselbe Kategorie "vorgefundener Bug" betrifft.
7. **Ziel-Repository ist aktuell öffentlich** (`private: false` laut
   GitHub-API), nicht privat wie vom Auftrag gefordert. Dem Nutzer
   explizit vorgelegt (siehe Konversation) -- Antwort: **bleibt bewusst
   öffentlich**. Damit weicht dieses Deployment bewusst von Auftrag
   Abschnitt 2 ("privates Repository") ab; alle Sicherheitsmaßnahmen
   (kein Klartext-Geheimnis, schreibgeschützter Deploy-Key etc.) wurden
   trotzdem in voller Strenge umgesetzt, da öffentliche Repos jeden
   Fehler sofort und dauerhaft sichtbar machen.

## 4. Entfernte/ausgelagerte Konfigurationswerte

| Wert | Vorher | Jetzt |
|---|---|---|
| Pepper-SSH-Passwort (aktuell) | Klartext in `STATUS.md`/`CAPABILITIES.md` | Redigiert; echter Wert nur in `.env`/Ansible Vault |
| Pepper-SSH-Passwort (alt, `Pepper1224!`) | Klartext in `flask_wrapper`-Git-Historie | Als kompromittiert markiert (Rotation ohnehin empfohlen, betraf vermutlich längst gewechseltes Passwort einer früheren Projektphase) |
| AnythingLLM-API-Token | Klartext in `flask_wrapper`-Git-Historie UND zuvor schon in `config.py` | Als kompromittiert markiert, Rotation empfohlen |
| Pepper-IP (`pepper_qi_host`) | z.T. hartkodiert in Doku-Beispielen | Pflichtvariable ohne Default (`ansible.builtin.undef`) in `group_vars/all.yml`, echter Wert nur in `production.yml` (gitignored) |
| `allow_motion`/`enable_autostart` | n/a (existierten vorher nicht) | Zentrale, versionierte Sicherheits-Defaults (`false`), propagiert bis zum `SafetyGate` |

## 5. System-/ROS2-Abhängigkeiten (definiert für den NUC, nicht live installiert)

Da kein NUC in dieser Session verfügbar war, wurden alle unten
genannten Abhängigkeiten **nur in Ansible-Rollen definiert und lokal
syntaktisch/strukturell geprüft**, nicht tatsächlich auf Zielhardware
installiert. Lokal auf dem Entwicklungsrechner **tatsächlich
installiert und genutzt** für die Prüfungen in diesem Bericht:
`ansible` (bereits vorhanden), `ansible-lint`, `yamllint`, `flake8`,
`pyflakes` (per `pip3 install --user --break-system-packages`).

Für den NUC vorgesehen (siehe `ansible/roles/*/defaults/main.yml` für
die vollständigen Listen): `ros-jazzy-ros-base` + einzelne Message-
Pakete, `python3-rosdep`, `python3-colcon-common-extensions`,
PulseAudio-/ALSA-/`ffmpeg`-/`v4l-utils`-Systempakete, optional
RealSense-SDK.

## 6. Git-Branch und Commit-IDs

Branch: `main` (kein Feature-Branch, da noch kein Remote/GitHub-Zugang
zum Verifizieren des Ziel-Repos in dieser Session bestand -- siehe
Abschnitt 8).

```
4395166 Deployment-Dokumentation (docs/)
8c742c0 Ansible-Deployment-Struktur + GitHub-CI + Requirements + Bugfixes
6dce351 Initial commit: bereinigter Projektstand (IHK-Pepper)
```

HEAD: `43951660c4516b434dad842606bb5de5f7fa5bb4`
342 versionierte Dateien, Arbeitsbaum-Größe ca. 4MB (`.git`-Verzeichnis).

## 7. Ausgeführte Tests und Ergebnisse

| Prüfung | Ergebnis |
|---|---|
| `ansible-playbook --syntax-check` (alle 5 Playbooks) | ✅ alle bestanden |
| `ansible-lint .` (Profil `basic` angefordert) | ✅ 0 Findings, erreichte sogar Profil `production` |
| `yamllint` (ansible/) | ✅ sauber |
| `python3 -m py_compile` (alle `.py` in flask_wrapper/vision_ws/pepper_autonomy_ws) | ✅ sauber |
| `flake8 --select=E9,F63,F7,F82` | ✅ sauber (nach Bugfix, siehe Abschnitt 3) |
| Secret-Scan (`git grep`, Muster für Passwort/Token/Key) | ✅ keine Treffer im committeten Stand |
| Private-Key-Scan | ✅ keine Treffer |
| DB-/Modell-Artefakt-Scan (`.sqlite`, `.db`, `.pt`, `.onnx`, `.bag`) | ✅ keine im Git-Index |
| Große-Dateien-Scan (>5MB) | ✅ keine im Git-Index |
| ROS2-Paketstruktur-Check (`package.xml` + Build-Typ je Paket) | ✅ alle 11 Pakete korrekt |
| `colcon build` (4 geänderte Pakete neu gebaut) | ✅ erfolgreich |
| `python3 -m pytest ihk_pepper_tests` | ✅ 54/54 grün |
| `flask_wrapper/app.py` Live-Start + `curl` gegen die reparierten Routen | ✅ liefert jetzt 503 statt Absturz |
| **Ansible-Playbooks gegen einen echten NUC** | ⚠️ Erster Versuch durch den Nutzer deckte 2 echte Bugs auf (`ansible.cfg`-Ladepfad, SSH-Identität für Push), beide dokumentiert/gefixt (siehe Abschnitt 13) -- vollständiger End-to-End-Lauf danach noch nicht erneut durchgeführt |
| **GitHub Actions Workflow selbst** | ❌ NICHT auf GitHub ausgeführt (kein Push in dieser Session, siehe Abschnitt 8) |
| **Deploy-Key/GitHub-Checkout-Pfad** | ❌ NICHT getestet (kein SSH-Schlüssel für das Ziel-Repo vorhanden) |
| **systemd-Units/`pepperctl`** | ❌ NICHT auf echtem systemd getestet (nur als Templates/Syntax geprüft) |

## 8. Noch offene manuelle Schritte

1. **Repo-Sichtbarkeit entscheiden**: aktuell bewusst öffentlich
   belassen (Nutzerentscheidung) -- falls das sich ändert, in GitHub-
   Settings umstellen.
2. **`git push`**: In dieser Session nicht ausgeführt (kein `gh`/SSH-
   Zugang für das Ziel-Repo vorhanden). Auszuführen:
   ```bash
   git remote add origin git@github.com:MoritzSchallenberg/Student-Assistant-Pepper-FH-Aachen.git
   git push -u origin main
   ```
3. **Deploy Key erzeugen und in GitHub eintragen** (siehe
   `docs/github-setup.md`).
4. **`ansible/inventory/production.yml` aus der Vorlage erstellen**
   und mit echter NUC-IP/Pepper-IP füllen.
5. **`ansible/inventory/group_vars/vault.yml` anlegen und
   verschlüsseln** (echtes Pepper-Passwort, AnythingLLM-Token).
6. **NUC beschaffen/bereitstellen** -- existiert in dieser Session
   nicht, daher ist der komplette Ansible-Teil ungetestete, aber in
   sich konsistente Vorbereitung.
7. **Credential-Rotation** (siehe `IMPLEMENTATION_REPORT.md` und Punkt
   3 oben): Pepper-SSH-Passwort und AnythingLLM-API-Token gelten als
   kompromittiert und sollten unabhängig von diesem Deployment erneuert
   werden.
8. **`ros-jazzy-navigation2`/`behaviortree_cpp`/etc.** falls
   Navigation/Behavior-Tree auf dem NUC produktiv genutzt werden sollen
   (siehe `IMPLEMENTATION_REPORT.md`).

## 9. Erster vollständiger Deployment-Befehl

```bash
# Nach Schritten 1-5 in Abschnitt 8. WICHTIG: aus ansible/ ausfuehren,
# sonst wird ansible.cfg nicht geladen (siehe Abschnitt 12/13 unten --
# per Live-Test auf dem echten NUC gefunden).
cd ansible
ansible-playbook -i inventory/production.yml \
  playbooks/site.yml --ask-vault-pass --ask-become-pass
```

## 10. SSH-Befehle für Start, Status, Logs, ROS2

```bash
ssh <benutzer>@<nuc>
pepperctl start
pepperctl status
pepperctl logs
pepperctl logs -f
pepperctl doctor
pepperctl version
pepperctl ros topic list
pepperctl ros node list
pepperctl ros service list
pepperctl ros action list
```

## 11. Rollback-Befehl

```bash
cd ansible
ansible-playbook -i inventory/production.yml \
  playbooks/rollback.yml \
  -e rollback_revision=<commit-id> --ask-vault-pass --ask-become-pass
```

## 13. Update nach erstem Live-Versuch (2026-08-22, echter NUC des Nutzers)

Der Nutzer hat die oben genannten Befehle tatsächlich auf einem echten
NUC (`canvastino-NUC7i5BNK`) ausprobiert, was zwei reale Probleme
aufgedeckt hat -- beide sind jetzt behoben/dokumentiert:

1. **`ansible.cfg` wurde nicht geladen, wenn Befehle aus dem
   Pepper-Wurzelverzeichnis statt aus `ansible/` gestartet wurden**
   (`[ERROR]: The role 'base' was not found in:
   .../ansible/playbooks/roles:...`) -- Ansible sucht `ansible.cfg`
   relativ zum aktuellen Arbeitsverzeichnis, nicht relativ zum
   Playbook-Pfad. Root Cause: alle Befehlsbeispiele in `README.md`/
   `docs/*.md`/diesem Bericht gingen fälschlich davon aus, dass die
   Pfade `ansible/inventory/...`/`ansible/playbooks/...` von
   *außerhalb* von `ansible/` funktionieren. **Fix**: alle Beispiele
   korrigiert auf `cd ansible` + relative Pfade (`inventory/...`,
   `playbooks/...`), passend zu `ansible.cfg`s eigenen relativen
   Einstellungen (`roles_path = roles`, `inventory =
   inventory/production.yml`). Per erneutem `ansible-config dump` und
   `--list-tasks` lokal nachgewiesen, dass es danach korrekt lädt.
2. **`git push` schlug mit `Permission ... denied to
   FieldMarkerSVBFHAC` fehl** -- der Nutzer hat auf diesem Rechner
   mehrere SSH-Keys für verschiedene GitHub-Projekte, und `~/.ssh/config`
   bindet den generischen `Host github.com`-Eintrag an den Key eines
   ANDEREN Projekts (`id_ed25519_fieldmarker_github`). Für dieses
   Projekt fehlt ein eigener `Host`-Alias (nach demselben Muster wie
   die bereits vorhandenen `github-carologistics`/
   `github-learning-arabic-tool`-Einträge). **Kein Fix meinerseits
   vorgenommen** (das ist eine reine Kontoberechtigungsfrage, die der
   Nutzer selbst lösen muss -- siehe Konversation für die konkrete
   Anleitung: neuer SSH-Key auf dem MoritzSchallenberg-Account
   hinterlegen + eigener `Host`-Alias in `~/.ssh/config` +
   `git remote set-url` auf diesen Alias).
3. `git remote add origin ...` meldete beim zweiten Versuch "existiert
   bereits" -- unkritisch, der Remote zeigt bereits korrekt auf
   `git@github.com:MoritzSchallenberg/Student-Assistant-Pepper-FH-Aachen.git`,
   kein weiteres Handeln nötig.
4. `ansible-vault encrypt` einmal mit "Passwords do not match"
   fehlgeschlagen -- reiner Tippfehler des Nutzers beim zweimaligen
   Eintippen, kein struktureller Fehler.
5. Merge von GitHubs Platzhalter-README mit dem bereinigten Stand: per
   `git fetch && git merge origin/main --allow-unrelated-histories`
   ohne Force-Push durchgeführt (Auftrag: kein Force-Push, keine
   Historie ueberschreiben) -- Konflikt in `README.md` mit `--ours`
   zugunsten des echten Projekt-READMEs aufgelöst. Push danach
   erfolgreich, per GitHub-API bestätigt (`commits/main` zeigt exakt
   den lokalen Merge-Commit).
6. Nach Adressierung des Deploy Keys/SSH-Alias tauchten beim
   eigentlichen Verbindungsaufbau zum Ziel-NUC nacheinander drei
   weitere reale, aufeinanderfolgende Probleme auf (alle jetzt behoben):
   - `ansible_host` in der ausgefüllten `production.yml` war
     `192.168.0.255` -- die **Broadcast-Adresse** des `/24`-Netzes, kein
     Host. Per `ip a`-Ausgabe des Nutzers auf dem Ziel-NUC (Interface
     `wlp58s0`) auf die echte `inet`-Adresse `192.168.0.186` korrigiert;
     `ansible_user` ebenfalls falsch (`canvastino` statt `pw-hallo`,
     dem tatsächlichen Login auf dem Ziel-NUC) -- korrigiert.
   - `ssh ... port 22: Connection refused` -- `openssh-server` war auf
     dem frischen Ziel-NUC (Ubuntu Desktop, kein Server-Image) nicht
     installiert. Vom Nutzer selbst nachinstalliert/gestartet
     (`apt install openssh-server`, `systemctl enable --now ssh`) --
     das kann und soll Ansible nicht selbst lösen, da es fuer die
     ERSTE Verbindung ja SSH selbst braucht (Henne-Ei-Problem).
   - `Host key verification failed` + `ssh_askpass ... No such file`
     -- der Kontrollrechner kannte den Host-Key des Ziel-NUC noch
     nicht (`host_key_checking = True` in `ansible.cfg`, bewusst kein
     `StrictHostKeyChecking=no`), und hatte zudem noch keinen
     SSH-Key/keine Zugangsdaten fuer den Ziel-NUC hinterlegt (kein
     `~/.ssh/id_ed25519` o.ä. vorhanden). Gelöst durch einen
     dedizierten neuen Key (`~/.ssh/id_ed25519_pepper_nuc`) +
     `ssh-copy-id` (akzeptiert dabei interaktiv den Host-Key) +
     Eintrag `ansible_ssh_private_key_file` in `production.yml`.
7. **Echter Bug in `ansible.cfg` gefunden**: `stdout_callback = yaml`
   (rein kosmetisch, fuer schoenere Konsolenausgabe gedacht) liess
   `ansible-playbook` mit `TypeError: function() argument 'code' must
   be code, not str` abstuerzen -- eine Versionsinkompatibilitaet
   zwischen der apt-installierten `community.general`-Collection und
   dem per pip installierten, deutlich neueren `ansible-core 2.21.3`
   auf dem Rechner des Nutzers. **Fix**: `stdout_callback` aus
   `ansible.cfg` entfernt (faellt auf den eingebauten
   `ansible.builtin.default`-Callback zurueck, der keine
   Zusatz-Collection braucht) -- lokal verifiziert, dass der
   Callback-Loader danach ohne Absturz laedt.

**Damit korrigiert sich Abschnitt 12 unten**: Es gab inzwischen mehrere
echte Testläufe gegen den echten Ziel-NUC, die nacheinander 7 reale
Probleme aufdeckten (alle oben dokumentiert und behoben). Der
vollständige `bootstrap`/`site.yml`-Lauf ist zum Zeitpunkt dieses
Updates noch nicht erfolgreich bis zum Ende durchgelaufen -- der
letzte bekannte Blocker war der `stdout_callback`-Absturz direkt nach
dem Start (Punkt 7), der jetzt behoben ist, aber noch nicht erneut
gegen den echten NUC verifiziert wurde.

## 12. Bekannte Einschränkungen

- **Der komplette Ansible-Lauf (Bootstrap+Deploy) ist noch nicht
  vollständig gegen den echten NUC durchgelaufen** -- ein erster
  Versuch deckte die zwei in Abschnitt 13 beschriebenen Probleme auf,
  die jetzt behoben/dokumentiert sind, aber noch nicht erneut
  vollständig End-to-End nachgetestet wurden.
- **GitHub Actions CI wurde nie auf GitHub ausgeführt** -- nur lokal
  Schritt für Schritt nachgebildet (siehe Abschnitt 7).
- **`pepperctl start/stop/restart` brauchen normales `sudo`** (kein
  passwortloser Sonderfall eingerichtet) -- für vollautomatisierte
  Skripte müsste das noch ergänzt werden (bewusst nicht getan, um keine
  ungetestete zusätzliche Rechteausweitung einzuführen).
- **`ihk_pepper_dialog` und `ihk_pepper_behavior_tree` sind vom
  Standard-CI-Build ausgenommen** (siehe `.github/workflows/ci.yml`) --
  ersteres aus Zeit-/Ressourcengründen (schwerer Torch-Download),
  zweiteres weil `behaviortree_cpp` nicht ohne Weiteres in einer
  Standard-Ubuntu-24.04-CI-Umgebung verfügbar ist, ohne den
  ROS2-Jazzy-Kanal selbst hinzuzufügen (was der Workflow zwar tut, aber
  nicht für dieses eine Paket separat konfiguriert wurde).
- **Repository ist öffentlich** -- bewusste Nutzerentscheidung, weicht
  vom Auftragstext ab (siehe Abschnitt 3, Punkt 7).
- **Ansible-Hardening (`ProtectSystem=strict` in den systemd-Units)
  ist ungetestet** -- könnte bei tatsächlicher Nutzung noch
  Pfadanpassungen brauchen (siehe Kommentare in den
  `.service.j2`-Templates).
