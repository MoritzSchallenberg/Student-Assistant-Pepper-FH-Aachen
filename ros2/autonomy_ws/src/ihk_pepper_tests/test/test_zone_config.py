"""
Voraussetzung: ROS2 + der Workspace-Overlay muessen gesourced sein
(source /opt/ros/jazzy/setup.bash; source install/setup.bash), damit
ihk_pepper_navigation importierbar ist. Aufruf z.B.:
    python3 -m pytest src/ihk_pepper_tests/test/ -v
"""
import os
import tempfile

import pytest

from ihk_pepper_navigation.zone_config import (
    load_zone, load_all_zones, point_in_any_keepout, speed_limit_at,
    ZoneValidationError, Zone,
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return str(p)


def test_load_keepout_zone(tmp_path):
    path = _write(tmp_path, "z.yaml", """
id: z1
type: keepout
polygon: [[0,0],[2,0],[2,2],[0,2]]
""")
    z = load_zone(path)
    assert z.id == "z1"
    assert z.is_hard_keepout()
    assert z.contains_point(1, 1)
    assert not z.contains_point(5, 5)


def test_slow_zone_requires_max_speed(tmp_path):
    path = _write(tmp_path, "z.yaml", """
id: z1
type: slow
polygon: [[0,0],[2,0],[2,2],[0,2]]
""")
    with pytest.raises(ZoneValidationError):
        load_zone(path)


def test_missing_required_fields(tmp_path):
    path = _write(tmp_path, "broken.yaml", "title: nur ein Feld\n")
    with pytest.raises(ZoneValidationError):
        load_zone(path)


def test_invalid_type_rejected(tmp_path):
    path = _write(tmp_path, "z.yaml", """
id: z1
type: not_a_real_type
polygon: [[0,0],[2,0],[2,2],[0,2]]
""")
    with pytest.raises(ZoneValidationError):
        load_zone(path)


def test_load_all_zones_skips_broken_files(tmp_path):
    _write(tmp_path, "good.yaml", "id: good\ntype: keepout\npolygon: [[0,0],[1,0],[1,1]]\n")
    _write(tmp_path, "bad.yaml", "id: bad\n")  # fehlende Pflichtfelder
    zones, errors = load_all_zones(str(tmp_path))
    assert "good" in zones
    assert len(errors) == 1


def test_point_in_any_keepout_and_speed_limit():
    keepout = Zone(id="k", type="keepout", polygon=[(0, 0), (2, 0), (2, 2), (0, 2)])
    slow = Zone(id="s", type="slow", polygon=[(10, 10), (12, 10), (12, 12), (10, 12)],
                max_speed_mps=0.2)
    zones = {"k": keepout, "s": slow}
    assert point_in_any_keepout(zones, 1, 1) is True
    assert point_in_any_keepout(zones, 20, 20) is False
    assert speed_limit_at(zones, 11, 11, default_mps=0.5) == 0.2
    assert speed_limit_at(zones, 20, 20, default_mps=0.5) == 0.5
