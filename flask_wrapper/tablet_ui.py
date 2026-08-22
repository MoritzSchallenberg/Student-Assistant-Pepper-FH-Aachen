"""
Erweiterte Tablet-Oberflaeche (Entwicklungsauftrag Abschnitt 20).

Eigenstaendiges Flask-Blueprint, NEBEN den bestehenden Routen in app.py --
nichts Bestehendes wird veraendert oder entfernt (Auftrag Abschnitt 3.1).
Registrierung erfolgt in app.py via `app.register_blueprint(tablet_bp)`.

Getestet (2026-08-20): /tablet/, /tablet/api/state, /tablet/api/control
gegen eine laufende ROS2-Kette (presentation_manager_node + supervisor_node
+ dialog_manager_node + bridge_node) OHNE echten Pepper -- siehe
IMPLEMENTATION_REPORT.md. Auf einem echten Pepper-Tablet (Android-Webview)
NICHT getestet (kein Zugriff in dieser Session).
"""
import os

from flask import Blueprint, jsonify, render_template, request, send_from_directory, abort
from werkzeug.utils import safe_join

from tablet.ros_bridge import bridge

tablet_bp = Blueprint(
    "tablet", __name__, url_prefix="/tablet", template_folder="templates"
)

# Erlaubte Basisverzeichnisse fuer Video/Untertitel-Auslieferung --
# feste Liste, kein beliebiger Dateizugriff (Abschnitt 3.4). Deckt sowohl
# den installierten ROS2-share-Ordner als auch den src-Ordner ab (fuer
# Entwicklung ohne vorherigen colcon build --symlink-install).
_WS_ROOT = os.environ.get(
    "PEPPER_AUTONOMY_WS", "/home/canvastino/Schreibtisch/Pepper/pepper_autonomy_ws"
)
_MEDIA_ROOTS = [
    os.path.join(_WS_ROOT, "install", "ihk_pepper_presentation", "share",
                 "ihk_pepper_presentation", "content"),
    os.path.join(_WS_ROOT, "src", "ihk_pepper_presentation", "content"),
]


@tablet_bp.route("/")
def tablet_home():
    return render_template("tablet.html")


@tablet_bp.route("/api/state")
def tablet_state():
    return jsonify(bridge.get_snapshot())


@tablet_bp.route("/api/control", methods=["POST"])
def tablet_control():
    action = request.form.get("action")
    if action is None:
        json_body = request.get_json(silent=True) or {}
        action = json_body.get("action")

    # Feste Zuordnung Tablet-Button -> ROS2-Kanal (Abschnitt 3.4: kein
    # Freitext, nur dieser Allowlist-Dispatch). "Wiederholen" geht an
    # BEIDE Kanaele, weil ein Klick sowohl waehrend einer Praesentation
    # (presentation_control) als auch waehrend eines Dialogs
    # (audio_node/voice_command) sinnvoll sein kann -- die jeweils nicht
    # zustaendige Seite ignoriert die Nachricht einfach.
    if action in ("stop", "back"):
        success, message = bridge.request_stop()
    elif action in ("pause", "resume"):
        success, message = bridge.request_control(action)
    elif action == "repeat":
        ok1, msg1 = bridge.request_control("repeat")
        ok2, msg2 = bridge.request_voice_command("repeat")
        success, message = (ok1 or ok2), f"{msg1}; {msg2}"
    else:
        return jsonify({"success": False, "message": f"Unbekannte Aktion: {action}"}), 400
    return jsonify({"success": success, "message": message})


@tablet_bp.route("/media/<path:relpath>")
def tablet_media(relpath):
    """Liefert Video-/Untertitel-Dateien fuer die Praesentation aus.
    Nur aus den festen _MEDIA_ROOTS -- safe_join lehnt Pfad-Traversal
    (z.B. '../../etc/passwd') explizit ab, statt es stillschweigend
    aufzuloesen (Abschnitt 3.4: kein beliebiger Dateizugriff)."""
    for root in _MEDIA_ROOTS:
        candidate = safe_join(root, relpath)
        if candidate and os.path.isfile(candidate):
            directory, filename = os.path.split(candidate)
            return send_from_directory(directory, filename)
    abort(404)
