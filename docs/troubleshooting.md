# Troubleshooting

## Deployment

**"Kein Deploy-Key unter ... gefunden"**
→ Einmalige Einrichtung nachholen, siehe `docs/github-setup.md`.

**"Dieser NUC laeuft nicht auf Ubuntu 24.04+"**
→ `ansible-playbook ... deploy.yml` bricht bewusst ab (Auftrag Abschnitt
7, Schritt 1). Falsches Image installiert, oder Inventory zeigt auf den
falschen Host.

**"Nur XMB frei, YMB benoetigt"**
→ Alte Releases manuell aufräumen (`ls /opt/ihk-pepper/releases/`,
älteste per Hand löschen) oder `deploy_keep_releases` reduzieren.

**`rosdep install` schlägt fehl**
→ `rosdep update` erneut laufen lassen (`ansible-playbook ...
bootstrap.yml` deckt das ab); prüfen ob ein neues `package.xml`
einen rosdep-Key referenziert, der (noch) nicht in der rosdep-Datenbank
existiert -- ggf. `--skip-keys` in `pepper_deploy/tasks/build.yml`
ergänzen (analog zu `ihk_pepper_navigation`s Nav2-Paketen, siehe
`IMPLEMENTATION_REPORT.md`).

**`colcon build` scheitert bei `ihk_pepper_dialog`**
→ Bekanntes Muster (siehe `IMPLEMENTATION_REPORT.md`, Abschnitt
"Erroren und Fixes" #7/#8): braucht `venv_dialog` UND `python3 -m
colcon`, nicht die bare `colcon`-Binary (deren Shebang zeigt auf
System-Python, ignoriert das aktive venv). Der `pepper_deploy`-Build-
Task macht das bereits richtig -- bei manuellem Nachbauen darauf achten.

**Healthcheck schlägt fehl, obwohl der Code korrekt ist**
→ Meistens: `naoqi_port_reachable: false`, weil Pepper aus/nicht
verbunden ist. Das ALLEIN führt nicht zum Abbruch (siehe
`pepper_healthcheck`-Rolle) -- prüfen, welcher der ANDEREN Werte
(`workspace_built`, `free_space_mb`) tatsächlich fehlgeschlagen ist.

## Betrieb

**`pepperctl start` fragt nach einem Passwort und hängt in einer
nicht-interaktiven Session**
→ `pepperctl start/stop/restart` nutzen normales `sudo` (siehe
`docs/operations.md`) -- in einer interaktiven SSH-Sitzung normal, in
einem Skript/CI nicht automatisierbar ohne zusätzliche Einrichtung
(bewusst so, siehe `GITHUB_DEPLOYMENT_REPORT.md`).

**Dienst startet, beendet sich aber sofort wieder (`Restart=on-failure`
in Schleife)**
→ `pepperctl logs` prüfen. Häufigste Ursache: `current`-Symlink zeigt
auf keinen gebauten Release (`install/setup.bash` fehlt) -- erneut
deployen.

**"FEHLER: .../current existiert nicht -- kein Release deployed."**
→ Noch nie erfolgreich deployt. `docs/deployment.md` durchgehen.

## Audio (bestehender PulseAudio-Workaround, siehe `STATUS.md`)

**Kein Audio trotz erfolgreichem Deployment**
→ Dieser Workaround wurde durch das Ansible-Deployment NICHT verändert
(Auftrag Abschnitt 4: "ersetze PulseAudio/PipeWire nicht"). Prüfen:
- Ist der `pepper`-Laufzeitbenutzer in der Gruppe `audio`/`pulse-access`?
  (`groups pepper`)
- Läuft PulseAudio als der richtige Benutzer? (`pactl info`)
- Gleiche Diagnosekette wie in `STATUS.md` beschrieben (parecord-Test,
  SFTP-Fetch).

## Nav2/SLAM/RealSense

**`ihk_pepper_navigation` baut nicht (behaviortree_cpp/nav2_bringup
fehlt)**
→ Erwartet auf einem frischen NUC ohne die optionalen Pakete. Siehe
`IMPLEMENTATION_REPORT.md`/`ihk_pepper_behavior_tree/README.md` für
die exakten `sudo apt install ros-jazzy-navigation2 ...`-Befehle.
`pepper_deploy` baut standardmäßig NUR die getesteten Pakete
(`--packages-skip ihk_pepper_dialog`) -- `ihk_pepper_navigation` selbst
baut auch ohne diese Pakete (nur `<exec_depend>`, siehe dessen
`package.xml`), nutzt sie aber erst zur Laufzeit.

## GitHub/CI

**CI schlägt beim Secret-Scan fehl**
→ `git grep` hat ein Muster gefunden, das wie ein Zugangsdatensatz
aussieht. Meist ein False Positive (z.B. ein Beispielwert in der
Dokumentation) -- in diesem Fall die CI-Ausschlussliste in
`.github/workflows/ci.yml` erweitern (`':!pfad/zur/datei'`), NICHT den
Scan selbst deaktivieren.

**CI schlägt beim "grosse Dateien"-Check fehl**
→ Eine Datei >5MB wurde versehentlich committet. `git rm --cached
<datei>`, Muster zur `.gitignore` hinzufügen, neu committen.

## Allgemein

**"Woher weiß ich, welcher Commit gerade läuft?"**
→ `pepperctl version` oder `cat /var/log/ihk-pepper/deployments.log`.

**"Ich will alles zurücksetzen und neu anfangen"**
→ NUC neu aufsetzen (Ubuntu neu installieren) ist der sicherste Weg;
`ansible-playbook ... site.yml` baut alles von Grund auf wieder auf.
Laufzeitdaten unter `/var/lib/ihk-pepper/` vorher sichern, falls
gewünscht.
