#!/usr/bin/env python3
"""
Erzeugt docs/GESTURE_CATALOG_INVENTORY.md aus dem echten YAML-Gestenkatalog
(Entwicklungsauftrag 04-B, AP8, Commit 11/14, Abschnitt 10). Nutzt
DIESELBE validierte GestureCatalog/Gesture-Klasse und denselben
Audit-Renderer wie `gesturectl audit` (ihk_pepper_bridge.gesture_catalog_audit)
-- die Inventartabelle kann dadurch nicht mehr von Hand aus der Reihe
laufen. Rein lesend: instanziiert NIE einen Pepper-Client, ruft NIE
SSH/qicli/eine ROS-Action auf, veraendert NIE eine YAML-Datei.

Nutzung (nach `colcon build`, mit gesourctem Workspace):
    python3 scripts/generate_gesture_inventory.py
    python3 scripts/generate_gesture_inventory.py --check   # nur Drift pruefen, nichts schreiben
"""
import argparse
import glob
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_GESTURE_DIR = os.path.join(
    _REPO_ROOT, "ros2", "autonomy_ws", "src", "ihk_pepper_bridge", "config", "gestures")
_DEFAULT_OUTPUT_PATH = os.path.join(_REPO_ROOT, "docs", "GESTURE_CATALOG_INVENTORY.md")


def _generate(gesture_dir: str) -> str:
    from ihk_pepper_bridge.gesture_catalog import GestureCatalog
    from ihk_pepper_bridge.gesture_catalog_audit import audit_catalog, render_inventory_markdown

    catalog = GestureCatalog(gesture_dir)
    errors = catalog.reload()
    total_files = len(glob.glob(os.path.join(gesture_dir, "*.yaml")))
    result = audit_catalog(catalog, load_errors=errors, total_yaml_files_found=total_files)
    if errors:
        for e in errors:
            print(f"WARNUNG beim Laden: {e}", file=sys.stderr)
    return render_inventory_markdown(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gesture-dir", default=_DEFAULT_GESTURE_DIR)
    parser.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--check", action="store_true",
        help="nur pruefen, ob die eingecheckte Datei einer frischen Generierung entspricht "
        "(Exitcode 1 bei Abweichung) -- schreibt NICHTS.",
    )
    args = parser.parse_args(argv)

    fresh = _generate(args.gesture_dir)

    if args.check:
        try:
            with open(args.output) as f:
                current = f.read()
        except FileNotFoundError:
            print(f"FEHLER: '{args.output}' existiert nicht.", file=sys.stderr)
            return 1
        if current != fresh:
            print(
                f"FEHLER: '{args.output}' ist veraltet (weicht von einer frischen Generierung "
                "aus dem aktuellen Katalog ab) -- 'python3 scripts/generate_gesture_inventory.py' "
                "erneut ausfuehren.",
                file=sys.stderr,
            )
            return 1
        print(f"'{args.output}' ist aktuell.")
        return 0

    with open(args.output, "w") as f:
        f.write(fresh)
    print(f"'{args.output}' geschrieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
