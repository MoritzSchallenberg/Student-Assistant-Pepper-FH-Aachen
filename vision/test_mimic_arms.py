"""
Test fuer die Hardwaretest-Sperre in mimic_arms.py (Entwicklungsauftrag
04-B, AP5B, Abschnitt 15): dieses Skript bewegt Peppers Arme ueber rohe
qicli-Shellbefehle, komplett an Motion Guard/Aktuator-Arbiter/
Gestenkatalog vorbei. main() muss VOR jedem rclpy.init()/MimicNode()
abbrechen, wenn PEPPER_WEB_HARDWARE_TEST_ENABLED nicht gesetzt ist --
kein Import von mimic_arms selbst und keine SSH-Verbindung darf dabei
noetig sein.
"""
import importlib.util
import os
import sys

import pytest

_MIMIC_ARMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mimic_arms.py")


def _load_mimic_arms_module():
    spec = importlib.util.spec_from_file_location("mimic_arms_under_test", _MIMIC_ARMS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mimic_arms():
    return _load_mimic_arms_module()


def test_main_exits_before_rclpy_init_when_hardware_test_disabled(mimic_arms, monkeypatch):
    monkeypatch.setattr(mimic_arms._cfg, "WEB_HARDWARE_TEST_ENABLED", False)
    monkeypatch.setattr(sys, "argv", ["mimic_arms.py"])

    rclpy_init_calls = []
    monkeypatch.setattr(mimic_arms.rclpy, "init", lambda *a, **kw: rclpy_init_calls.append(1))

    with pytest.raises(SystemExit) as exc_info:
        mimic_arms.main()

    assert exc_info.value.code == 1
    assert rclpy_init_calls == []  # rclpy.init() NIE erreicht


def test_main_proceeds_to_rclpy_init_when_hardware_test_explicitly_enabled(mimic_arms, monkeypatch):
    # Prueft NUR, dass die Sperre selbst korrekt durchlaesst, wenn sie
    # bewusst aktiviert wurde -- MimicNode() (echte SSH-Verbindung/
    # Kamera-Subscription) wird durch ein Fake ersetzt, damit dieser Test
    # NIE tatsaechlich mit Pepper spricht.
    monkeypatch.setattr(mimic_arms._cfg, "WEB_HARDWARE_TEST_ENABLED", True)
    monkeypatch.setattr(sys, "argv", ["mimic_arms.py"])

    rclpy_init_calls = []
    monkeypatch.setattr(mimic_arms.rclpy, "init", lambda *a, **kw: rclpy_init_calls.append(1))

    class _FakeNode:
        def __init__(self, duration_s, conf):
            pass

    monkeypatch.setattr(mimic_arms, "MimicNode", _FakeNode)

    def _raise_keyboard_interrupt(node):
        raise KeyboardInterrupt()

    monkeypatch.setattr(mimic_arms.rclpy, "spin", _raise_keyboard_interrupt)

    class _FakeNodeWithFinish(_FakeNode):
        def finish(self):
            pass

    monkeypatch.setattr(mimic_arms, "MimicNode", _FakeNodeWithFinish)

    mimic_arms.main()  # darf nicht abbrechen/werfen

    assert rclpy_init_calls == [1]
