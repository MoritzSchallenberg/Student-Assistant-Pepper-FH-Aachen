"""
Entwicklungsauftrag 04-B, AP2/AP3: Tests fuer SupervisorNode's
_build_safety_inputs() -- echte Aktualitaetspruefung je Eingang plus die
drei konkret behobenen unsicheren Defaults (battery_percent=100.0,
compute_power_valid=true, hardware_fault fest False).

Ruft die echten, ungebundenen SupervisorNode-Methoden gegen ein
leichtgewichtiges Fake-Objekt auf (gleiches Muster wie
test_dialogue_thinking_loop.py/test_motion_guard_freshness.py) -- kein
rclpy.init() noetig, aber exakt derselbe Code wie im echten Node.
"""
from std_msgs.msg import Bool, Float32, String

from ihk_pepper_interaction.interaction_state import InteractionState, InteractionStateMachine
from ihk_pepper_interaction.safety_gate import SafetyGate
from ihk_pepper_interaction.safety_topics import FreshBool
from ihk_pepper_interaction.supervisor_node import SupervisorNode


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def info(self, *_a, **_kw):
        pass

    def warn(self, *_a, **_kw):
        pass


class _FakeSupervisorNode:
    def __init__(self, params=None, now=1000.0, motion_capable=True):
        self._params = dict(
            low_battery_threshold=15.0, max_data_age_s=2.0, max_input_age_s=2.0,
        )
        self._params.update(params or {})
        self._t = now
        self._last_tracks_t = None
        self._battery_valid = FreshBool(False)
        self._battery_percent_raw = 0.0
        self._compute_power_valid = FreshBool(False)
        self._localization_valid = FreshBool(False)
        self._obstacle_data_valid = FreshBool(False)
        self._person_depth_valid = FreshBool(False)
        self._bumper_active = FreshBool(True)
        self._bridge_connected = FreshBool(False)
        self._is_charging = FreshBool(False)
        self._charging_cable_connected = FreshBool(True)
        self.state_machine = InteractionStateMachine()
        self.safety_gate = SafetyGate(motion_capable=motion_capable)
        self.safety_gate.request_motion_permission(True, True)

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def _now(self):
        return self._t


def _all_clear(node, now=None):
    now = node._t if now is None else now
    node._battery_valid.update(True, now)
    node._battery_percent_raw = 80.0
    node._compute_power_valid.update(True, now)
    node._localization_valid.update(True, now)
    node._obstacle_data_valid.update(True, now)
    node._person_depth_valid.update(True, now)
    node._bumper_active.update(False, now)
    node._bridge_connected.update(True, now)
    return node


# ---- Batterie erreicht den Supervisor ----

def test_battery_value_reaches_safety_inputs():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_battery(node, Float32(data=42.0))
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.battery_percent == 42.0


def test_battery_sentinel_negative_one_is_treated_as_unknown_not_literal():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_battery(node, Float32(data=-1.0))
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.battery_percent == 0.0  # fail-closed, NICHT -1.0


def test_battery_never_received_defaults_to_fail_closed_zero_not_hundred():
    node = _FakeSupervisorNode()  # kein _on_battery() aufgerufen
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.battery_percent == 0.0
    assert inputs.battery_percent < node._params["low_battery_threshold"]


def test_stale_battery_value_is_ignored():
    node = _all_clear(_FakeSupervisorNode(now=1000.0))
    SupervisorNode._on_battery(node, Float32(data=90.0))
    node._t = 1000.0 + 10.0  # weit ueber max_input_age_s
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.battery_percent == 0.0


# ---- compute_power_valid: unsicherer Default behoben ----

def test_compute_power_valid_never_received_defaults_false_not_true():
    node = _FakeSupervisorNode()
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.compute_power_valid is False


def test_unknown_compute_power_status_blocks_motion():
    node = _FakeSupervisorNode()
    inputs = SupervisorNode._build_safety_inputs(node)
    result = node.safety_gate.evaluate(inputs)
    assert result["allow_motion"] is False
    assert "compute_power_invalid" in result["reason"]


# ---- hardware_fault jetzt aus echter Bridge-Verbindung ----

def test_hardware_fault_true_when_connection_never_confirmed():
    node = _FakeSupervisorNode()
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.hardware_fault is True


def test_hardware_fault_false_when_connected():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_connection_state(node, String(data="connected"))
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.hardware_fault is False


def test_hardware_fault_true_when_disconnected():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_connection_state(node, String(data="disconnected"))
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.hardware_fault is True


def test_hardware_fault_true_on_error_state():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_connection_state(node, String(data="error:timeout"))
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.hardware_fault is True


def test_hardware_fault_becomes_true_again_when_connection_state_goes_stale():
    node = _all_clear(_FakeSupervisorNode(now=1000.0))
    SupervisorNode._on_connection_state(node, String(data="connected"))
    inputs_fresh = SupervisorNode._build_safety_inputs(node)
    assert inputs_fresh.hardware_fault is False

    node._t = 1000.0 + 10.0
    inputs_stale = SupervisorNode._build_safety_inputs(node)
    assert inputs_stale.hardware_fault is True


# ---- Ladekabelstatus: unbekannt blockiert (bleibt auf sicherem Default) ----

def test_unknown_charging_cable_status_blocks_motion():
    node = _all_clear(_FakeSupervisorNode())  # kein _on_charging_cable_connected() je aufgerufen
    inputs = SupervisorNode._build_safety_inputs(node)
    result = node.safety_gate.evaluate(inputs)
    assert result["allow_motion"] is False
    assert "charging_cable_connected" in result["reason"]


def test_charging_state_does_not_affect_charging_cable_connected():
    """Auftrag Abschnitt 6: 'laedt nicht' != 'Kabel getrennt'."""
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_charging_state(node, Bool(data=False))
    inputs = SupervisorNode._build_safety_inputs(node)
    assert inputs.charging_cable_connected is True  # unveraendert


# ---- Obstacle-Data: kein Latch mehr (True -> False wird uebernommen) ----

def test_obstacle_data_true_to_false_transition_takes_effect():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_obstacle_data_valid(node, Bool(data=True))
    assert SupervisorNode._build_safety_inputs(node).obstacle_data_valid is True
    SupervisorNode._on_obstacle_data_valid(node, Bool(data=False))
    assert SupervisorNode._build_safety_inputs(node).obstacle_data_valid is False


# ---- Bumper blockiert weiterhin sofort ----

def test_bumper_active_triggers_safety_event_and_blocks():
    node = _all_clear(_FakeSupervisorNode())
    SupervisorNode._on_bumper(node, Bool(data=True))
    assert node.state_machine.state == InteractionState.SAFE_STOP
    inputs = SupervisorNode._build_safety_inputs(node)
    result = node.safety_gate.evaluate(inputs)
    assert result["allow_motion"] is False
    assert "bumper_active" in result["reason"]


# ---- End-to-End: alles frisch + gueltig erlaubt Bewegung ----

def test_all_clear_and_connected_allows_motion():
    node = _all_clear(_FakeSupervisorNode())
    node._last_tracks_t = node._t  # sonst blockiert der unabhaengige Personentrack-Alter-Grund
    SupervisorNode._on_connection_state(node, String(data="connected"))
    SupervisorNode._on_charging_cable_connected(node, Bool(data=False))
    inputs = SupervisorNode._build_safety_inputs(node)
    result = node.safety_gate.evaluate(inputs)
    assert result["allow_motion"] is True
    assert result["reason"] == "ok"
