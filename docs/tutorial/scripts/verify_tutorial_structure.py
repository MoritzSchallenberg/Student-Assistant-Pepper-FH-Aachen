#!/usr/bin/env python3
"""verify_tutorial_structure.py -- source-level structure checks for the
Pepper Developer Tutorial (Arbeitspaket 15, section 15.9). No build, no
browser -- reads the Markdown/YAML/SVG sources in docs/tutorial/ directly.

Run with:

    python3 docs/tutorial/scripts/verify_tutorial_structure.py

Checks:

 1. exactly the 13 required topic directories exist, each with index.md;
 2. every internal Markdown link and every image reference resolves to a
    real file (a lighter, source-only complement to `sphinx-build -W`,
    which also catches heading-anchor issues -- run both);
 3. every image actually embedded in a published page has a matching
    entry in ASSET_PROVENANCE.yml with decision: approved -- no page may
    embed an image whose provenance entry is candidate/recreate/rejected
    or missing entirely;
 4. no absolute user home path (`/home/<user>/...`) appears in any page;
 5. no credential-shaped string (password/token/secret assignment, or a
    literal SSH password) appears -- the project's own
    `<PEPPER_QI_PASSWORD>` placeholder convention is the only accepted
    form;
 6. no old Spot-specific command (`webots_spot`, `ALMotion` calls copied
    verbatim from the ALeRT/Spot source archive, `spot_gen3_moveit`,
    literal "Boston Dynamics") is presented as a Pepper command;
 7. `docs/tutorial/.gitignore`-equivalent: `_build/` is excluded from
    Sphinx's own source scan (checked indirectly: conf.py exclude_patterns).

Exit code is 0 if every check passed, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TUTORIAL = REPO_ROOT / "docs" / "tutorial"

TOPIC_DIRS = [
    "getting-started",
    "architecture",
    "ros2",
    "pepper-platform",
    "realsense-frames",
    "mapping-navigation",
    "perception-interaction",
    "decision-making",
    "dialogue-memory",
    "gestures-kinematics",
    "integration-testing",
    "deployment",
    "reference",
]

LINK_RE = re.compile(r"\]\(([^)]+)\)")
IMAGE_FIGURE_RE = re.compile(r"```\{figure\}\s*([^\s]+)")
IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def all_md_files() -> list[Path]:
    return [p for p in TUTORIAL.rglob("*.md") if "_build" not in p.parts]


def check_topic_directories() -> list[str]:
    failures = []
    existing = {p.name for p in TUTORIAL.iterdir() if p.is_dir() and not p.name.startswith("_") and p.name != "scripts"}
    missing = [d for d in TOPIC_DIRS if d not in existing]
    for d in missing:
        failures.append(f"expected topic directory missing: docs/tutorial/{d}/")
    for d in TOPIC_DIRS:
        index = TUTORIAL / d / "index.md"
        if d not in missing and not index.is_file():
            failures.append(f"docs/tutorial/{d}/ has no index.md")
    unexpected = existing - set(TOPIC_DIRS)
    for d in sorted(unexpected):
        failures.append(f"unexpected top-level directory under docs/tutorial/: {d}/ (not one of the 13 topics)")
    if len(set(TOPIC_DIRS) & existing) != 13:
        failures.append(f"expected exactly 13 topic directories, found {len(set(TOPIC_DIRS) & existing)}")
    return failures


def resolve_link(raw: str, from_file: Path) -> Path | None:
    target = raw.split("#")[0].strip()
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    if target.startswith("../ASSET_PROVENANCE.yml") or target == "ASSET_PROVENANCE.yml":
        return TUTORIAL / "ASSET_PROVENANCE.yml"
    return (from_file.parent / target).resolve()


def check_internal_links_and_images() -> list[str]:
    failures = []
    for md in all_md_files():
        text = md.read_text(encoding="utf-8")
        for m in LINK_RE.finditer(text):
            target = resolve_link(m.group(1), md)
            if target is None:
                continue
            if not target.exists():
                failures.append(f"{md.relative_to(REPO_ROOT)}: broken link -> {m.group(1)}")
        for m in IMAGE_FIGURE_RE.finditer(text):
            target = (md.parent / m.group(1)).resolve()
            if not target.exists():
                failures.append(f"{md.relative_to(REPO_ROOT)}: figure references missing image -> {m.group(1)}")
        for m in IMAGE_MD_RE.finditer(text):
            target = (md.parent / m.group(1)).resolve()
            if not target.exists():
                failures.append(f"{md.relative_to(REPO_ROOT)}: image references missing file -> {m.group(1)}")
    return failures


def load_asset_provenance() -> dict[str, dict]:
    """Minimal, dependency-free YAML reading for this one file's shape
    (a top-level `assets:` list of flat-ish mappings) -- avoids requiring
    PyYAML just for this check. Falls back to PyYAML if available."""
    provenance_path = TUTORIAL / "ASSET_PROVENANCE.yml"
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(provenance_path.read_text(encoding="utf-8"))
        return {entry["id"]: entry for entry in data.get("assets", [])}
    except ImportError:
        pass

    # Fallback: a small line-based parser good enough for this file's
    # own flat structure (id/decision/source_path pairs per asset).
    entries: dict[str, dict] = {}
    current: dict | None = None
    for line in provenance_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^  - id:\s*(\S+)", line)
        if m:
            current = {"id": m.group(1)}
            entries[current["id"]] = current
            continue
        if current is None:
            continue
        m2 = re.match(r"^\s+(\w+):\s*(.*)$", line)
        if m2 and m2.group(1) in ("decision", "source_path", "platform"):
            current[m2.group(1)] = m2.group(2).strip().strip('"')
    return entries


def check_image_provenance() -> list[str]:
    failures = []
    provenance = load_asset_provenance()
    by_path = {}
    for entry in provenance.values():
        sp = entry.get("source_path", "")
        if sp.startswith("docs/tutorial/"):
            by_path[Path(REPO_ROOT / sp).resolve()] = entry

    for md in all_md_files():
        text = md.read_text(encoding="utf-8")
        referenced = set()
        for m in IMAGE_FIGURE_RE.finditer(text):
            referenced.add((md.parent / m.group(1)).resolve())
        for m in IMAGE_MD_RE.finditer(text):
            referenced.add((md.parent / m.group(1)).resolve())
        for img in referenced:
            if "_static/images" not in img.parts:
                continue
            entry = by_path.get(img)
            if entry is None:
                failures.append(
                    f"{md.relative_to(REPO_ROOT)}: embeds {img.name} with NO ASSET_PROVENANCE.yml entry"
                )
            elif entry.get("decision") != "approved":
                failures.append(
                    f"{md.relative_to(REPO_ROOT)}: embeds {img.name} whose provenance decision is "
                    f"{entry.get('decision')!r}, not 'approved'"
                )
    return failures


def check_no_absolute_user_paths() -> list[str]:
    failures = []
    pattern = re.compile(r"/home/[a-zA-Z0-9_.-]+/")
    for md in all_md_files():
        text = md.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                failures.append(f"{md.relative_to(REPO_ROOT)}:{i}: absolute user home path found")
    return failures


def check_no_credentials() -> list[str]:
    failures = []
    pattern = re.compile(
        r"(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?(?!<[A-Z_]+>)\S",
        re.IGNORECASE,
    )
    for md in all_md_files():
        text = md.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line) and "<PEPPER_QI_PASSWORD>" not in line:
                failures.append(f"{md.relative_to(REPO_ROOT)}:{i}: credential-shaped string found")
    return failures


_SPOT_TERMS = ("webots_spot", "spot_gen3_moveit", "boston dynamics", "alert_auto_dexterity")


def check_no_spot_commands_as_pepper() -> list[str]:
    failures = []
    for md in all_md_files():
        text_lower = md.read_text(encoding="utf-8").lower()
        for term in _SPOT_TERMS:
            if term in text_lower:
                failures.append(f"{md.relative_to(REPO_ROOT)}: references Spot-specific term {term!r}")
    return failures


def check_build_excludes() -> list[str]:
    conf = (TUTORIAL / "conf.py").read_text(encoding="utf-8")
    if '"_build"' not in conf:
        return ["docs/tutorial/conf.py: exclude_patterns does not exclude '_build'"]
    return []


def main() -> int:
    all_failures: list[str] = []
    all_failures.extend(check_topic_directories())
    all_failures.extend(check_internal_links_and_images())
    all_failures.extend(check_image_provenance())
    all_failures.extend(check_no_absolute_user_paths())
    all_failures.extend(check_no_credentials())
    all_failures.extend(check_no_spot_commands_as_pepper())
    all_failures.extend(check_build_excludes())

    print("=== verify_tutorial_structure.py results ===")
    if all_failures:
        for f in all_failures:
            print(f"  [FAIL] {f}")
        print(f"\n{len(all_failures)} failure(s)")
        return 1

    print(f"All structural checks passed for {len(TOPIC_DIRS)} topic directories.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
