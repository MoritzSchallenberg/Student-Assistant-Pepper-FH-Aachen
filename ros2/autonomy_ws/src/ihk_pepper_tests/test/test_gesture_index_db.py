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
