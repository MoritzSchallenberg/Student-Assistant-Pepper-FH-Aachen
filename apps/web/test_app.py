"""
Tests fuer die Hardwaretest-Sperre in app.py (Entwicklungsauftrag 04-B,
AP5B, Abschnitt 15): app.py ist ein manuelles Entwicklerwerkzeug, das
qicli DIREKT anspricht, an der ihk_pepper_bridge/Aktuator-Arbiter-
Sicherheitskette vorbei. JEDE Route, die qicli anspricht, muss per
Default (PEPPER_WEB_HARDWARE_TEST_ENABLED=false) blockiert sein -- ein
qicli-Aufruf wuerde real eine SSH-Verbindung zu Pepper aufbauen, daher
wird qicli in diesen Tests IMMER durch ein Fake ersetzt, selbst wenn die
Sperre bewusst deaktiviert wird, um eine Route ohne Sperre zu pruefen.
"""
import config.config as _cfg
import app as app_module


class _FakeQicli:
    def __init__(self):
        self.calls = []

    def say(self, text):
        self.calls.append(("say", text))
        return "ok", None

    def moveTo(self, x, y, theta):
        self.calls.append(("moveTo", x, y, theta))
        return "ok", None

    def setAutonomousLife(self, enabled):
        self.calls.append(("setAutonomousLife", enabled))
        return "ok", None

    def showImage(self, path):
        self.calls.append(("showImage", path))
        return "ok", None


def _client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_execute_route_blocked_by_default(monkeypatch):
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    fake = _FakeQicli()
    monkeypatch.setattr(app_module, "qicli", fake)

    resp = _client().post("/execute", data={"function": "say", "message": "hallo"})

    assert resp.status_code == 403
    assert fake.calls == []  # qicli NIE erreicht


def test_execute_route_with_movetoblocked_by_default(monkeypatch):
    # moveTo ist eine ECHTE Bewegung -- besonders wichtig, dass sie
    # gesperrt bleibt.
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    fake = _FakeQicli()
    monkeypatch.setattr(app_module, "qicli", fake)

    resp = _client().post(
        "/execute", data={"function": "moveTo", "x": "1.0", "y": "0.0", "theta": "0.0"})

    assert resp.status_code == 403
    assert fake.calls == []


def test_say_route_blocked_by_default(monkeypatch):
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    fake = _FakeQicli()
    monkeypatch.setattr(app_module, "qicli", fake)

    resp = _client().get("/say/hallo")

    assert resp.status_code == 403
    assert fake.calls == []


def test_al_route_blocked_by_default(monkeypatch):
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    fake = _FakeQicli()
    monkeypatch.setattr(app_module, "qicli", fake)

    resp = _client().get("/al/True")

    assert resp.status_code == 403
    assert fake.calls == []


def test_logo_route_blocked_by_default(monkeypatch):
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    fake = _FakeQicli()
    monkeypatch.setattr(app_module, "qicli", fake)

    resp = _client().get("/logo")

    assert resp.status_code == 403
    assert fake.calls == []


def test_execute_route_reaches_qicli_when_explicitly_enabled(monkeypatch):
    # Auch im "aktivierten" Fall wird NIE eine echte SSH-Verbindung
    # aufgebaut -- nur geprueft, dass die Sperre selbst korrekt
    # durchlaesst, wenn sie bewusst deaktiviert wurde.
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", True)
    fake = _FakeQicli()
    monkeypatch.setattr(app_module, "qicli", fake)

    resp = _client().post("/execute", data={"function": "say", "message": "hallo"})

    assert resp.status_code == 200
    assert fake.calls == [("say", "hallo")]


def test_hardware_test_guard_returns_none_when_enabled(monkeypatch):
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", True)
    assert app_module._hardware_test_guard() is None


def test_hardware_test_guard_returns_403_payload_when_disabled(monkeypatch):
    monkeypatch.setattr(_cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    payload, status = app_module._hardware_test_guard()
    assert status == 403
    assert "error" in payload
