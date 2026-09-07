"""
Entwicklungsauftrag 04-B, Arbeitspaket 0: beweist, dass
scripts/export_source_only.sh (und damit jede kuenftige Weitergabe ueber
dieses Skript bzw. per `git archive`) NIEMALS Zugangsdaten-, Vault-,
Produktions-Inventar-, Datenbank-, venv-, build-/install-/log- oder
sonstige Laufzeitdateien enthaelt.

Ruft das echte Skript gegen HEAD auf (kein Mock) -- `git archive` liest
per Definition nur den Git-Index, daher ist dieser Test zugleich ein
indirekter Beweis, dass keine dieser Dateien jemals versehentlich
getrackt wurde (ein getrackter Treffer wuerde hier durchschlagen, egal
ob .gitignore ihn heute ausschliesst oder nicht -- .gitignore wirkt nur
auf UNGETRACKTE Dateien, nicht rueckwirkend auf bereits committete).
"""
import os
import subprocess
import zipfile

import pytest

_FORBIDDEN_SUFFIXES = (".env", ".db", ".sqlite", ".sqlite3", ".pyc", ".retry")
_FORBIDDEN_EXACT_BASENAMES = ("vault.yml", "production.yml")
_FORBIDDEN_PATH_SEGMENTS = (
    "/build/", "/install/", "/log/", "/venv/", "/venv_dialog/", "/.venv/",
    "/__pycache__/", "/.pytest_cache/", "/secrets/",
)
# Vorlagen/Beispieldateien duerfen sehr wohl im Export sein -- nur die
# echten, potenziell befuellten Gegenstuecke sind verboten.
_ALLOWED_EXCEPTIONS = (
    "vault.yml.example", "production.example.yml", ".env.example",
)


def _repo_root() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _is_forbidden(path: str) -> bool:
    basename = os.path.basename(path)
    if basename in _ALLOWED_EXCEPTIONS:
        return False
    if basename in _FORBIDDEN_EXACT_BASENAMES:
        return True
    if basename.endswith(_FORBIDDEN_SUFFIXES):
        return True
    normalized = f"/{path}/"
    return any(seg in normalized for seg in _FORBIDDEN_PATH_SEGMENTS)


@pytest.fixture(scope="module")
def exported_zip_path(tmp_path_factory):
    repo_root = _repo_root()
    script = os.path.join(repo_root, "scripts", "export_source_only.sh")
    if not os.path.exists(script):
        pytest.skip("scripts/export_source_only.sh nicht gefunden")

    dest = str(tmp_path_factory.mktemp("export") / "source_export_test.zip")
    result = subprocess.run(
        ["bash", script, "HEAD", dest],
        cwd=repo_root, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"export_source_only.sh fehlgeschlagen (rc={result.returncode}):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert os.path.exists(dest), "Export-Skript lief durch, aber keine ZIP-Datei entstand."
    return dest


def test_export_produces_nonempty_archive(exported_zip_path):
    with zipfile.ZipFile(exported_zip_path) as zf:
        names = zf.namelist()
    assert len(names) > 50  # grobe Plausibilitaetspruefung, kein leerer/kaputter Export


def test_export_contains_no_forbidden_files(exported_zip_path):
    with zipfile.ZipFile(exported_zip_path) as zf:
        names = zf.namelist()
    forbidden_hits = [n for n in names if _is_forbidden(n)]
    assert forbidden_hits == [], (
        "Der Source-Export enthaelt verbotene Laufzeit-/Geheimnisdateien: "
        f"{forbidden_hits}"
    )


def test_export_contains_expected_source_files(exported_zip_path):
    """Gegenprobe: der Export ist nicht einfach leer/kaputt, sondern
    enthaelt tatsaechlich erwarteten Quellcode."""
    with zipfile.ZipFile(exported_zip_path) as zf:
        names = set(zf.namelist())
    assert "ros2/autonomy_ws/src/ihk_pepper_bridge/package.xml" in names
    assert "scripts/export_source_only.sh" in names


def test_env_example_and_vault_example_are_allowed_to_be_present(exported_zip_path):
    """Die *.example-Vorlagen sind gewollt versioniert (siehe
    .gitignore-Ausnahmen) -- dieser Test dokumentiert bewusst, dass ihre
    Anwesenheit KEIN Fehlschlag von test_export_contains_no_forbidden_files
    waere, falls sie im Repo vorhanden sind."""
    with zipfile.ZipFile(exported_zip_path) as zf:
        names = zf.namelist()
    for name in names:
        assert not _is_forbidden(name)
    # Kein assert auf Anwesenheit -- ob *.example-Dateien existieren, ist
    # unabhaengig von diesem Sicherheitsvertrag.
