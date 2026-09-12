"""
Drift-Test fuer docs/GESTURE_CATALOG_INVENTORY.md (Entwicklungsauftrag
04-B, AP8, Commit 11/14, Abschnitt 10): die eingecheckte Inventardatei
MUSS mit einer frischen Generierung aus dem aktuellen Katalog identisch
sein -- sie darf nicht von Hand nachgepflegt/vergessen worden sein.
"""
import importlib.util
import os

import pytest
from ament_index_python.packages import get_package_share_directory


def _find_repo_root():
    """Sucht vom Paket-Share-Verzeichnis aus nach oben, bis 'scripts/
    generate_gesture_inventory.py' gefunden wird -- funktioniert sowohl
    im Quellbaum als auch nach colcon build (share-Verzeichnis liegt
    unter install/, nicht src/, daher kein einfacher relativer Pfad ab
    __file__)."""
    try:
        start = get_package_share_directory("ihk_pepper_bridge")
    except Exception:
        pytest.skip("ihk_pepper_bridge share-Verzeichnis nicht gefunden (nicht gesourced?)")
    # Fallback: vom Testdatei-Pfad aus nach oben suchen (deckt einen
    # reinen Quellbaum-Lauf ohne vorherigen colcon build ab).
    candidates = [start, os.path.dirname(os.path.abspath(__file__))]
    for candidate in candidates:
        current = candidate
        for _ in range(12):
            if os.path.isfile(os.path.join(current, "scripts", "generate_gesture_inventory.py")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    pytest.skip("Repo-Wurzel (scripts/generate_gesture_inventory.py) nicht gefunden.")


def _load_generator_module():
    repo_root = _find_repo_root()
    script_path = os.path.join(repo_root, "scripts", "generate_gesture_inventory.py")
    spec = importlib.util.spec_from_file_location("generate_gesture_inventory", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, repo_root


def test_checked_in_inventory_matches_a_fresh_generation():
    module, repo_root = _load_generator_module()
    gesture_dir = os.path.join(
        repo_root, "ros2", "autonomy_ws", "src", "ihk_pepper_bridge", "config", "gestures")
    output_path = os.path.join(repo_root, "docs", "GESTURE_CATALOG_INVENTORY.md")
    if not os.path.isdir(gesture_dir) or not os.path.isfile(output_path):
        pytest.skip("Gestenordner oder Inventardatei im Quellbaum nicht gefunden.")

    fresh = module._generate(gesture_dir)
    with open(output_path) as f:
        checked_in = f.read()
    assert checked_in == fresh, (
        "docs/GESTURE_CATALOG_INVENTORY.md ist veraltet -- "
        "'python3 scripts/generate_gesture_inventory.py' erneut ausfuehren."
    )
