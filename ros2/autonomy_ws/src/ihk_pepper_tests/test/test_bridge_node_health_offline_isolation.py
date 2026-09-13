"""
Entwicklungsauftrag 04-B, AP8.9 (Commit 14/14), Abschnitt 5: vollstaendige
Offline-Isolation. Bestaetigter Fund: bridge_node.py::_publish_health()
rief bisher UNBEDINGT self.pepper.is_reachable() auf -- ein echter
TCP-Verbindungsversuch (socket.create_connection zu Host:22), komplett
unabhaengig vom dry_run-Parameter. Ein periodisch laufender Health-Timer
(auch im vollstaendigen Offline-/dry_run-Betrieb) durfte NIE einen
echten Netzwerkzugriff versuchen -- selbst ein scheiternder
Verbindungsversuch verletzt vollstaendige Offline-Isolation.

Gleiches Duck-Typing-Muster wie test_bridge_node_joint_states.py -- die
ECHTE, ungebundene Methode von PepperBridgeNode laeuft gegen ein
leichtgewichtiges Fake, kein rclpy.init() noetig. self.pepper ist hier
absichtlich ein Fake, dessen is_reachable()/get_bumper_pressed()/
get_charging_state()/get_battery() SOFORT eine Exception werfen, falls
sie im dry_run ueberhaupt aufgerufen werden -- ein test double, das
einen echten Hardwarezugriff strukturell nachweisbar macht, statt ihn
nur zu behaupten.
"""
from ihk_pepper_bridge.bridge_node import PepperBridgeNode


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _FakeTime:
    def to_msg(self):
        return "stamp"


class _FakeClock:
    def now(self):
        return _FakeTime()


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(msg)


class _FreshBoolRecorder:
    def __init__(self):
        self.updates = []

    def update(self, value, now):
        self.updates.append(value)


class _FailOnUseFakePepperClient:
    """Wirft SOFORT eine Exception bei jedem Zugriff, der einen echten
    Hardware-/Netzwerkzugriff bedeuten wuerde -- beweist damit, dass der
    dry_run-Pfad diese Methoden ueberhaupt nicht erst aufruft, statt nur
    zu behaupten, es gaebe keinen Zugriff."""

    def is_reachable(self, timeout_s=1.0):
        raise AssertionError(
            "is_reachable() wurde im dry_run aufgerufen -- echter TCP-Verbindungsversuch!")

    def get_bumper_pressed(self):
        raise AssertionError("get_bumper_pressed() im dry_run aufgerufen -- echte Hardwareabfrage!")

    def get_charging_state(self):
        raise AssertionError("get_charging_state() im dry_run aufgerufen -- echte Hardwareabfrage!")

    def get_battery(self):
        raise AssertionError("get_battery() im dry_run aufgerufen -- echte Hardwareabfrage!")

    def get_angle(self, joint):
        raise AssertionError("get_angle() im dry_run aufgerufen -- echte Hardwareabfrage!")

    @property
    def connection_state(self):
        # Reiner Attributzugriff, kein Netzwerk -- unproblematisch, wird
        # in _publish_health() unabhaengig von reachable gelesen.
        return "disconnected"


class _RealReachablePepperClient:
    """Fuer den NICHT-dry_run-Vergleichsfall: zaehlt echte Aufrufe,
    liefert feste Werte -- stellt sicher, dass die Nachbesserung den
    regulaeren (nicht-dry_run) Pfad nicht versehentlich mit abschaltet."""

    def __init__(self):
        self.is_reachable_calls = 0
        self.get_angle_calls = 0

    def is_reachable(self, timeout_s=1.0):
        self.is_reachable_calls += 1
        return True

    def get_bumper_pressed(self):
        return False

    def get_charging_state(self):
        return False

    def get_battery(self):
        return 80.0

    def get_angle(self, joint):
        self.get_angle_calls += 1
        return 0.0

    @property
    def connection_state(self):
        return "connected"


class _FakeNode:
    _publish_health = PepperBridgeNode._publish_health
    _publish_joint_states = PepperBridgeNode._publish_joint_states

    def __init__(self, dry_run: bool, pepper_client):
        self._params = {
            "dry_run": dry_run,
            "health_publish_interval_s": 5.0,
        }
        self.pepper = pepper_client
        self._pepper_reachable_fresh = _FreshBoolRecorder()
        self.bumper_pub = _FakePublisher()
        self.charging_state_pub = _FakePublisher()
        self.battery_pub = _FakePublisher()
        self.connection_state_pub = _FakePublisher()
        self.joint_states_pub = _FakePublisher()
        self.health_pub = _FakePublisher()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock()


def test_publish_health_never_touches_the_pepper_client_in_dry_run():
    node = _FakeNode(dry_run=True, pepper_client=_FailOnUseFakePepperClient())
    # Wirft NICHT (der Fake wuerde bei jedem echten Zugriff eine
    # AssertionError werfen) -- das ist der eigentliche Beweis.
    node._publish_health()

    assert node._pepper_reachable_fresh.updates == [False]
    assert node.health_pub.published[0].pepper_bridge_ok is False
    assert node.joint_states_pub.published == []  # _publish_joint_states() kehrte sofort zurueck


def test_publish_health_reports_a_recognizably_simulated_safe_state_in_dry_run():
    node = _FakeNode(dry_run=True, pepper_client=_FailOnUseFakePepperClient())
    node._publish_health()

    msg = node.health_pub.published[0]
    # Sicherste Werte, klar dem "nicht erreichbar"-Pfad entsprechend --
    # NIE eine Hardwarefreigabe begruenden.
    assert msg.pepper_bridge_ok is False
    assert "pepper_unreachable" in msg.active_warnings
    assert node.bumper_pub.published[0].data is True  # unbekannt -> sicherster (gesperrter) Wert
    assert node.charging_state_pub.published[0].data is False


def test_publish_health_still_calls_the_real_client_when_not_dry_run():
    # Gegenprobe: die Nachbesserung darf den regulaeren, NICHT-dry_run
    # Health-Check nicht versehentlich mit abschalten.
    pepper = _RealReachablePepperClient()
    node = _FakeNode(dry_run=False, pepper_client=pepper)
    node._publish_health()

    assert pepper.is_reachable_calls == 1
    assert node._pepper_reachable_fresh.updates == [True]
    assert node.health_pub.published[0].pepper_bridge_ok is True
    assert pepper.get_angle_calls == 2  # HeadYaw + HeadPitch ueber _publish_joint_states()
