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

    def __init__(self, fail=False, delay_s=0.0):
        self.calls = []
        self._fail = fail
        self._delay_s = delay_s

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        if self._delay_s:
            import time
            time.sleep(self._delay_s)
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


def test_qicli_transport_cancel_while_genuinely_still_running_sends_hold_position():
    # delay_s simuliert eine noch laufende synchrone SSH-Anfrage -- cancel()
    # wird aufgerufen, WAEHREND play_trajectory() noch blockiert (kein
    # .wait() davor), genau der Fall, den Entwicklungsauftrag 04-B, AP5B
    # (Abschnitt 2.2/10) beheben sollte: cancel() darf nicht unbegrenzt
    # blockieren, muss aber trotzdem (ohne interrupt_channel, altes
    # Fallback-Verhalten) danach noch eine Halteposition senden.
    client = FakeClient(delay_s=0.2)
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan(joint_names=["HeadYaw", "HeadPitch"]))
    transport.start()
    result = transport.cancel(timeout_s=2.0)
    assert result.cancel_confirmed is True
    assert transport.poll() == TransportStatus.CANCELLED
    # Zweiter Aufruf = die Halteposition (aktuelle Ist-Position, kurze Dauer).
    assert client.calls[-1][0] == "play_trajectory"
    _, joint_names, angle_lists, time_lists = client.calls[-1]
    assert all(t == [QicliTrajectoryTransport.CANCEL_HOLD_DURATION_S] for t in time_lists)


def test_qicli_transport_cancel_after_natural_completion_is_a_noop():
    # Bereits VOR cancel() natuerlich fertig (DONE) -- cancel() darf das
    # nicht rueckwirkend zu "CANCELLED" umdeuten und keine zusaetzliche
    # Halteposition mehr senden (das Ziel wurde bereits erreicht).
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan(joint_names=["HeadYaw", "HeadPitch"]))
    transport.start()
    transport.wait(timeout_s=2.0)
    calls_before_cancel = len(client.calls)
    result = transport.cancel()
    assert result.cancel_confirmed is True
    assert result.final_transport_state == TransportStatus.DONE
    assert transport.poll() == TransportStatus.DONE
    assert len(client.calls) == calls_before_cancel  # keine zusaetzliche Halteposition


def test_qicli_transport_cancel_times_out_when_request_still_running():
    # delay_s > timeout_s: cancel() MUSS trotzdem rechtzeitig zurueckkehren
    # (kein unbegrenztes Blockieren mehr) und das ehrlich als nicht
    # bestaetigt melden.
    client = FakeClient(delay_s=1.0)
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    import time
    started = time.monotonic()
    result = transport.cancel(timeout_s=0.1)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0  # kehrt VOR dem Ende der 1.0s-Verzoegerung zurueck
    assert result.cancel_confirmed is False
    assert result.cancel_requested is True


def test_qicli_transport_cancel_after_failure_does_not_raise():
    client = FakeClient(fail=True)
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    transport.wait(timeout_s=2.0)
    result = transport.cancel()  # darf nicht crashen, obwohl der Transport schon FAILED ist
    assert result.cancel_confirmed is True
    # Bereits VOR cancel() gescheitert (done_event schon gesetzt) -- cancel()
    # deutet das nicht rueckwirkend als "cancelled" um, das waere unehrlich.
    assert transport.poll() == TransportStatus.FAILED
    assert result.final_transport_state == TransportStatus.FAILED


# ---- interrupt_channel: unabhaengiger Kanal (Auftrag Abschnitt 2.3/10) ----

class _FakeInterruptChannel:
    def __init__(self, fail=False):
        self.stop_motion_calls = 0
        self._fail = fail

    def stop_motion(self):
        self.stop_motion_calls += 1
        if self._fail:
            raise RuntimeError("Interrupt-Kanal nicht erreichbar")
        return True


def test_cancel_uses_interrupt_channel_immediately_not_the_main_channel_lock():
    client = FakeClient(delay_s=0.3)
    interrupt = _FakeInterruptChannel()
    transport = QicliTrajectoryTransport(client, interrupt_channel=interrupt)
    transport.prepare(_plan())
    transport.start()
    result = transport.cancel(timeout_s=2.0)
    assert interrupt.stop_motion_calls == 1
    assert result.cancel_confirmed is True
    # Mit interrupt_channel wird KEINE zusaetzliche Halteposition mehr
    # ueber den Hauptkanal gesendet (nur der urspruengliche Aufruf).
    assert len([c for c in client.calls if c[0] == "play_trajectory"]) == 1


def test_cancel_reports_honestly_when_interrupt_channel_itself_fails():
    client = FakeClient(delay_s=0.3)
    interrupt = _FakeInterruptChannel(fail=True)
    transport = QicliTrajectoryTransport(client, interrupt_channel=interrupt)
    transport.prepare(_plan())
    transport.start()
    result = transport.cancel(timeout_s=2.0)
    assert result.cancel_confirmed is True  # die urspruengliche Anfrage ist trotzdem fertig geworden
    assert "Interrupt" in result.error_message or result.error_message != ""


def test_cancel_with_interrupt_channel_still_times_out_correctly():
    client = FakeClient(delay_s=1.0)
    interrupt = _FakeInterruptChannel()
    transport = QicliTrajectoryTransport(client, interrupt_channel=interrupt)
    transport.prepare(_plan())
    transport.start()
    result = transport.cancel(timeout_s=0.1)
    assert interrupt.stop_motion_calls == 1  # trotzdem sofort versucht
    assert result.cancel_confirmed is False


# ---- Entwicklungsauftrag 04-B, AP8-R2 (bestaetigter Fund 2.9) ----

class _FailingReturnClient:
    """play_trajectory() gibt explizit False zurueck, OHNE eine
    Exception zu werfen -- muss trotzdem als Fehlschlag gewertet
    werden."""

    def __init__(self):
        self.calls = []

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        self.calls.append(("play_trajectory", joint_names, angle_lists, time_lists))
        return False

    def get_angle(self, joint):
        return 0.2


def test_false_return_from_play_trajectory_is_treated_as_failed():
    client = _FailingReturnClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    status = transport.wait(timeout_s=2.0)
    assert status == TransportStatus.FAILED
    assert transport.last_error is not None


def test_none_return_from_play_trajectory_still_counts_as_success():
    # Gegenprobe: die bestehenden Fakes/die reale Implementierung geben
    # meist None zurueck -- das bleibt weiterhin ein Erfolg, NUR ein
    # expliziter False-Rueckgabewert zaehlt als Fehlschlag.
    client = FakeClient()
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    status = transport.wait(timeout_s=2.0)
    assert status == TransportStatus.DONE


class _FakeInterruptChannelReturningFalse:
    def __init__(self):
        self.stop_motion_calls = 0

    def stop_motion(self):
        self.stop_motion_calls += 1
        return False


def test_cancel_does_not_count_a_false_interrupt_return_as_confirmed_send():
    client = FakeClient(delay_s=1.0)
    interrupt = _FakeInterruptChannelReturningFalse()
    transport = QicliTrajectoryTransport(client, interrupt_channel=interrupt)
    transport.prepare(_plan())
    transport.start()
    result = transport.cancel(timeout_s=0.05)
    assert interrupt.stop_motion_calls == 1
    assert "nicht bestaetigt" in result.error_message.lower() or "false" in result.error_message.lower()


# ---- wait_for_terminal() ----

def test_wait_for_terminal_true_for_mock_transport_after_start():
    transport = MockMotionTransport()
    transport.prepare(_plan())
    transport.start()
    assert transport.wait_for_terminal() is True


def test_wait_for_terminal_true_for_dry_run_transport_after_start():
    transport = DryRunMotionTransport()
    transport.prepare(_plan())
    transport.start()
    assert transport.wait_for_terminal() is True


def test_wait_for_terminal_waits_for_the_real_background_thread_not_just_cancel():
    # Entwicklungsauftrag 04-B, AP8-R2 (bestaetigter Fund 2.1): cancel()
    # kann mit cancel_confirmed=False zurueckkehren, waehrend der Thread
    # noch laeuft -- wait_for_terminal() muss trotzdem irgendwann True
    # liefern, SOBALD der Thread tatsaechlich endet (kein separates,
    # unabhaengiges Ereignis).
    client = FakeClient(delay_s=0.3)
    transport = QicliTrajectoryTransport(client)
    transport.prepare(_plan())
    transport.start()
    cancel_result = transport.cancel(timeout_s=0.05)
    assert cancel_result.cancel_confirmed is False
    # Unbegrenztes Warten liefert True, sobald der Thread (nach den
    # verbleibenden ~0.25s) tatsaechlich endet.
    assert transport.wait_for_terminal(timeout_s=2.0) is True
    assert transport.poll() != TransportStatus.RUNNING
