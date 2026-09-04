"""
Reine Geometrie fuer die sichere Annaeherungs-Zielpose (Entwicklungsauftrag 2,
Abschnitt 12 "AP9 -- Sichere Annaeherungszielpose"). Kein ROS -- gleiches
Muster wie head_pose_gate.py/zone_config.py, Node-Wrapper bleibt duenn.

Ersetzt den in person_approach_node.py::_drive_to_person() bestaetigten
Mangel aus Entwicklungsauftrag 1 (siehe docs/DEVELOPMENT_ORDER_02_REPORT.md,
AP1): die bisherige Implementierung setzte die Nav2-Zielpose direkt auf die
Personenposition selbst. Diese Datei berechnet stattdessen eine Zielpose
target_distance_m VOR der Person, mit Blickrichtung zur Person -- NIEMALS
die Personenposition selbst als Fahrziel.

Alle Positionen im selben Frame (i.d.R. "map", von der aufrufenden Seite
sichergestellt -- diese Funktionen wissen selbst nichts von Frames).
"""
import math
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ApproachPoseResult:
    valid: bool
    reason: str
    target_x: float = 0.0
    target_y: float = 0.0
    target_yaw_rad: float = 0.0
    # True, wenn die Person bereits innerhalb von target_distance_m ist --
    # dann ist KEINE Fahrt noetig (Zielpose = aktuelle Roboterpose, nur die
    # Blickrichtung wird korrigiert). Der Aufrufer soll in diesem Fall keinen
    # Nav2-Auftrag senden.
    already_within_distance: bool = False


def compute_approach_pose(
    robot_x: float,
    robot_y: float,
    person_x: float,
    person_y: float,
    target_distance_m: float,
    minimum_person_distance_m: float,
    maximum_approach_distance_m: float,
    zones: Optional[dict] = None,
    costmap_free_fn: Optional[Callable[[float, float], bool]] = None,
) -> ApproachPoseResult:
    """Reine Funktion, keine Seiteneffekte. valid=False ist immer der
    sichere Ausgang bei ungueltiger Geometrie -- niemals eine Ersatz-/
    Fantasiepose (gleiches Prinzip wie ueberall im Projekt, siehe
    ihk_pepper_perception/deprojection.py).

    zones: optionales Ergebnis von zone_config.load_all_zones() -- lehnt
    eine Zielpose in einer Keepout-/staff_only-Zone ab (zone_config.py
    wird wiederverwendet statt dupliziert).

    costmap_free_fn: optionaler Rueckruf (x, y) -> bool, der True liefert,
    wenn die Zielpose ausserhalb der Karte oder in einem Hindernis liegt
    NICHT gilt. Interface fuer Arbeitspaket 6 (Nav2-Costmap) -- ohne
    Costmap (aktueller Stand, siehe AP1-Bericht) wird diese Pruefung
    uebersprungen, nicht stillschweigend als "frei" angenommen.
    """
    if target_distance_m <= 0.0:
        return ApproachPoseResult(False, "target_distance_muss_positiv_sein")
    if target_distance_m < minimum_person_distance_m:
        return ApproachPoseResult(False, "target_distance_unter_minimum_person_distance")

    dx = person_x - robot_x
    dy = person_y - robot_y
    dist = math.hypot(dx, dy)

    if dist < 1e-6:
        return ApproachPoseResult(False, "person_position_identisch_mit_roboterposition")
    if dist > maximum_approach_distance_m:
        return ApproachPoseResult(False, "person_ausserhalb_maximum_approach_distance_m")

    yaw_to_person = math.atan2(dy, dx)

    if dist <= target_distance_m:
        # Person ist bereits naeher (oder genau so weit) als der gewuenschte
        # Gespraechsabstand. NIEMALS ueber die Person hinaus oder direkt auf
        # sie zufahren -- keine Fahrt noetig, nur die Blickrichtung stimmt.
        return ApproachPoseResult(
            True, "bereits_im_gespraechsabstand",
            target_x=robot_x, target_y=robot_y, target_yaw_rad=yaw_to_person,
            already_within_distance=True,
        )

    ux, uy = dx / dist, dy / dist
    # target_distance_m VOR der Person, auf der Geraden Roboter->Person --
    # liegt damit immer zwischen der aktuellen Roboterposition und der
    # Person, nie dahinter (vermeidet ein Rueckwaertsanfahren der Person).
    target_x = person_x - ux * target_distance_m
    target_y = person_y - uy * target_distance_m

    if zones is not None:
        from .zone_config import point_in_any_keepout
        if point_in_any_keepout(zones, target_x, target_y):
            return ApproachPoseResult(False, "zielpose_in_keepout_zone")

    if costmap_free_fn is not None and not costmap_free_fn(target_x, target_y):
        return ApproachPoseResult(False, "zielpose_ausserhalb_karte_oder_in_hindernis")

    return ApproachPoseResult(
        True, "ok", target_x=target_x, target_y=target_y, target_yaw_rad=yaw_to_person,
    )


def should_replan(
    last_person_x: float,
    last_person_y: float,
    current_person_x: float,
    current_person_y: float,
    replan_distance_threshold_m: float,
) -> bool:
    """Deutliche Bewegung der Person (Auftrag Abschnitt 12) loest
    kontrolliertes Replanning aus -- kein Sofort-Reflex bei jedem kleinen
    Tracking-Jitter unterhalb der Schwelle."""
    moved = math.hypot(current_person_x - last_person_x, current_person_y - last_person_y)
    return moved >= replan_distance_threshold_m


def is_track_fresh(track_age_s: float, person_track_timeout_s: float) -> bool:
    """Track-Verlust (Auftrag Abschnitt 12) -- sicherer Default: bei
    Ueberschreitung des Timeouts gilt der Track als verloren, die
    Annaeherung muss abgebrochen werden (gleiches Prinzip wie ueberall im
    Projekt, siehe head_pose_gate.py::check_head_pose)."""
    return track_age_s <= person_track_timeout_s


class RepeatedPlanningFailureGuard:
    """Zaehlt aufeinanderfolgende Planungsfehler (Auftrag Abschnitt 12:
    "wiederholte Planungsfehler fuehren zum sicheren Abbruch"). Reiner
    Zaehler, kein ROS -- vom Node bei jedem fehlgeschlagenen
    _drive_to_pose()-Versuch aufgerufen."""

    def __init__(self, max_consecutive_failures: int = 3):
        self.max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def should_abort(self) -> bool:
        return self._consecutive_failures >= self.max_consecutive_failures

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures
