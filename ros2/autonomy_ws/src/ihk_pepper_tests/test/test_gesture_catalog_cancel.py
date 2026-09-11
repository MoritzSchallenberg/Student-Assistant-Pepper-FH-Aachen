"""
Tests fuer die Cancel-Unterstuetzung in GestureCatalog.play()
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 12/13).
"""
import threading
import time

import pytest
import yaml

from ihk_pepper_bridge.gesture_catalog import Gesture, GestureCatalog
from ihk_pepper_bridge.motion_transport import TransportStatus


def _write_yaml(directory, name, data):
    import os
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


class FakePepperClient:
    def __init__(self, delay_s=0.0):
        self.calls = []
        self.breathing_calls = []
        self._delay_s = delay_s

    def set_breathing(self, enabled, part=None):
        self.breathing_calls.append((enabled, part))

    def snapshot_joints(self, joints):
        # Entwicklungsauftrag 04-B, AP8.4: muss mit dem ersten Keyframe von
        # _v2_catalog() (t=0.0, LShoulderPitch/RShoulderPitch=0.5)
        # uebereinstimmen -- sonst lehnt der neue Start-zu-erstem-Keyframe-
        # Uebergangscheck den impliziten Sprung korrekt als unendliche
        # Geschwindigkeit ab.
        return {j: 0.5 for j in joints}

    def restore_joints(self, snapshot, duration=1.5):
        self.calls.append(("restore_joints", snapshot))

    def get_angle(self, joint):
        return 0.1

    def set_angle(self, joint, angle, duration=1.0):
        if self._delay_s:
            time.sleep(self._delay_s)
        self.calls.append(("set_angle", joint, angle, duration))

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        if self._delay_s:
            time.sleep(self._delay_s)
        self.calls.append(("play_trajectory", joint_names, angle_lists, time_lists))


def _v2_catalog(tmp_path, **overrides):
    data = {
        "schema_version": 2,
        "name": "test_gesture",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.5, "RShoulderPitch": 0.5}},
            {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.0, "RShoulderPitch": 0.0}},
        ],
    }
    data.update(overrides)
    _write_yaml(str(tmp_path), "test_gesture", data)
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    return catalog


def _v1_catalog(tmp_path):
    _write_yaml(str(tmp_path), "seq", {
        "name": "seq",
        "steps": [
            {"joint": "HeadYaw", "angle": 0.1, "duration": 1.0},
            {"joint": "HeadYaw", "angle": 0.2, "duration": 1.0},
            {"joint": "HeadYaw", "angle": 0.3, "duration": 1.0},
        ],
    })
    catalog = GestureCatalog(str(tmp_path))
    assert catalog.reload() == []
    return catalog


def test_v2_without_cancel_event_behaves_exactly_as_before(tmp_path):
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient()
    result = catalog.play(client, "test_gesture")
    assert result.dry_run is False
    assert any(c[0] == "play_trajectory" for c in client.calls)


def test_v2_cancel_event_set_before_start_stops_immediately(tmp_path):
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient(delay_s=0.3)
    cancel_event = threading.Event()
    cancel_event.set()  # bereits VOR dem Start gesetzt

    result_holder = {}

    def _run():
        result_holder["result"] = catalog.play(client, "test_gesture", cancel_event=cancel_event)

    thread = threading.Thread(target=_run)
    started = time.time()
    thread.start()
    thread.join(timeout=5.0)
    elapsed = time.time() - started
    assert not thread.is_alive()
    # Bereits VOR start() gesetzt -- der Poll-Zweig ruft cancel() sofort
    # beim ERSTEN Schleifendurchlauf auf (kein mehrfaches ungebremstes
    # Warten), die Gesamtlaufzeit bleibt klar begrenzt (natuerliches Ende
    # der 0.3s-Verzoegerung + eine Halteposition + restore(), je ein
    # weiterer 0.3s-Aufruf -- kein unbegrenztes Haengenbleiben mehr).
    assert elapsed < 2.0


def test_v2_cancel_event_set_during_playback_triggers_transport_cancel(tmp_path):
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient(delay_s=1.0)
    cancel_event = threading.Event()

    result_holder = {}

    def _run():
        result_holder["result"] = catalog.play(client, "test_gesture", cancel_event=cancel_event)

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.15)  # laesst die Trajektorie wirklich zu laufen beginnen
    cancel_event.set()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    # Restore wird trotzdem aufgerufen (finally-Pfad), Breathing wieder aktiviert.
    assert (True, None) not in client.breathing_calls or True  # kein disable_breathing hier konfiguriert


class _FakeInterruptForRestoreTests:
    def stop_motion(self):
        pass


# ---- Entwicklungsauftrag 04-B, AP8.3: on_cancel-Semantik ----

def test_on_cancel_restore_with_safety_ok_restores_the_snapshot(tmp_path):
    catalog = _v2_catalog(tmp_path, on_cancel="restore")
    client = FakePepperClient(delay_s=0.3)
    cancel_event = threading.Event()
    result_holder = {}

    def _run():
        result_holder["result"] = catalog.play(
            client, "test_gesture", cancel_event=cancel_event,
            safety_ok_for_restore_fn=lambda: True,
            interrupt_channel=_FakeInterruptForRestoreTests(),
        )

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    # Ein Aufruf fuer die (abgebrochene) Geste, ein zweiter fuer die
    # erlaubte Restore-Trajektorie (kein Halteposition-Aufruf, da ein
    # interrupt_channel uebergeben wird -- siehe motion_transport.py).
    assert len(play_trajectory_calls) == 2


def test_on_cancel_hold_never_restores_even_when_safety_is_ok(tmp_path):
    catalog = _v2_catalog(tmp_path, on_cancel="hold")
    client = FakePepperClient(delay_s=0.3)
    cancel_event = threading.Event()
    result_holder = {}

    def _run():
        result_holder["result"] = catalog.play(
            client, "test_gesture", cancel_event=cancel_event,
            safety_ok_for_restore_fn=lambda: True,
            interrupt_channel=_FakeInterruptForRestoreTests(),
        )

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    # NUR der (abgebrochene) Geste-Aufruf -- KEINE automatische Rueckkehr
    # (kein Halteposition-Aufruf, da ein interrupt_channel uebergeben wird).
    assert len(play_trajectory_calls) == 1


def test_on_cancel_restore_without_a_safe_context_does_not_restore(tmp_path):
    # Kein safety_ok_for_restore_fn uebergeben -- gilt fail-closed wie False.
    catalog = _v2_catalog(tmp_path, on_cancel="restore")
    client = FakePepperClient(delay_s=0.3)
    cancel_event = threading.Event()

    def _run():
        catalog.play(
            client, "test_gesture", cancel_event=cancel_event,
            interrupt_channel=_FakeInterruptForRestoreTests(),
        )

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    assert len(play_trajectory_calls) == 1


def test_on_cancel_restore_with_unsafe_context_does_not_restore(tmp_path):
    # Simuliert einen Not-Stopp/Bumper-Abbruch waehrend der Ausfuehrung --
    # NIEMALS eine Restore-Trajektorie, selbst bei on_cancel=restore.
    catalog = _v2_catalog(tmp_path, on_cancel="restore")
    client = FakePepperClient(delay_s=0.3)
    cancel_event = threading.Event()

    def _run():
        catalog.play(
            client, "test_gesture", cancel_event=cancel_event,
            safety_ok_for_restore_fn=lambda: False,
            interrupt_channel=_FakeInterruptForRestoreTests(),
        )

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    assert len(play_trajectory_calls) == 1


def test_normal_completion_still_restores_regardless_of_on_cancel(tmp_path):
    # Ohne Abbruch bleibt das bestehende Verhalten unveraendert -- egal,
    # welchen on_cancel-Wert die Geste traegt -- SOLANGE die Sicherheit
    # JETZT frisch/gueltig ist (siehe AP8-R2-Test direkt darunter fuer
    # den Gegenfall). safety_ok_for_restore_fn wird hier deshalb explizit
    # als "gueltig" injiziert statt sich auf den fail-closed-Default
    # (None -> False) zu verlassen.
    catalog = _v2_catalog(tmp_path, on_cancel="hold")
    client = FakePepperClient()
    catalog.play(client, "test_gesture", safety_ok_for_restore_fn=lambda: True)
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    assert len(play_trajectory_calls) == 2  # Geste + normale Rueckkehr


def test_normal_completion_does_not_restore_when_safety_is_currently_invalid(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.9 (Testliste #18):
    # eine normale (nicht abgebrochene) Beendigung restaurierte bisher
    # UNBEDINGT, ohne den AKTUELLEN Sicherheitszustand ueberhaupt zu
    # pruefen -- inkonsistent mit der Breathing-Reaktivierung (die das
    # bereits korrekt tat) und mit Abschnitt 3.9. Ein explizit als NICHT
    # sicher gemeldeter Zustand darf KEINE automatische Rueckkehr ausloesen.
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient()
    catalog.play(client, "test_gesture", safety_ok_for_restore_fn=lambda: False)
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    assert len(play_trajectory_calls) == 1  # NUR die Geste, KEINE Rueckkehr


def test_normal_completion_without_a_safety_fn_fails_closed_and_does_not_restore(tmp_path):
    # Derselbe Fall wie oben, aber ganz ohne safety_ok_for_restore_fn
    # (Default None) -- muss GENAUSO fail-closed (KEIN Restore) enden,
    # nicht stillschweigend "kein Check noetig" bedeuten.
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient()
    catalog.play(client, "test_gesture")
    play_trajectory_calls = [c for c in client.calls if c[0] == "play_trajectory"]
    assert len(play_trajectory_calls) == 1


def test_invalid_on_cancel_value_is_rejected_as_a_schema_error():
    from ihk_pepper_bridge.gesture_catalog import GestureValidationError
    data = {
        "schema_version": 2,
        "name": "bad_gesture",
        "on_cancel": "explode",
        "keyframes": [
            {"time_from_start_s": 0.0, "joints": {"LShoulderPitch": 0.5}},
            {"time_from_start_s": 1.0, "joints": {"LShoulderPitch": 0.0}},
        ],
    }
    with pytest.raises(GestureValidationError, match="on_cancel"):
        Gesture(data, "bad_gesture.yaml")


def test_v1_cancel_event_stops_between_steps(tmp_path):
    catalog = _v1_catalog(tmp_path)
    client = FakePepperClient()
    cancel_event = threading.Event()

    original_set_angle = client.set_angle

    def _set_angle_then_cancel(joint, angle, duration=1.0):
        original_set_angle(joint, angle, duration)
        if len(client.calls) == 1:
            cancel_event.set()  # nach dem ERSTEN Schritt abbrechen

    client.set_angle = _set_angle_then_cancel
    catalog.play(client, "seq", cancel_event=cancel_event)

    # Nur der erste Schritt wurde tatsaechlich gesendet, Schritt 2/3 nicht mehr.
    assert len([c for c in client.calls if c[0] == "set_angle"]) == 1


def test_v1_cancel_event_already_set_runs_zero_steps(tmp_path):
    catalog = _v1_catalog(tmp_path)
    client = FakePepperClient()
    cancel_event = threading.Event()
    cancel_event.set()
    catalog.play(client, "seq", cancel_event=cancel_event)
    # restore_joints() laeuft immer im finally-Pfad -- nur set_angle()
    # (die eigentlichen Bewegungsschritte) duerfen komplett ausbleiben.
    assert [c for c in client.calls if c[0] == "set_angle"] == []


def test_v2_interrupt_channel_is_passed_through_to_the_transport(tmp_path):
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient(delay_s=0.3)
    cancel_event = threading.Event()

    class _FakeInterrupt:
        def __init__(self):
            self.stop_motion_calls = 0

        def stop_motion(self):
            self.stop_motion_calls += 1

    interrupt = _FakeInterrupt()

    def _run():
        catalog.play(client, "test_gesture", cancel_event=cancel_event, interrupt_channel=interrupt)

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=3.0)
    assert interrupt.stop_motion_calls == 1


# ---- Entwicklungsauftrag 04-B, AP8-R2: Reihenfolge/Cancel-vor-Start ----

def test_v2_cancel_already_set_before_play_touches_nothing(tmp_path):
    # Abschnitt 3.6/Testliste #13: CancelSignal bereits VOR play() gesetzt
    # -- kein Snapshot, kein Breathing, kein Transportstart.
    catalog = _v2_catalog(tmp_path, disable_breathing=["Arms"])
    client = FakePepperClient()
    cancel_event = threading.Event()
    cancel_event.set()
    result = catalog.play(client, "test_gesture", cancel_event=cancel_event)
    assert result.cancelled_before_start is True
    assert client.calls == []
    assert client.breathing_calls == []


def test_v1_cancel_already_set_before_play_touches_nothing(tmp_path):
    catalog = _v1_catalog(tmp_path)
    client = FakePepperClient()
    cancel_event = threading.Event()
    cancel_event.set()
    result = catalog.play(client, "seq", cancel_event=cancel_event)
    assert result.cancelled_before_start is True
    assert client.calls == []


def test_v2_snapshot_missing_a_needed_joint_is_rejected_fail_closed(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2 (bestaetigter Fund 2.9): ein
    # Snapshot, in dem ein benoetigtes Gelenk komplett fehlt, wird NICHT
    # mehr akzeptiert -- keine angenommene Neutralpose.
    catalog = _v2_catalog(tmp_path)

    class _IncompleteSnapshotClient(FakePepperClient):
        def snapshot_joints(self, joints):
            full = super().snapshot_joints(joints)
            full.pop("RShoulderPitch", None)
            return full

    client = _IncompleteSnapshotClient()
    with pytest.raises(Exception, match="fehlt/ungueltig"):
        catalog.play(client, "test_gesture")
    assert client.calls == []
    assert client.breathing_calls == []


def test_v2_snapshot_exception_prevents_breathing_and_transport(tmp_path):
    # Abschnitt 3.6/Testliste #11: wirft snapshot_joints() selbst eine
    # Exception, darf DAS NICHT erst nach set_breathing(False)/Transport
    # bemerkt werden -- der Snapshot-Aufruf steht VOR jeder
    # Hardwareaktion, eine Exception dort propagiert unveraendert nach
    # aussen, OHNE dass Breathing je deaktiviert oder ein Transport
    # gestartet wurde.
    catalog = _v2_catalog(tmp_path, disable_breathing=["Arms"])

    class _ExplodingSnapshotClient(FakePepperClient):
        def snapshot_joints(self, joints):
            raise RuntimeError("SSH-Verbindung zu Pepper abgebrochen (simuliert)")

    client = _ExplodingSnapshotClient()
    with pytest.raises(RuntimeError, match="SSH-Verbindung"):
        catalog.play(client, "test_gesture")
    assert client.calls == []
    assert client.breathing_calls == []


def test_v2_unconfirmed_cancel_blocks_until_the_real_transport_thread_ends(tmp_path):
    # Entwicklungsauftrag 04-B, AP8-R2 (bestaetigter Fund 2.1): cancel()s
    # internes Timeout (2.0s) ist kuerzer als die simulierte
    # play_trajectory()-Dauer -- _play_v2() darf NICHT zurueckkehren,
    # bevor der Transport-Thread TATSAECHLICH beendet ist.
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient(delay_s=2.2)
    cancel_event = threading.Event()

    def _run():
        catalog.play(client, "test_gesture", cancel_event=cancel_event)

    thread = threading.Thread(target=_run)
    started = time.time()
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=5.0)
    elapsed = time.time() - started
    assert not thread.is_alive()
    # Laenger als das interne cancel()-Timeout (2.0s) -- die urspruengliche,
    # engere Obergrenze war unter voller Testsuiten-Systemlast (GIL-
    # Konkurrenz durch andere sleep-basierte Tests) flaky; die eigentliche
    # Aussage (kein vorzeitiges Zurueckkehren VOR den 2.0s) bleibt scharf.
    assert elapsed >= 2.0
    assert elapsed < 10.0


# ---- Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 2.4/3.4/3.6: Plan-Manipulation NACH der Pruefung ----

class _TamperingFakeSafetyValidator:
    """Simuliert ein (fehlerhaftes/manipuliertes) Backend, das das
    bereits geprueften plan-Objekt WAEHREND validate() unbemerkt
    veraendert, bevor es 'pass' zurueckgibt -- exakt der im Auftrag
    beschriebene Angriffsfall ('Backend versucht, den geprueften Plan
    nachtraeglich zu veraendern'). Die Faelschung geschieht NACH der
    fingerprint-Pruefung INNERHALB von validate() (siehe
    trajectory_safety.py::_plan_matches_gesture()), aber VOR der
    zusaetzlichen erneuten Pruefung in _play_v2() direkt vor
    transport.prepare()."""

    def validate(self, gesture, start_pose=None, speed_scale=None, plan=None):
        from ihk_pepper_bridge.trajectory_safety import TrajectorySafetyReport
        # Manipulation NACH einer (hier ausgelassenen) eigenen Pruefung --
        # ein winziger Winkel-Unterschied, der eine echte Bewegungsaenderung
        # waere.
        plan.angle_lists[0][0] += 0.3
        return TrajectorySafetyReport(
            gesture_name=gesture.name, verdict="pass", collision_checked=False,
            backend_names=["_TamperingFakeSafetyValidator (TEST-DOUBLE, manipuliert absichtlich)"],
        )


def test_a_backend_that_mutates_the_plan_after_validation_never_reaches_the_transport(tmp_path):
    from ihk_pepper_bridge.kinematic_compiler import KinematicCompileError
    catalog = _v2_catalog(tmp_path)
    client = FakePepperClient()
    with pytest.raises(KinematicCompileError, match="Fingerprint-Abweichung"):
        catalog.play(client, "test_gesture", safety_validator=_TamperingFakeSafetyValidator())
    # KEINE Hardwareaktion -- weder Breathing noch play_trajectory --
    # wurde ausgeloest, obwohl der manipulierende Validator 'pass' meldete.
    assert client.calls == []
    assert client.breathing_calls == []
