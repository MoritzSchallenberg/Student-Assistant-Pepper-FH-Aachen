"""
Tests fuer GestureIndexStore (Ergaenzungsauftrag 04-A): deterministischer
Neuaufbau aus einem echten (kleinen, temporaeren) YAML-Gestenkatalog ueber
die echte ihk_pepper_bridge.gesture_catalog.GestureCatalog-Klasse -- keine
zweite YAML-Parsing-Implementierung im Test.
"""
import shutil

import pytest
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_gesture_memory.embedding_backend import DifflibFallbackBackend
from ihk_pepper_gesture_memory.gesture_index_db import GestureIndexStore
from ihk_pepper_gesture_memory.gesture_search import GestureSearchRequest

_REAL_CATALOG_DIR = None
try:
    import os
    _REAL_CATALOG_DIR = os.path.join(
        get_package_share_directory("ihk_pepper_bridge"), "config", "gestures"
    )
except Exception:
    pass


def _copy_real_gestures(tmp_path, names):
    """Kopiert ausgewaehlte, bereits validierte reale Gestendateien in
    ein temporaeres Katalogverzeichnis -- vermeidet, in Tests neue
    Gelenkwinkel zu erfinden, die vielleicht gar nicht sicherheits-
    valide waeren."""
    if _REAL_CATALOG_DIR is None:
        pytest.skip("ihk_pepper_bridge share-Verzeichnis nicht gefunden (nicht sourced?)")
    catalog_dir = tmp_path / "gestures"
    catalog_dir.mkdir()
    for name in names:
        src = os.path.join(_REAL_CATALOG_DIR, f"{name}.yaml")
        if not os.path.exists(src):
            pytest.skip(f"Referenzgeste '{name}.yaml' nicht im echten Katalog gefunden")
        shutil.copy(src, catalog_dir / f"{name}.yaml")
    return str(catalog_dir)


def _store(tmp_path, embedding_backend=None):
    return GestureIndexStore(
        str(tmp_path / "gesture_index.db"),
        embedding_backend=embedding_backend or DifflibFallbackBackend(),
    )


def test_reindex_populates_index_from_real_catalog(tmp_path):
    catalog_dir = _copy_real_gestures(tmp_path, ["point_to_self", "small_bow"])
    catalog = GestureCatalog(catalog_dir)
    store = _store(tmp_path)

    result = store.reindex(catalog, force=True)

    assert result["indexed_count"] == 2
    assert result["unchanged"] is False
    assert store.entry_count() == 2


def test_reindex_is_deterministic_and_idempotent(tmp_path):
    catalog_dir = _copy_real_gestures(tmp_path, ["point_to_self", "small_bow"])
    catalog = GestureCatalog(catalog_dir)
    store = _store(tmp_path)

    first = store.reindex(catalog, force=True)
    second = store.reindex(catalog, force=True)

    assert first["indexed_count"] == second["indexed_count"] == 2
    assert store.entry_count() == 2  # kein Duplizieren bei wiederholtem Reindex


def test_reindex_without_force_skips_unchanged_catalog(tmp_path):
    catalog_dir = _copy_real_gestures(tmp_path, ["point_to_self"])
    catalog = GestureCatalog(catalog_dir)
    store = _store(tmp_path)

    store.reindex(catalog, force=True)
    second = store.reindex(catalog, force=False)

    assert second["unchanged"] is True
    assert second["indexed_count"] == 1


def test_reindex_without_force_detects_new_file(tmp_path):
    catalog_dir = _copy_real_gestures(tmp_path, ["point_to_self"])
    catalog = GestureCatalog(catalog_dir)
    store = _store(tmp_path)

    store.reindex(catalog, force=True)
    assert store.entry_count() == 1

    # Katalog waehrenddessen um eine zweite echte Geste erweitert.
    import os
    import shutil as _shutil
    _shutil.copy(
        os.path.join(_REAL_CATALOG_DIR, "small_bow.yaml"),
        os.path.join(catalog_dir, "small_bow.yaml"),
    )
    catalog.reload()
    result = store.reindex(catalog, force=False)

    assert result["unchanged"] is False
    assert result["indexed_count"] == 2
    assert store.entry_count() == 2


def test_search_returns_indexed_gesture(tmp_path):
    catalog_dir = _copy_real_gestures(tmp_path, ["point_to_self", "small_bow"])
    catalog = GestureCatalog(catalog_dir)
    store = _store(tmp_path)
    store.reindex(catalog, force=True)

    ranked = store.search(GestureSearchRequest(query="", top_k=10))
    names = {entry.name for entry, _score in ranked}
    assert names == {"point_to_self", "small_bow"}


def test_search_respects_production_mode_against_draft_gestures(tmp_path):
    """point_to_self.yaml ist im echten Katalog tested_status: draft --
    im Produktionsmodus darf es nicht auftauchen."""
    catalog_dir = _copy_real_gestures(tmp_path, ["point_to_self"])
    catalog = GestureCatalog(catalog_dir)
    store = _store(tmp_path)
    store.reindex(catalog, force=True)

    assert catalog.get("point_to_self").tested_status == "draft"

    ranked = store.search(GestureSearchRequest(query="", production_mode=True))
    assert ranked == []


def test_affects_head_is_persisted_correctly_for_head_and_non_head_gestures(tmp_path):
    """Entwicklungsauftrag 04-B, AP5A, Abschnitt 5: affects_head muss aus
    dem echten Gestenkatalog (Gesture.affects_head(), siehe
    gesture_catalog.py) korrekt in den Index uebernommen werden --
    agree_nod bewegt nur HeadPitch (affects_head=True), wave_right
    bewegt nur Arm-/Ellbogengelenke (affects_head=False)."""
    catalog_dir = _copy_real_gestures(tmp_path, ["agree_nod", "wave_right"])
    catalog = GestureCatalog(catalog_dir)
    assert catalog.get("agree_nod").affects_head() is True
    assert catalog.get("wave_right").affects_head() is False

    store = _store(tmp_path)
    store.reindex(catalog, force=True)
    ranked = store.search(GestureSearchRequest(query="", top_k=10))
    affects_head_by_name = {entry.name: entry.affects_head for entry, _score in ranked}
    assert affects_head_by_name == {"agree_nod": True, "wave_right": False}


def test_semantic_tags_are_persisted_and_used_in_the_search_text(tmp_path):
    # Entwicklungsauftrag 04-B, AP8 (11/14), Abschnitt 8: semantic_tags
    # sind jetzt echte Gesture-Attribute und fliessen in den Suchtext ein.
    catalog_dir = _copy_real_gestures(tmp_path, ["wave_right"])
    catalog = GestureCatalog(catalog_dir)
    assert catalog.get("wave_right").semantic_tags == ["greeting", "waving", "farewell"]

    store = _store(tmp_path)
    store.reindex(catalog, force=True)
    ranked = store.search(GestureSearchRequest(query="farewell"))
    assert ranked
    assert ranked[0][0].name == "wave_right"
    assert ranked[0][0].semantic_tags == ["greeting", "waving", "farewell"]


def test_opening_a_pre_existing_db_file_without_the_semantic_tags_column_does_not_crash(tmp_path):
    # Entwicklungsauftrag 04-B, AP8 (11/14) (bestaetigter Fund):
    # 'CREATE TABLE IF NOT EXISTS' legt KEINE fehlende Spalte in einer
    # bereits bestehenden Datei nach -- eine aeltere gesture_index.db
    # (aus einer Session vor dieser Migration) darf reindex() NICHT mit
    # einem sqlite3.OperationalError abbrechen lassen.
    import sqlite3
    db_path = tmp_path / "old_gesture_index.db"
    old_schema = """
    CREATE TABLE gesture_index (
        name TEXT PRIMARY KEY,
        description TEXT NOT NULL,
        tested_status TEXT NOT NULL,
        duration_s REAL NOT NULL,
        allowed_interaction_states TEXT NOT NULL,
        requires_stationary INTEGER NOT NULL,
        affects_head INTEGER NOT NULL,
        system_only INTEGER NOT NULL,
        selectable_by_llm INTEGER NOT NULL,
        embedding TEXT,
        source_path TEXT NOT NULL,
        source_mtime REAL NOT NULL,
        indexed_at REAL NOT NULL
    );
    CREATE TABLE gesture_index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(old_schema)
    conn.commit()
    conn.close()

    catalog_dir = _copy_real_gestures(tmp_path, ["wave_right"])
    catalog = GestureCatalog(catalog_dir)
    store = GestureIndexStore(str(db_path), embedding_backend=DifflibFallbackBackend())
    result = store.reindex(catalog, force=True)
    assert result["indexed_count"] == 1
