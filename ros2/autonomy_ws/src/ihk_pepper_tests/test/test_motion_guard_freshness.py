"""
Entwicklungsauftrag 04-B, AP2/AP3: Tests fuer safety_topics.FreshBool
(reine Logik) und fuer die daraus gebaute Aktualitaets-/Latch-Reparatur
in MotionGuardNode -- true<->false-Wechsel, aktuell->veraltet, Publisher
vorhanden->ausgefallen, sowie der konkret behobene obstacle_data_valid-
Latch-Fehler.

MotionGuardNode-Callbacks werden -- wie bereits bei
test_dialogue_thinking_loop.py etabliert -- als UNGEBUNDENE Methoden
gegen ein leichtgewichtiges Fake-Objekt aufgerufen (kein rclpy.init()
noetig, aber exakt derselbe Code wie im echten Node).
"""
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, String

from ihk_pepper_interaction.motion_guard_node import MotionGuardNode
from ihk_pepper_interaction.safety_topics import FreshBool
from ihk_pepper_interfaces.msg import SafetyState


# ---- FreshBool (reine Logik) ----

def test_freshbool_never_received_is_not_fresh():
    fb = FreshBool(initial_value=False)
    assert fb.is_fresh(now=100.0, max_age_s=2.0) is False


def test_freshbool_fresh_after_update():
    fb = FreshBool(initial_value=False)
    fb.update(True, now=100.0)
    assert fb.is_fresh(now=101.0, max_age_s=2.0) is True


def test_freshbool_becomes_stale_after_max_age():
    fb = FreshBool(initial_value=False)
    fb.update(True, now=100.0)
    assert fb.is_fresh(now=103.0, max_age_s=2.0) is False


def test_freshbool_effective_returns_real_value_when_fresh():
    fb = FreshBool(initial_value=False)
    fb.update(True, now=100.0)
    assert fb.effective(now=100.5, max_age_s=2.0, fail_closed_value=False) is True


def test_freshbool_effective_returns_fail_closed_when_stale():
    fb = FreshBool(initial_value=False)
    fb.update(True, now=100.0)
    assert fb.effective(now=200.0, max_age_s=2.0, fail_closed_value=False) is False


def test_freshbool_effective_returns_fail_closed_when_never_received():
    fb = FreshBool(initial_value=False)
    assert fb.effective(now=100.0, max_age_s=2.0, fail_closed_value=False) is False


def test_freshbool_true_to_false_transition_not_latched():
    """Regressionstest fuer den behobenen Latch-Fehler: ein spaeteres
    False MUSS ein frueheres True tatsaechlich ueberschreiben."""
    fb = FreshBool(initial_value=False)
    fb.update(True, now=100.0)
    assert fb.value is True
    fb.update(False, now=101.0)
    assert fb.value is False
    assert fb.effective(now=101.5, max_age_s=2.0, fail_closed_value=False) is False


def test_freshbool_false_to_true_transition():
    fb = FreshBool(initial_value=False)
    fb.update(False, now=100.0)
    fb.update(True, now=101.0)
    assert fb.effective(now=101.5, max_age_s=2.0, fail_closed_value=False) is True


# ---- MotionGuardNode: echte Callbacks gegen ein Fake-Objekt ----

class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeLogger:
    def info(self, *_a, **_kw):
        pass

    def warn(self, *_a, **_kw):
        pass


class _FakeMotionGuardNode:
    def __init__(self, params, now=1000.0):
        self._params = params
        self._t = now
        self._last_cmd = None
        self._last_cmd_wall_s = None
        self._safety_allow_motion = FreshBool(False)
        self._emergency_stop = FreshBool(True)
        self._realsense_diagnostics_valid = FreshBool(False)
        self._odometry_valid = FreshBool(False)
        self._localization_valid = FreshBool(False)
        self._obstacle_data_valid = FreshBool(False)
        self._head_navigation_pose_valid = FreshBool(False)
        self._bumper_active = FreshBool(True)
        self._gesture_in_progress = FreshBool(True)
        self.cmd_pub = _FakePublisher()
        self.diagnostics_pub = _FakePublisher()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def _now(self):
        return self._t


def _all_clear_params(**overrides):
    base = dict(
        enable_live_motion=True,
        max_cmd_age_s=0.5,
        max_input_age_s=2.0,
    )
    base.update(overrides)
    return base


def _make_all_clear_node(now=1000.0):
    node = _FakeMotionGuardNode(_all_clear_params(), now=now)
    msg = SafetyState()
    msg.allow_motion = True
    msg.emergency_stop = False
    MotionGuardNode._on_safety_state(node, msg)
    for attr, value in [
        ("_realsense_diagnostics_valid", True), ("_odometry_valid", True),
        ("_localization_valid", True), ("_obstacle_data_valid", True),
        ("_head_navigation_pose_valid", True),
    ]:
        getattr(node, attr).update(value, now)
    node._bumper_active.update(False, now)
    node._gesture_in_progress.update(False, now)
    node._last_cmd = Twist()
    node._last_cmd_wall_s = now
    return node


def test_all_clear_allows_command_through():
    node = _make_all_clear_node()
    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] is node._last_cmd
    assert "allow=True" in node.diagnostics_pub.messages[-1].data


def test_obstacle_data_true_to_false_via_safety_state_no_longer_latches():
    """Regressionstest fuer den konkreten AP2-Fund: SafetyState darf
    obstacle_data_valid nicht mehr beeinflussen -- nur das dedizierte
    Thema tut das noch, und ueberschreibt statt zu veroderen."""
    node = _make_all_clear_node()
    # Ein SafetyState mit obstacle_data_valid=True (Feld existiert im
    # msg, wird aber von _on_safety_state() bewusst ignoriert).
    msg = SafetyState()
    msg.allow_motion = True
    msg.emergency_stop = False
    msg.obstacle_data_valid = True
    MotionGuardNode._on_safety_state(node, msg)

    MotionGuardNode._on_obstacle_data_valid(node, Bool(data=False))
    MotionGuardNode._tick(node)

    assert node.cmd_pub.messages[-1] == Twist()  # blockiert
    assert "obstacle_data_invalid" in node.diagnostics_pub.messages[-1].data


def test_gesture_in_progress_true_then_false_stops_then_allows():
    node = _make_all_clear_node()
    MotionGuardNode._on_gesture_in_progress(node, Bool(data=True))
    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] == Twist()
    assert "gesture_in_progress" in node.diagnostics_pub.messages[-1].data

    MotionGuardNode._on_gesture_in_progress(node, Bool(data=False))
    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] is node._last_cmd


def test_stale_localization_blocks_even_if_last_value_was_true():
    node = _make_all_clear_node(now=1000.0)
    node._t = 1000.0 + 10.0  # weit ueber max_input_age_s=2.0
    # Alle ANDEREN Eingaenge auf dem neuen Zeitpunkt frisch halten --
    # isoliert gezielt NUR die Lokalisierung als veraltet, sonst wuerde
    # (korrekterweise) der hoeher priorisierte bumper_active-Grund
    # zuerst greifen und diesen Test verdecken.
    for attr, value in [
        ("_safety_allow_motion", True), ("_emergency_stop", False),
        ("_realsense_diagnostics_valid", True), ("_odometry_valid", True),
        ("_obstacle_data_valid", True), ("_head_navigation_pose_valid", True),
        ("_bumper_active", False), ("_gesture_in_progress", False),
    ]:
        getattr(node, attr).update(value, node._t)
    node._last_cmd_wall_s = node._t

    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] == Twist()
    assert "localization_invalid" in node.diagnostics_pub.messages[-1].data


def test_never_received_bumper_signal_blocks_as_if_pressed():
    node = _FakeMotionGuardNode(_all_clear_params())
    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] == Twist()
    assert "bumper_active" in node.diagnostics_pub.messages[-1].data


def test_publisher_present_then_gone_transitions_to_blocking():
    """'Publisher vorhanden -> Publisher ausgefallen': ein Eingang war
    frisch und gueltig, dann kommen einfach keine Nachrichten mehr --
    nach max_input_age_s muss das exakt wie ein fehlender Publisher
    behandelt werden (blockierend), nicht wie ein weiterhin gueltiger
    letzter Wert."""
    node = _make_all_clear_node(now=1000.0)
    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] is node._last_cmd  # zunaechst frei

    node._t += 5.0  # Publisher "faellt aus" -- keine weiteren Updates
    MotionGuardNode._tick(node)
    assert node.cmd_pub.messages[-1] == Twist()
