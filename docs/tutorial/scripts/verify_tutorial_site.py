#!/usr/bin/env python3
"""verify_tutorial_site.py -- browser-level checks for the built Pepper
Developer Tutorial (Arbeitspaket 15, section 15.9). Complements
verify_tutorial_structure.py (source-only) with what only a real browser
can check: mobile layout, light/dark mode, the copy-button, and search.

Usage: build the site, serve it, then run this script against the
served URL.

    sphinx-build -E -a -W --keep-going docs/tutorial docs/tutorial/_build/html
    python3 -m http.server 8901 -d docs/tutorial/_build/html &
    python3 docs/tutorial/scripts/verify_tutorial_site.py http://localhost:8901

Playwright is intentionally not in docs/tutorial/requirements.txt --
building the site itself should never need a browser download. Install
it only when running this script (`pip install playwright && playwright
install chromium`).
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

PAGES = [
    "",
    "getting-started/index.html",
    "architecture/system-overview.html",
    "ros2/package-layout.html",
    "pepper-platform/capabilities-and-limits.html",
    "realsense-frames/coverage-gap.html",
    "mapping-navigation/realsense-only-navigation.html",
    "perception-interaction/person-engagement.html",
    "decision-making/interaction-behavior-tree.html",
    "dialogue-memory/three-stage-llm-pipeline.html",
    "dialogue-memory/person-memory.html",
    "gestures-kinematics/gesture-format.html",
    "gestures-kinematics/safe-gesture-development.html",
    "gestures-kinematics/gesture-catalog.html",
    "integration-testing/offline-dialogue-test.html",
    "integration-testing/gesture-validation.html",
    "deployment/development-nuc.html",
    "reference/interfaces.html",
    "reference/status-legend.html",
]


def check(condition: bool, results: list, label: str) -> None:
    results.append((label, condition))


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8901"
    results: list[tuple[str, bool]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. Every page loads with no console errors.
        for page_path in PAGES:
            page = browser.new_page()
            errors = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            resp = page.goto(f"{base_url}/{page_path}", wait_until="networkidle")
            check(resp is not None and resp.status == 200, results, f"loads 200: {page_path or 'index.html'}")
            check(len(errors) == 0, results, f"no console errors: {page_path or 'index.html'} ({errors[:1]})")
            page.close()

        # 2. Mobile viewport: the page must not actually be horizontally
        # scrollable by the user. document.documentElement.scrollWidth
        # reports the full intrinsic content width regardless of
        # `overflow-x: hidden` (that property only stops VISIBLE
        # scrolling), so the correct check is to actually try to scroll
        # and confirm the viewport does not move -- not compare
        # scrollWidth/clientWidth, which would false-positive on any
        # page with a wide table/code block even though nothing is
        # visibly scrollable.
        page = browser.new_page(viewport={"width": 375, "height": 812})
        page.goto(f"{base_url}/gestures-kinematics/gesture-catalog.html", wait_until="networkidle")
        page.evaluate("window.scrollTo(2000, 0)")
        scroll_x = page.evaluate("window.scrollX")
        check(scroll_x == 0, results, "mobile: page body itself does not scroll horizontally on gesture-catalog.html")
        page.close()

        # 3. Light/dark toggle button exists and actually flips data-theme.
        page = browser.new_page()
        page.goto(f"{base_url}/index.html", wait_until="networkidle")
        toggle = page.query_selector("#pdt-theme-toggle")
        check(toggle is not None, results, "theme toggle button present")
        if toggle is not None:
            before = page.evaluate("document.documentElement.getAttribute('data-theme')")
            toggle.click()
            after = page.evaluate("document.documentElement.getAttribute('data-theme')")
            check(before != after, results, "theme toggle changes data-theme")
        page.close()

        # 4. Copy button present on a page with a code block.
        page = browser.new_page()
        page.goto(f"{base_url}/getting-started/repository-and-environment.html", wait_until="networkidle")
        copy_btn = page.query_selector("button.copybtn")
        check(copy_btn is not None, results, "copy button present on a code block")
        page.close()

        # 5. Search works (search page loads and accepts a query param).
        page = browser.new_page()
        page.goto(f"{base_url}/search.html?q=gesture", wait_until="networkidle")
        check("search" in page.title().lower() or page.query_selector("#search-results") is not None,
              results, "search page loads")
        page.close()

        # 6. Navigation sidebar present and has at least 13 top-level entries.
        page = browser.new_page()
        page.goto(f"{base_url}/index.html", wait_until="networkidle")
        nav_captions = page.query_selector_all(".wy-menu-vertical p.caption")
        check(len(nav_captions) >= 13, results, f"sidebar has >=13 topic captions (found {len(nav_captions)})")
        page.close()

        browser.close()

    print("=== verify_tutorial_site.py results ===")
    failed = [label for label, ok in results if not ok]
    for label, ok in results:
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {label}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
