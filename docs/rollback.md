# Rollback

Aktiviert eine bereits vorhandene, frühere Release-Version erneut --
ohne erneuten Checkout/Build, nur Healthcheck + atomarer
Symlink-Umschalt + kontrollierter Dienst-Neustart.

## Verfügbare Releases anzeigen

```bash
ssh <benutzer>@<nuc>
ls -la /opt/ihk-pepper/releases/
pepperctl version   # zeigt den aktuellen Release + die letzten Deployments
cat /var/log/ihk-pepper/deployments.log
```

## Zurückrollen

```bash
cd ansible
ansible-playbook -i inventory/production.yml \
  playbooks/rollback.yml \
  -e rollback_revision=<commit-id> \
  --ask-vault-pass
```

`<commit-id>` muss ein Verzeichnisname unter
`/opt/ihk-pepper/releases/` sein (also ein zuvor erfolgreich
deployter Commit).

## Was dabei passiert

1. Prüfen, ob `rollback_revision` angegeben wurde
2. Prüfen, ob dieser Release lokal noch existiert (wurde er evtl.
   schon durch die Aufräum-Logik entfernt -- Standard: die letzten 5
   Releases bleiben erhalten)
3. Passiver Healthcheck gegen diesen Release
4. `current`-Symlink atomar umschalten
5. Nur bereits laufende Dienste neu starten
6. Rollback in `deployments.log` protokollieren

## Falls der gewünschte Release nicht mehr vorhanden ist

```text
Release <commit-id> existiert nicht (mehr) unter .../releases/<commit-id>
```

In diesem Fall: erneut mit `deploy.yml` auf den gewünschten Commit
deployen (siehe `docs/deployment.md`) statt Rollback.

## Datenbanken/Laufzeitdaten

Bleiben unverändert (liegen unter `/var/lib/ihk-pepper/`, nicht im
Release-Verzeichnis) -- ein Rollback kann alte Code-Versionen mit den
aktuellen Laufzeitdaten kombinieren. Falls ein Rollback wegen einer
inkompatiblen Datenbank-Migration nötig wird, vorher ein Backup unter
`/var/lib/ihk-pepper/` ziehen (siehe `docs/operations.md`).
