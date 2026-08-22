"""
Threadsicherer Wrapper um flask_wrapper/pepper/qicli.py.

Grund: sowohl der Flask-Server (app.py, Live-Weboberflaeche) als auch
dieser autonome ROS2-Bridge-Node koennen gleichzeitig SSH-Kommandos an
Pepper schicken wollen. paramikos SSHClient ist NICHT thread-sicher fuer
parallele exec_command()-Aufrufe auf derselben Verbindung. Diese Klasse
serialisiert alle Aufrufe ueber einen Lock.

Empfehlung (siehe IMPLEMENTATION_REPORT.md): langfristig sollte app.py
ebenfalls ueber diesen Bridge-Node laufen (per ROS2-Service/Action),
statt eine zweite, unabhaengige SSH-Verbindung zu halten. Fuer diese
Session wurde nur die Absicherung *innerhalb* eines Prozesses umgesetzt
(dieser Wrapper) -- Koordination *zwischen* Flask-Prozess und ROS2-Node
(zwei verschiedene Prozesse) ist damit NICHT abgedeckt und im Bericht als
offener Punkt vermerkt.
"""
import os
import sys
import threading

_FLASK_WRAPPER_PATH = os.environ.get(
    "PEPPER_FLASK_WRAPPER_PATH",
    "/home/canvastino/Schreibtisch/Pepper/flask_wrapper",
)
if _FLASK_WRAPPER_PATH not in sys.path:
    sys.path.insert(0, _FLASK_WRAPPER_PATH)

from pepper.qicli import qicli  # noqa: E402
import config.config as _cfg  # noqa: E402

from .joint_limits import validate_angle, JointLimitError  # noqa: E402


class ThreadSafePepperClient:
    """Serialisiert alle qicli-Aufrufe ueber einen Lock. Verbindet sich
    lazy beim ersten Aufruf (nicht schon beim Erzeugen der Node), damit
    der Bridge-Node auch startet, wenn Pepper gerade nicht erreichbar ist."""

    def __init__(self, host=None, user=None, password=None):
        self._host = host or _cfg.QI_HOST
        self._user = user or _cfg.QI_USER
        self._password = password or _cfg.QI_PW
        self._lock = threading.RLock()
        self._client = qicli(self._host, self._user, self._password)
        self._connected = False

    def _ensure_connected(self):
        if not self._connected:
            self._client.connect()
            self._connected = True

    def is_reachable(self, timeout_s: float = 2.0) -> bool:
        """Nicht-blockierender Erreichbarkeits-Check (fuer Health-Reporting,
        wirft nie eine Exception)."""
        import socket
        try:
            with socket.create_connection((self._host, 22), timeout=timeout_s):
                return True
        except OSError:
            return False

    # ---- Durchgereichte, threadsichere Methoden ----

    def say(self, text: str):
        with self._lock:
            self._ensure_connected()
            return self._client.say(text)

    def set_angle(self, joint: str, angle: float, duration: float = 1.0, strict_limits: bool = True):
        angle = validate_angle(joint, angle, strict=strict_limits)
        with self._lock:
            self._ensure_connected()
            return self._client.set_angle(joint, angle, duration)

    def get_angle(self, joint: str):
        with self._lock:
            self._ensure_connected()
            return self._client.get_angle(joint)

    def snapshot_joints(self, joints):
        with self._lock:
            self._ensure_connected()
            return self._client.snapshot_joints(joints)

    def restore_joints(self, snapshot, duration: float = 1.5):
        with self._lock:
            self._ensure_connected()
            return self._client.restore_joints(snapshot, duration)

    def set_breathing(self, enabled: bool, part=None):
        with self._lock:
            self._ensure_connected()
            return self._client.setBreathing(enabled, part)

    def get_battery(self):
        with self._lock:
            self._ensure_connected()
            return self._client.get_battery()

    def get_touch_status(self):
        with self._lock:
            self._ensure_connected()
            return self._client.get_touch_status()

    def get_autonomous_life_state(self):
        with self._lock:
            self._ensure_connected()
            return self._client.get_autonomous_life_state()

    def set_autonomous_life_state(self, state: str):
        with self._lock:
            self._ensure_connected()
            return self._client.set_autonomous_life_state(state)

    def set_led_color(self, group: str, color: str, duration: float = 0.5):
        with self._lock:
            self._ensure_connected()
            return self._client.set_led_color(group, color, duration)

    def show_url(self, url: str):
        with self._lock:
            self._ensure_connected()
            return self._client.showURL(url)

    def close(self):
        with self._lock:
            if self._connected:
                self._client.close()
                self._connected = False
