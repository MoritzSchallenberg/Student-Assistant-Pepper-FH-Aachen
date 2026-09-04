"""
Reine Bewertungslogik fuer die RTAB-Map-Lokalisierung (Entwicklungsauftrag
2, Abschnitt 8 "AP5"). Kein ROS -- localization_health_node.py ist der
duenne ROS-Wrapper, gleiches Muster wie head_pose_gate.py.

Der praktische Gesundheitsindikator einer laufenden Lokalisierung ist die
Aktualitaet der von RTAB-Map publizierten map->odom-TF: solange sie
regelmaessig aktualisiert wird, weiss RTAB-Map, wo der Roboter in der
Karte steht. Bleibt sie aus/veraltet, gilt die Lokalisierung als verloren
-- sicherer Default False, NIE eine geschaetzte/veraltete Position
weiterverwendet (gleiches Prinzip wie odometry_health.py).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class LocalizationHealthResult:
    valid: bool
    reason: str


def check_localization_health(
    map_to_odom_tf_available: bool,
    map_to_odom_tf_age_s: Optional[float],
    max_tf_age_s: float,
) -> LocalizationHealthResult:
    """Reine Funktion, keine Seiteneffekte."""
    if not map_to_odom_tf_available:
        return LocalizationHealthResult(False, "keine_map_odom_tf")
    if map_to_odom_tf_age_s is None:
        return LocalizationHealthResult(False, "map_odom_tf_alter_unbekannt")
    if map_to_odom_tf_age_s > max_tf_age_s:
        return LocalizationHealthResult(False, "map_odom_tf_veraltet")
    return LocalizationHealthResult(True, "ok")
