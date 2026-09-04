# Entwicklungsauftrag 3: Drei-LLM-Dialogsystem, Vektorgedächtnis, kinematischer Gestenbaukasten

Laufender Bericht. Wird nach jedem Arbeitspaket ergänzt (Order-3-Vorgabe:
keine geschönten Angaben, `dry_run_validated` ist nicht `live_validated`).

## AP1: Baseline und Projektbereinigung

Verbindlicher Ausgangsstand geprüft und bestätigt:

```
$ git rev-parse HEAD   (vor dem Branchwechsel)
4d358c8d4ae4a225d9566454763dd554ec31bba9
$ git status --short
(leer -- sauberer Working Tree)
```

Branch erstellt:
```bash
git switch -c order-03-llm-memory-kinematic-gestures
```
(von `order-02-realsense-nav2-safe-approach`, Commit `4d358c8` -- exakt
der im Auftrag genannte Ausgangsstand.)

### Baseline-Build + Test (vor jeder Änderung dieses Auftrags)

```
$ colcon build --symlink-install --packages-skip ihk_pepper_dialog
Summary: 12 packages finished [12.9s]  (nur Warnungen, keine Fehler)

$ python3 -m pytest ros2/autonomy_ws/src/ihk_pepper_tests/test/ -q
218 passed in 0.84s

$ colcon test --packages-select ihk_pepper_behavior_tree
Summary: 17 tests, 0 errors, 0 failures, 3 skipped
```

Exakt der im Auftrag genannte nachgewiesene Stand (218/218, 17/0/0/3) --
bestätigt.

### .gitignore-Prüfung (Auftrag: build/, install/, log/, venv/, .venv/,
### __pycache__/, .pytest_cache/, *.db, *.sqlite, *.bag, .env, vault.yml, production.yml)

`git ls-files | grep -E "..."` gegen alle genannten Muster durchgeführt:
**keine einzige dieser Dateien ist versioniert.** `.gitignore` deckt
bereits alle genannten Muster ab (teils sogar präziser/pfadspezifischer
als im Auftrag formuliert, z.B. `ansible/inventory/production.yml` statt
eines pauschalen `production.yml` -- bewusst so belassen, ein globales
Muster auf einen bloßen Dateinamen könnte anderswo im Repo unbeabsichtigt
etwas Falsches treffen). **Keine Änderung an `.gitignore` nötig** -- das
war bereits am Ende von Auftrag 1/2 korrekt eingerichtet (siehe
`docs/GITHUB_DEPLOYMENT_REPORT.md`/Repo-Reorg-Historie). Keine
Nutzerdaten gelöscht, da nichts zu löschen war.

### Source-only-Exportskript

Neu: `scripts/export_source_only.sh` -- nutzt `git archive` (liest per
Definition ausschließlich den Git-Index, nie das Arbeitsverzeichnis;
ungetrackte Dateien -- also automatisch auch alles oben Geprüfte --
können darin strukturell nie landen, unabhängig vom Zustand des
Arbeitsverzeichnisses beim Aufruf).

**Echt getestet**: `./scripts/export_source_only.sh HEAD /tmp/test_export.zip`
ausgeführt -- erzeugt ein 1,8 MB-ZIP. Inhalt mit `unzip -l | grep`
gegen `build/`, `install/`, `.db`, `.sqlite`, `.env`, `venv/` geprüft:
**keine Treffer, ZIP ist sauber.**

### Reihenfolge der Umsetzung in diesem Auftrag

Gegeben die Größe dieses Auftrags (14 Arbeitspakete über LLM-Pipeline,
Gedächtnis, Kinematik, Executor, Behavior-Tree-Integration, CLI-Tooling)
folgt die Umsetzung einer geplanten Reihenfolge -- siehe Planungsdatei
dieser Sitzung für die vollständige Begründung. Kurzfassung: zuerst die
unabhängigen, ROS-freien Bausteine (LLM-Provider-Schnittstelle,
LLM-Verträge/Validierung, Identity Registry, Vector Memory, Kinematik-
Compiler/Transport), dann die ROS-Integration (Executor, RunDialogue-
Action, Behavior Tree), zuletzt Gesten-Erweiterung/CLI/Tests/Doku.
