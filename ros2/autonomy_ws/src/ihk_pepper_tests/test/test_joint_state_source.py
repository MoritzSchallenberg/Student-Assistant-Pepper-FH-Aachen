"""
Tests fuer joint_state_source.py (Entwicklungsauftrag 04-B, AP8.7,
Commit 12/14): rein lesende Gelenkzustands-Abstraktion.
"""
from ihk_pepper_bridge.joint_state_source import JointStateReading, PepperJointStateSource


class _FakeMovementCapableClient:
    """Simuliert einen vollen Pepper-Client mit Bewegungsmethoden --
    beweist, dass PepperJointStateSource NUR get_angle erreichen kann,
    selbst wenn der zugrunde liegende Client viel mehr koennte."""

    def __init__(self):
        self.get_angle_calls = []
        self._angles = {"HeadYaw": 0.1, "HeadPitch": -0.05}

    def get_angle(self, joint):
        self.get_angle_calls.append(joint)
        return self._angles.get(joint)

    def set_angle(self, *a, **kw):
        raise AssertionError("set_angle darf von PepperJointStateSource NIE aufgerufen werden.")

    def play_trajectory(self, *a, **kw):
        raise AssertionError("play_trajectory darf von PepperJointStateSource NIE aufgerufen werden.")

    def restore_joints(self, *a, **kw):
        raise AssertionError("restore_joints darf von PepperJointStateSource NIE aufgerufen werden.")

    def set_breathing(self, *a, **kw):
        raise AssertionError("set_breathing darf von PepperJointStateSource NIE aufgerufen werden.")

    def stop_motion(self, *a, **kw):
        raise AssertionError("stop_motion darf von PepperJointStateSource NIE aufgerufen werden.")


def test_read_returns_values_for_all_requested_joints():
    client = _FakeMovementCapableClient()
    source = PepperJointStateSource(client.get_angle)
    reading = source.read(["HeadYaw", "HeadPitch"])
    assert reading.values == {"HeadYaw": 0.1, "HeadPitch": -0.05}


def test_read_is_labeled_sequential_per_joint_and_qicli_ssh_backend():
    client = _FakeMovementCapableClient()
    source = PepperJointStateSource(client.get_angle)
    reading = source.read(["HeadYaw", "HeadPitch"])
    assert reading.acquisition_mode == "sequential_per_joint"
    assert reading.source_backend == "qicli_ssh"


def test_read_calls_get_angle_once_per_joint_in_requested_order():
    client = _FakeMovementCapableClient()
    source = PepperJointStateSource(client.get_angle)
    source.read(["HeadPitch", "HeadYaw"])
    assert client.get_angle_calls == ["HeadPitch", "HeadYaw"]


def test_read_never_reaches_a_movement_method():
    # PepperJointStateSource haelt NUR die get_angle-Funktion, nicht das
    # Client-Objekt selbst -- ein struktureller Beweis, nicht nur ein
    # Verhaltenstest: es gibt schlicht kein Attribut, ueber das
    # set_angle/play_trajectory/restore_joints/set_breathing/
    # stop_motion erreichbar waeren.
    client = _FakeMovementCapableClient()
    source = PepperJointStateSource(client.get_angle)
    assert not hasattr(source, "set_angle")
    assert not hasattr(source, "play_trajectory")
    assert not hasattr(source, "restore_joints")
    assert not hasattr(source, "set_breathing")
    assert not hasattr(source, "stop_motion")
    # Trotzdem tatsaechlich ausgefuehrt (nicht nur Quelltext durchsucht):
    source.read(["HeadYaw"])  # darf keine AssertionError ausloesen.


def test_acquisition_span_reflects_the_difference_between_start_and_finish():
    reading = JointStateReading(
        values={"HeadYaw": 0.0}, acquisition_started_monotonic_s=10.0,
        acquisition_finished_monotonic_s=10.25, source_backend="qicli_ssh",
        acquisition_mode="sequential_per_joint",
    )
    assert reading.acquisition_span_s == 0.25


def test_read_returns_none_for_a_joint_the_client_could_not_resolve():
    client = _FakeMovementCapableClient()
    source = PepperJointStateSource(client.get_angle)
    reading = source.read(["HeadYaw", "LShoulderPitch"])
    assert reading.values["LShoulderPitch"] is None
