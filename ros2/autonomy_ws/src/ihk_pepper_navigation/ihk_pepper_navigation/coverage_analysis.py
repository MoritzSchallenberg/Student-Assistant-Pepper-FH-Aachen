"""
Abdeckungsanalyse fuer die kopfmontierte RealSense (Entwicklungsauftrag 2,
Abschnitt 9 "AP6-- Hinderniserkennung und Abdeckungsnachweis"). Kein ROS
-- reine Geometrie, beantwortet zwei Fragen:

1. Wie nah an die Kamera heran kann ein Hindernis auf Bodenhoehe
   herankommen, bevor es aus dem Sichtfeld faellt (Nahbereich/toter
   Winkel, Lochkamera-Naeherung, KEINE Linsenverzerrung beruecksichtigt)?
2. Welcher horizontale Winkel bleibt von EINER kopfmontierten,
   vorwaerts gerichteten Kamera komplett unabgedeckt (seitlich/hinten)?

Bewusst KEIN Ersatz fuer eine echte Vermessung -- alle Eingabewerte
(Montagehoehe, Sichtfeldwinkel) sind Konfigurationswerte aus einem
Datenblatt, keine erfundenen Praezisionsangaben. Das Ergebnis wird NICHT
schoengeredet (Auftrag Abschnitt 9): eine einzelne Kopfkamera kann
strukturell niemals rundum abdecken -- is_coverage_sufficient_for_live_motion()
liefert fuer jede realistische Einzelkamera-Konfiguration False.
"""
import math
from dataclasses import dataclass


@dataclass
class CoverageResult:
    blind_zone_radius_m: float
    uncovered_horizontal_deg: float
    covers_full_circle: bool


def analyze_ground_coverage(
    mount_height_m: float,
    vertical_fov_deg: float,
    downward_tilt_deg: float,
    horizontal_fov_deg: float,
) -> CoverageResult:
    """Reine Geometrie, keine Seiteneffekte."""
    half_vfov = vertical_fov_deg / 2.0
    # Winkel der UNTEREN Sichtfeldgrenze zur Horizontalen -- je groesser,
    # desto naeher an die Kamera reicht das Sichtfeld auf Bodenhoehe heran.
    lower_edge_angle_deg = downward_tilt_deg + half_vfov
    if lower_edge_angle_deg <= 0:
        # Blickt nicht genug nach unten, um den Boden je zu erreichen.
        blind_zone_radius_m = math.inf
    elif lower_edge_angle_deg >= 90.0:
        # Untere Sichtfeldgrenze zeigt bereits senkrecht nach unten oder
        # darueber hinaus -- der Punkt direkt unter der Kamera liegt im
        # Sichtfeld, kein Blindbereich mehr.
        blind_zone_radius_m = 0.0
    else:
        blind_zone_radius_m = mount_height_m / math.tan(math.radians(lower_edge_angle_deg))

    uncovered_horizontal_deg = max(0.0, 360.0 - horizontal_fov_deg)
    return CoverageResult(
        blind_zone_radius_m=blind_zone_radius_m,
        uncovered_horizontal_deg=uncovered_horizontal_deg,
        covers_full_circle=(uncovered_horizontal_deg <= 0.0),
    )


def is_coverage_sufficient_for_live_motion(
    blind_zone_radius_m: float,
    footprint_radius_m: float,
    uncovered_horizontal_deg: float,
) -> bool:
    """False, wenn der Nahbereichs-Blindfleck groesser als der
    Fussabdruck ist (ein Hindernis koennte unbemerkt bis an/unter den
    Roboter heranreichen) ODER wenn ueberhaupt ein horizontaler
    Blindwinkel existiert (seitlich/hinten muss ebenfalls abgedeckt sein
    -- eine einzelne Kopfkamera kann das strukturell nicht alleine
    leisten, siehe Moduldocstring)."""
    if uncovered_horizontal_deg > 0.0:
        return False
    return blind_zone_radius_m <= footprint_radius_m
