"""
Tests fuer den neuen /joint_states-Publisher in bridge_node.py
(Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6): robot_state_publisher
(siehe pepper_robot_state.launch.py) braucht /joint_states, um die
dynamische Kette base_link->torso->Neck->Head zu berechnen --
camera_pose_gate_node.py/head_pose_gate.py haben /joint_states bereits
seit Auftrag 1 konsumiert (fail-closed bei fehlend/veraltet), aber VOR
AP6.1 hat es in autonomy_ws nie einen tatsaechlichen Publisher dafuer
gegeben. Gleiches Duck-Typing-Muster wie
test_bridge_node_set_head_pose.py -- die ECHTE, ungebundene Methode von
PepperBridgeNode laeuft gegen ein leichtgewichtiges Fake, kein
rclpy.init() noetig.
"""
from ihk_pepper_bridge.bridge_node import PepperBridgeNode


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


class _FakePepperClient:
    def __init__(self, angles=None, raise_on_get_angle=False):
        self._angles = angles or {}
        self._raise = raise_on_get_angle

    def get_angle(self, joint):
        if self._raise:
            raise RuntimeError("qicli kaputt")
        return self._angles.get(joint)


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(msg)


class _FakeNode:
    _publish_joint_states = PepperBridgeNode._publish_joint_states

    def __init__(self, angles=None, raise_on_get_angle=False):
        self.pepper = _FakePepperClient(angles=angles, raise_on_get_angle=raise_on_get_angle)
        self.joint_states_pub = _FakePublisher()

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock()


def test_publishes_head_yaw_and_pitch_when_reachable():
    node = _FakeNode(angles={"HeadYaw": 0.3, "HeadPitch": -0.2})
    node._publish_joint_states(reachable=True)
    assert len(node.joint_states_pub.published) == 1
    msg = node.joint_states_pub.published[0]
    assert msg.name == ["HeadYaw", "HeadPitch"]
    assert list(msg.position) == [0.3, -0.2]


def test_publishes_nothing_when_pepper_unreachable():
    node = _FakeNode(angles={"HeadYaw": 0.3, "HeadPitch": -0.2})
    node._publish_joint_states(reachable=False)
    assert node.joint_states_pub.published == []


def test_publishes_nothing_when_get_angle_raises():
    node = _FakeNode(raise_on_get_angle=True)
    node._publish_joint_states(reachable=True)
    assert node.joint_states_pub.published == []


def test_publishes_nothing_when_yaw_missing():
    node = _FakeNode(angles={"HeadPitch": -0.2})
    node._publish_joint_states(reachable=True)
    assert node.joint_states_pub.published == []


def test_publishes_nothing_when_pitch_missing():
    node = _FakeNode(angles={"HeadYaw": 0.3})
    node._publish_joint_states(reachable=True)
    assert node.joint_states_pub.published == []
