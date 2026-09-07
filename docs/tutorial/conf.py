# Sphinx configuration for the Pepper Developer Tutorial.
#
# Structural template: Learning-Robotics-Crash-Course (the ALeRT Advanced
# Robotics Tutorial) -- see docs/tutorial/ASSET_PROVENANCE.yml and the
# Arbeitspaket-15 report section of DEVELOPMENT_ORDER_03_REPORT.md for
# what was adopted vs. deliberately built fresh for Pepper.
#
# This is a documentation site ABOUT the real ihk-pepper codebase in this
# repository. Every technical claim on a published page must trace back to
# real code/docs under ros2/autonomy_ws/src/ or docs/*.md -- see
# maintainers-only... (there are no maintainer-only pages in this
# project; every page here is written to already meet that bar).

project = "Pepper Developer Tutorial"
author = "IHK Pepper Project"
copyright = "IHK Pepper Project"
html_title = "Pepper Developer Tutorial"

extensions = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
]

source_suffix = {".md": "markdown"}
master_doc = "index"

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "attrs_inline",
    "substitution",
]
myst_heading_anchors = 3

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["css/custom.css"]
html_js_files = ["js/color-mode.js"]

# Deployed at a repository subpath (mirrors the ALeRT site's own
# constraint) -- every asset path must stay relative. Never introduce an
# absolute path beginning with "/".
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 3,
    "titles_only": False,
}

copybutton_prompt_text = r">>> |\$ |# "
copybutton_prompt_is_regexp = True


def _badge(css_class: str, label: str) -> str:
    return f'<span class="pdt-badge pdt-badge--{css_class}">{label}</span>'


def _level(css_class: str, label: str) -> str:
    return f'<span class="pdt-level pdt-level--{css_class}">{label}</span>'


def _safety(css_class: str, label: str) -> str:
    return f'<span class="pdt-safety pdt-safety--{css_class}">{label}</span>'


myst_substitutions = {
    "pepper": _badge("pepper", "PEPPER"),
    # ---------------------------------------------------------------------
    # Difficulty badges (Arbeitspaket 15, section 15.4). Mark genuine
    # technical difficulty, never how central a topic is to the project.
    # ---------------------------------------------------------------------
    "foundation": _level("foundation", "FOUNDATION"),
    "intermediate": _level("intermediate", "INTERMEDIATE"),
    "advanced": _level("advanced", "ADVANCED"),
    "research": _level("research", "RESEARCH"),
    # ---------------------------------------------------------------------
    # Verification badges. A passed mock/offline test is never
    # HARDWARE-VERIFIED; a live-executed arm motion is HARDWARE-VERIFIED
    # only after a supervised live test with tested_status: live_validated
    # written back by a human -- see gestures-kinematics/safe-gesture-
    # development.md.
    # ---------------------------------------------------------------------
    "documented": _badge("documented", "DOCUMENTED"),
    "offlinetested": _badge("offline-tested", "OFFLINE-TESTED"),
    "simulationtested": _badge("simulation-tested", "SIMULATION-TESTED"),
    "hardwareverified": _badge("hardware-verified", "HARDWARE-VERIFIED"),
    "hwverificationrequired": _badge(
        "hw-verification-required", "HARDWARE-VERIFICATION-REQUIRED"
    ),
    "experimental": _badge("experimental", "EXPERIMENTAL"),
    "unverified": _badge("unverified", "UNVERIFIED"),
    "historical": _badge("historical", "HISTORICAL"),
    # ---------------------------------------------------------------------
    # Safety-level badges for any exercise that touches real Pepper
    # hardware (section 15.4). Every hardware exercise on this site
    # carries exactly one.
    # ---------------------------------------------------------------------
    "offlineexercise": _safety("offline-exercise", "OFFLINE EXERCISE"),
    "readonlypepper": _safety("readonly-pepper", "READ-ONLY ON PEPPER"),
    "supervisedgesture": _safety("supervised-gesture", "SUPERVISED PEPPER GESTURE"),
    "supervisedmotion": _safety("supervised-motion", "SUPERVISED PEPPER MOTION"),
    "navblocked": _safety("nav-blocked", "LIVE NAVIGATION BLOCKED"),
}
