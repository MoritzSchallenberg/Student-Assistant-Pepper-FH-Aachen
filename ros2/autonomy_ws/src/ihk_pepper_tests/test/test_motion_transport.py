import pytest

from ihk_pepper_bridge.motion_transport import (
    DryRunMotionTransport,
    MockMotionTransport,
    QicliTrajectoryTransport,
    TrajectoryPlan,
    TransportStatus,
)


class FakeClient:
    """Nur die von QicliTrajectoryTransport genutzten Methoden -- kein
    Test hier darf jemals eine echte SSH-/Hardwareaktion ausloesen."""

    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        self.calls.append(("play_trajectory", joint_names, angle_lists, time_lists))
        if self._fail:
            raise RuntimeError("simulierter Abbruch")

    def get_angle(self, joint):
        return 0.2


def _plan(joint_names=("HeadYaw",)):
    return TrajectoryPlan(
        joint_names=list(joint_names),
        angle_lists=[[0.1, 0.2] for _ in joint_names],
        time_lists=[[0.0, 1.0] for _ in joint_names],
        source_gesture_name="test_gesture",
        max_duration_s=1.0,
    )


# ---- MockMotionTransport ----

def test_mock_transport_records_calls_in_order():
    transport = MockMotionTransport()
    plan = _plan()
    transport.prepare(plan, restore_snapshot={"HeadYaw": 0.0})
    transport.start()
    transport.restore()
    assert [c[0] for c in transport.calls] == ["prepare", "start", "restore"]
    assert transport.poll() == TransportStatus.DONE


def test_mock_transport_can_simulate_failure():
    transport = MockMotionTransport(fail_on_start=True)
    transport.prepare(_plan())
    transport.start()
    assert transport.poll() == TransportStatus.FAILED
    assert transport.last_error is not None


# ---- DryRunMotionTransport ----

class _RecordingLog:
    """Testdouble statt echtem logging.Logger -- unabhaengig von
    Root-Logger-/Propagate-Konfiguration des Testlaufs, reine
    Aufzeichnung der formatierten Nachrichten."""

    def __init__(self):
        self.messages = []

    def info(self, fmt, *args):
        self.messages.append(fmt % args if args else fmt)


def test_dry_run_transport_never_touches_hardware():
    log = _RecordingLog()
    transport = DryRunMotionTransport(log=log)
    transport.prepare(_plan())
    transport.start()
    transport.restore()
    transport.cancel()
    assert transport.poll() in (TransportStatus.DONE, TransportStatus.CANCELLED)
    # Es gibt keinerlei Hardware-Client hier -- die einzige Wirkung sind Logs.
    assert any("dry-run" in m for m in log.messages)


# ---- QicliTrajectoryTransport ----

def test_qicli_transport_start_completes_successfully():
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    status = transport.wait(timeout_s=2.0)
    assert status == TransportStatus.DONE
    assert client.calls[0][0] == "play_trajectory"


def test_qicli_transport_failure_is_reported_via_status_and_last_error():
    client = FakeClient(fail=True)
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    status = transport.wait(timeout_s=2.0)
    assert status == TransportStatus.FAILED
    assert isinstance(transport.last_error, RuntimeError)


def test_qicli_transport_restore_is_a_single_call_not_per_joint():
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan(), restore_snapshot={"LShoulderPitch": 0.1, "RShoulderPitch": -0.1})
    transport.start()
    transport.wait(timeout_s=2.0)
    calls_before_restore = len(client.calls)
    transport.restore()
    # GENAU EIN zusaetzlicher play_trajectory()-Aufruf fuer BEIDE Gelenke --
    # nicht zwei Aufrufe (Gelenk fuer Gelenk), das war der urspruengliche
    # Fehler (siehe AP12-Bericht/kinematic_compiler.py-Moduldoku).
    assert len(client.calls) == calls_before_restore + 1
    _, joint_names, angle_lists, time_lists = client.calls[-1]
    assert set(joint_names) == {"LShoulderPitch", "RShoulderPitch"}
    assert all(len(a) == 1 for a in angle_lists)  # ein Zielwinkel je Gelenk


def test_qicli_transport_restore_without_snapshot_is_a_noop():
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan(), restore_snapshot=None)
    transport.restore()
    assert client.calls == []


def test_qicli_transport_cancel_before_start_prevents_hardware_call():
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.cancel()
    transport.start()
    assert client.calls == []
    assert transport.poll() == TransportStatus.CANCELLED


def test_qicli_transport_cancel_after_running_sends_hold_position():
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan(joint_names=["HeadYaw", "HeadPitch"]))
    transport.start()
    transport.wait(timeout_s=2.0)  # laesst den simulierten Transport erst fertig werden
    transport.cancel()
    assert transport.poll() == TransportStatus.CANCELLED
    # Zweiter Aufruf = die Halteposition (aktuelle Ist-Position, kurze Dauer).
    assert client.calls[-1][0] == "play_trajectory"
    _, joint_names, angle_lists, time_lists = client.calls[-1]
    assert all(t == [QicliTrajectoryTransport.CANCEL_HOLD_DURATION_S] for t in time_lists)


def test_qicli_transport_cancel_after_failure_does_not_raise():
    client = FakeClient(fail=True)
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    transport.wait(timeout_s=2.0)
    transport.cancel()  # darf nicht crashen, obwohl der Transport schon FAILED ist
    assert transport.poll() == TransportStatus.FAILED
