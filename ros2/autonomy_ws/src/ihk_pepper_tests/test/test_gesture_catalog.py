import os

from ament_index_python.packages import get_package_share_directory

from ihk_pepper_bridge.gesture_catalog import GestureCatalog


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
