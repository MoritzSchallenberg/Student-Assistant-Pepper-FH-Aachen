# Deployment

Versioniertes, rücksetzbares Deployment (Auftrag Abschnitt 7). Ein
Deployment überschreibt nie einfach den aktiven Ordner -- es checkt in
ein neues Release-Verzeichnis aus, baut/testet dort, und schaltet erst
bei Erfolg um:

```text
/opt/ihk-pepper/
├── current -> releases/<commit-id>
├── releases/
│   ├── <commit-id-1>/
│   ├── <commit-id-2>/
│   └── <commit-id-3>/
└── shared/
    └── venv_dialog/   (bleibt ueber Releases hinweg erhalten, siehe unten)
```

## Voraussetzungen

- NUC ist gebootstrappt (`docs/nuc-bootstrap.md`)
- GitHub Deploy Key eingerichtet ODER `pepper_source_method:
  rsync_from_control_node` konfiguriert (`docs/github-setup.md`)

## Deployen

**Wichtig**: aus dem `ansible/`-Verzeichnis ausführen (siehe
`docs/troubleshooting.md`, sonst wird `ansible.cfg` nicht geladen).

```bash
cd ansible
ansible-playbook -i inventory/production.yml \
  playbooks/deploy.yml \
  -e deploy_revision=main \
  --ask-vault-pass --ask-become-pass
```

Ein bestimmter Commit oder Tag:

```bash
cd ansible
ansible-playbook -i inventory/production.yml \
  playbooks/deploy.yml \
  -e deploy_revision=a1b2c3d4 \
  --ask-vault-pass --ask-become-pass
```

## Was dabei passiert (14 Schritte, siehe `ansible/roles/pepper_deploy/tasks/`)

1. Betriebssystem prüfen (muss Ubuntu ≥24.04 sein)
2. Freien Speicherplatz prüfen (Standard: ≥2GB)
3. `deploy_revision` auflösen (Branch/Tag/Commit → konkrete Commit-ID)
4. Code in `releases/<commit-id>/` auschecken (Deploy-Key oder rsync)
5. Python-Requirements installieren/aktualisieren (`requirements.txt`
   je Komponente, siehe `docs/configuration.md`)
6. `rosdep install` für den Workspace
7. `colcon build --symlink-install` (ROS2-Workspace)
8. `pytest`-Suite ausführen (`ihk_pepper_tests`)
9. Berechtigungen prüfen/setzen
10. **Passiver Healthcheck** gegen den neuen Release (siehe
    `docs/operations.md` -- löst keine Bewegung aus)
11. **Erst jetzt**: `current`-Symlink atomar umschalten
12. Nur bereits laufende Dienste (`ihk-pepper-ros2`/`-web.service`)
    kontrolliert neu starten
13. Deployte Version in `/var/log/ihk-pepper/deployments.log`
    protokollieren
14. Alte Releases aufräumen (Standard: die letzten 5 behalten)

**Bei einem Fehler in Schritt 1-10 bleibt die zuvor aktive Version
unverändert aktiv** -- `current` wird erst nach erfolgreichem
Healthcheck umgeschaltet.

## Laufzeitdaten bleiben erhalten

Datenbanken (FAQ-Cache), Medien, Karten und Modelle liegen unter
`/var/lib/ihk-pepper/` -- **außerhalb** des Release-Verzeichnisses.
Ein Deployment/Rollback berührt diese Pfade nie.

## Nach dem Deployment

```bash
ssh <benutzer>@<nuc>
pepperctl status
pepperctl logs
```

Siehe `docs/operations.md` für die vollständige `pepperctl`-Referenz
und `docs/rollback.md` falls etwas schiefgeht.
