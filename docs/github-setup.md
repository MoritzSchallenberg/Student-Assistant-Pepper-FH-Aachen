# GitHub-Repository einrichten

Dieses Dokument beschreibt Schritt 1-3 des Gesamtablaufs (siehe
`docs/deployment.md` für den kompletten Ablauf).

## 1. Repository anlegen

Das Zielrepository für dieses Projekt existiert bereits:
`https://github.com/<DEIN-GITHUB-NUTZER>/<DEIN-REPO-NAME>`.

**Wichtiger Hinweis (siehe `GITHUB_DEPLOYMENT_REPORT.md`)**: Der
Entwicklungsauftrag verlangt ausdrücklich ein *privates* Repository.
Falls dein Repository aktuell öffentlich ist und das nicht beabsichtigt
war, stelle es in GitHub unter *Settings → General → Danger Zone →
Change repository visibility* auf privat, **bevor** du produktive
Zugangsdaten (Deploy Key, Ansible Vault) damit verbindest.

Falls noch kein Repository existiert:
1. GitHub → *New repository*
2. Sichtbarkeit: **Private**
3. Kein automatisches README/`.gitignore`/License (das Projekt bringt
   bereits alles mit)

## 2. Bereinigten Code hochladen

Der lokale Arbeitsstand ist bereits als bereinigter erster Commit
vorbereitet (siehe `GITHUB_DEPLOYMENT_REPORT.md`, Abschnitt
"Sicherheitsbereinigung"). Zum Hochladen:

```bash
cd /pfad/zu/Pepper
git remote add origin git@github.com:<DEIN-GITHUB-NUTZER>/<DEIN-REPO-NAME>.git
git branch -M main
git push -u origin main
```

Falls du lieber mit HTTPS + einem Personal Access Token arbeitest:

```bash
git remote add origin https://github.com/<DEIN-GITHUB-NUTZER>/<DEIN-REPO-NAME>.git
git push -u origin main
# Bei der Passwortabfrage: Personal Access Token statt Account-Passwort verwenden
```

**Nach dem Push prüfen**: GitHub selbst durchsucht Pushes automatisch
nach bekannten Geheimnis-Mustern (Secret Scanning) und würde den Push
bei einem Treffer blockieren/warnen -- das ist eine zusätzliche
Sicherheitsebene, kein Ersatz für die lokale Prüfung.

## 3. GitHub Deploy Key für den NUC einrichten

Der NUC bekommt einen **eigenen, nur lesenden** SSH-Schlüssel, der
ausschließlich diesem einen Repository zugeordnet ist (Auftrag
Abschnitt 6).

### Einmalige Einrichtung

```bash
# Auf dem NUC (oder lokal erzeugen und anschließend per Ansible/scp
# sicher auf den NUC übertragen -- NIEMALS den privaten Schlüssel ins
# Repo committen):
ssh-keygen -t ed25519 -C "ihk-pepper-nuc-deploy" \
  -f ~/.ssh/id_ed25519_github_deploy -N ""

chmod 600 ~/.ssh/id_ed25519_github_deploy
```

Den **öffentlichen** Schlüssel (`id_ed25519_github_deploy.pub`) auf
GitHub eintragen:

1. Repository → *Settings → Deploy keys → Add deploy key*
2. Titel: z.B. `pepper-nuc`
3. Inhalt: `cat ~/.ssh/id_ed25519_github_deploy.pub`
4. **"Allow write access" NICHT ankreuzen** (Auftrag: kein
   Schreibzugriff vom NUC auf GitHub)

### GitHub-Host-Key sicher hinterlegen

`ansible/roles/pepper_deploy/tasks/checkout.yml` erledigt das
automatisch beim ersten Deployment (`ssh-keyscan -H github.com`, kein
`StrictHostKeyChecking=no`). Manuell, falls gewünscht:

```bash
ssh-keyscan -H github.com >> ~/.ssh/known_hosts
```

### Konfiguration

In `ansible/inventory/production.yml` (bzw. `group_vars/all/vars.yml`):

```yaml
pepper_repo_url: "git@github.com:<DEIN-GITHUB-NUTZER>/<DEIN-REPO-NAME>.git"
pepper_source_method: git_deploy_key
pepper_deploy_key_path: "/home/pepper/.ssh/id_ed25519_github_deploy"
```

### Fehlende Schlüssel

Wenn `ansible-playbook ... deploy.yml` läuft und der Deploy-Key unter
`pepper_deploy_key_path` fehlt, bricht das Deployment mit einer klaren
Fehlermeldung ab (siehe `ansible/roles/pepper_deploy/tasks/checkout.yml`) --
kein stiller Fallback auf unsichere Optionen.

### Alternative: Quellcode ohne GitHub-Zugriff vom NUC übertragen

Falls kein Deploy Key gewünscht ist, überträgt Ansible den Code direkt
vom Entwicklungsrechner:

```yaml
pepper_source_method: rsync_from_control_node
pepper_control_node_src_path: "/pfad/zu/Pepper"   # auf dem Rechner, der ansible-playbook ausfuehrt
```

Der NUC braucht dann **gar keinen** GitHub-Zugriff.
