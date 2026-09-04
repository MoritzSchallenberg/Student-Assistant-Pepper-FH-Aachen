import glob
import os

import pytest
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_bridge.kinematic_compiler import KinematicCompiler


def _installed_gesture_dir():
    return os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")


def test_catalog_loads_all_shipped_gestures_without_error():
    catalog = GestureCatalog(_installed_gesture_dir())
    errors = catalog.reload()
    assert errors == []
    names = catalog.names()
    assert "wave_right" in names
    assert "wave_left" in names
    assert "t_pose" in names


def test_get_unknown_gesture_raises_keyerror():
    catalog = GestureCatalog(_installed_gesture_dir())
    catalog.reload()
    try:
        catalog.get("does_not_exist")
        assert False, "sollte KeyError werfen"
    except KeyError:
        pass


# ---- Entwicklungsauftrag 3, AP13: Kataloggroesse/Kinematik-Regression ----

def test_catalog_has_at_least_fifteen_gestures():
    # Auftrag verlangt mindestens 15 Kataloggesten (8 bestehend + 12 neu
    # aus AP13 = 20, deutlich darueber).
    catalog = GestureCatalog(_installed_gesture_dir())
    catalog.reload()
    assert len(catalog.names()) >= 15


def test_no_gesture_references_the_invalid_speaking_state():
    # SPEAKING ist KEIN gueltiger InteractionState-Wert (nur in
    # DialogueState.msg, komplett getrennt von interaction_state.py) --
    # bestaetigter Bug aus der AP3-Planung, in AP13 behoben.
    for path in glob.glob(os.path.join(_installed_gesture_dir(), "*.yaml")):
        with open(path) as f:
            assert "SPEAKING" not in f.read(), f"{path} referenziert weiterhin SPEAKING"


def _all_v2_gesture_names():
    catalog = GestureCatalog(_installed_gesture_dir())
    catalog.reload()
    return [n for n in catalog.names() if catalog.get(n).schema_version == 2]


@pytest.mark.parametrize("name", _all_v2_gesture_names())
def test_every_v2_gesture_compiles_without_error(name):
    catalog = GestureCatalog(_installed_gesture_dir())
    catalog.reload()
    gesture = catalog.get(name)
    plan = KinematicCompiler().compile(gesture, speed_scale=gesture.speed_scale_default)
    assert plan.joint_names  # mindestens ein Gelenk betroffen
    assert all(len(times) == len(plan.time_lists[0]) for times in plan.time_lists)
