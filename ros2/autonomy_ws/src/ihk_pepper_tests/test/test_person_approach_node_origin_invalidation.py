"""
Tests fuer die Ursprungsinvalidierung in person_approach_node.py
(Entwicklungsauftrag 04-B, AP7, Abschnitt 12: "Kartenwechsel und neu
initialisierte Lokalisierung invalidieren gespeicherte Urspruenge").
Gleiches Duck-Typing-Muster wie die anderen person_approach_node-Tests.
"""
import types

from ihk_pepper_navigation.person_approach_node import PersonApproachNode
from ihk_pepper_navigation.origin_session import OriginStore


class _FakeLogger:
    def warn(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass


class _FakeNode:
    _on_safety_state = PersonApproachNode._on_safety_state
    _on_mapping_active = PersonApproachNode._on_mapping_active

    def __init__(self):
        self._origin_store = OriginStore()
        self._mapping_active = False
        self._localization_was_valid = None
        self._safety_state = None

    def get_logger(self):
        return _FakeLogger()


def _safety_state(localization_valid):
    return types.SimpleNamespace(
        allow_motion=True, allow_person_approach=True, localization_valid=localization_valid,
        obstacle_data_valid=True, person_depth_valid=True, charging_cable_connected=False,
        bumper_active=False, emergency_stop=False, reason="",
    )


def _bool_msg(value):
    return types.SimpleNamespace(data=value)


def test_localization_recovering_invalidates_all_origins():
    node = _FakeNode()
    node._origin_store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    node._origin_store.capture("s2", "map", 0.0, 0.0, 0.0, initial_track_id=2)

    node._on_safety_state(_safety_state(localization_valid=False))  # erster Empfang: kein Trigger
    assert len(node._origin_store._origins) == 2

    node._on_safety_state(_safety_state(localization_valid=True))  # False->True: Trigger
    assert len(node._origin_store._origins) == 0


def test_localization_staying_valid_does_not_invalidate():
    node = _FakeNode()
    node._origin_store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)

    node._on_safety_state(_safety_state(localization_valid=True))
    node._on_safety_state(_safety_state(localization_valid=True))
    assert len(node._origin_store._origins) == 1


def test_mapping_starting_invalidates_all_origins():
    node = _FakeNode()
    node._origin_store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)

    node._on_mapping_active(_bool_msg(False))  # kein Trigger
    assert len(node._origin_store._origins) == 1

    node._on_mapping_active(_bool_msg(True))  # False->True: Trigger
    assert len(node._origin_store._origins) == 0
    assert node._mapping_active is True


def test_mapping_staying_inactive_does_not_invalidate():
    node = _FakeNode()
    node._origin_store.capture("s1", "map", 0.0, 0.0, 0.0, initial_track_id=1)
    node._on_mapping_active(_bool_msg(False))
    assert len(node._origin_store._origins) == 1
