#!/usr/bin/env bash
# Source-only-Export (Entwicklungsauftrag 3, AP1).
#
# Erstellt ein ZIP ausschliesslich aus git-getrackten Dateien (git archive
# liest per Definition nur den Git-Index, nie das Arbeitsverzeichnis --
# build/, install/, log/, venv*/, __pycache__/, .pytest_cache/, *.db,
# *.sqlite, *.bag, .env, Vault-/Production-Inventories etc. sind laut
# .gitignore ohnehin nie getrackt, siehe docs/DEVELOPMENT_ORDER_03_REPORT.md
# AP1 fuer die Verifikation). Kein Risiko, versehentlich Laufzeit-/
# Secret-/Build-Daten mit einzupacken, weil git archive niemals
# ungetrackte Dateien einliest -- unabhaengig vom aktuellen Zustand des
# Arbeitsverzeichnisses (auch nicht committete lokale .env-Aenderungen
# etc. landen nie im Export).
#
# Nutzung:
#   ./scripts/export_source_only.sh [ref] [ziel.zip]
#
# ref     : Git-Referenz (Branch/Tag/Commit), Default: HEAD
# ziel.zip: Ausgabepfad, Default: ../pepper-source-<ref>-<datum>.zip
#           (bewusst AUSSERHALB des Repos, damit ein zweiter Lauf das ZIP
#           nicht selbst wieder einpackt)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

ref="${1:-HEAD}"
default_name="../pepper-source-$(git rev-parse --short "$ref" 2>/dev/null || echo "$ref")-$(date +%Y%m%d_%H%M%S).zip"
dest="${2:-$default_name}"

if ! git rev-parse --verify --quiet "$ref" > /dev/null; then
  echo "FEHLER: '$ref' ist keine gueltige Git-Referenz." >&2
  exit 1
fi

echo "Exportiere getrackte Dateien von '$ref' nach '$dest' ..."
git archive --format=zip --output="$dest" "$ref"

echo "Fertig: $dest ($(du -h "$dest" | cut -f1))"
echo "Enthaelt ausschliesslich git-getrackte Dateien -- keine build/, install/,"
echo "log/, venv*/, __pycache__/, .pytest_cache/, *.db/*.sqlite, *.bag, .env,"
echo "Vault-/Production-Inventories (siehe .gitignore)."
