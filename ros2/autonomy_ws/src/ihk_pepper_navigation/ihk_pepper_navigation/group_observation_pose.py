"""
Reine Geometrie fuer eine sichere Gruppen-Beobachtungspose
(Entwicklungsauftrag 04-B, AP7, Abschnitt 16). Gleiches Muster wie
approach_pose.py: kein ROS, Node-Wrapper bleibt duenn, valid=False ist
immer der sichere Ausgang -- NIE eine Ersatz-/Fantasiepose.

Pepper soll sich vor Gespraechsbeginn so positionieren, dass alle
bestaetigten Gruppenmitglieder moeglichst gleichzeitig im RealSense-Bild
liegen -- NIEMALS auf den Gruppenmittelpunkt fahren, der Mindestabstand
gilt zur NAECHSTEN Person (nicht nur zum Zentrum). Nur EINE begrenzte
Positionierung VOR Gespraechsbeginn -- der Aufrufer darf diese Funktion
NICHT waehrend eines laufenden Gespraechs wiederholt aufrufen (kein
staendiges Nachregeln, Auftrag Abschnitt 16).

EHRLICHE EINSCHRAENKUNG zu "kein Rueckwaertsfahren" (Auftrag Abschnitt
16): diese reine Geometriefunktion waehlt bewusst KEINE Zielpose danach
aus, ob sie "hinter" der aktuellen Blickrichtung liegt -- ein normales
Nav2-Ziel dreht sich zuerst und faehrt dann VORWAERTS dorthin, das ist
kein Rueckwaertsfahren im eigentlichen Sinn (anders als
compute_approach_pose(), das ebenfalls keine solche Pruefung hat). Die
eigentliche "keine rohe Rueckwaerts-/cmd_vel-Bewegung"-Garantie liegt
weiterhin bei Motion Guard/Nav2s eigenem Controller (Ausfuehrungsebene,
siehe Commit 8 -- FollowPerson-Laufzeit), nicht bei der Zielpose-Auswahl
hier."""
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class GroupObservationPoseResult:
    valid: bool
    reason: str
    target_x: float = 0.0
    target_y: float = 0.0
    target_yaw_rad: float = 0.0
    expected_angular_span_rad: float = 0.0
    distance_to_nearest_person_m: float = 0.0
    all_members_expected_visible: bool = False


def compute_group_observation_pose(
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    member_positions: List[Tuple[float, float]],
    camera_horizontal_fov_deg: float,
    minimum_person_distance_m: float,
    maximum_travel_distance_m: float,
    zones: Optional[dict] = None,
    costmap_free_fn: Optional[Callable[[float, float], bool]] = None,
    fov_safety_margin_ratio: float = 0.85,
) -> GroupObservationPoseResult:
    """Reine Funktion, keine Seiteneffekte.

    Geschlossene Loesung statt Suche: eine Gruppe wird als Kreisscheibe
    um ihr Zentrum mit Radius spread_radius_m (Abstand des am weitesten
    entfernten Mitglieds vom Zentrum) genaehert. Der Mindestabstand, aus
    dem diese Scheibe vollstaendig ins (leicht verkleinerte, Sicherheits-
    marge fov_safety_margin_ratio) Kamera-Sichtfeld passt, ergibt sich
    direkt aus der Tangens-Beziehung -- keine iterative Suche noetig.

    zones/costmap_free_fn: siehe approach_pose.py::compute_approach_pose,
    identisches Wiederverwendungsprinzip. Siehe Moduldoku oben zur
    bewussten Nicht-Beruecksichtigung von "Rueckwaertsfahren" in dieser
    reinen Zielpose-Auswahl.
    """
    if len(member_positions) < 2:
        return GroupObservationPoseResult(False, "zu_wenige_mitglieder")

    center_x = sum(p[0] for p in member_positions) / len(member_positions)
    center_y = sum(p[1] for p in member_positions) / len(member_positions)
    spread_radius_m = max(math.hypot(p[0] - center_x, p[1] - center_y) for p in member_positions)

    dx = center_x - robot_x
    dy = center_y - robot_y
    dist_robot_to_center = math.hypot(dx, dy)
    if dist_robot_to_center < 1e-6:
        # Roboter steht exakt im Gruppenzentrum -- degenerierter Fall
        # (sollte durch "niemals auf den Gruppenmittelpunkt fahren" in
        # frueheren Aufrufen ohnehin nie eintreten). Nutzt die aktuelle
        # Blickrichtung als Rueckzugsachse statt abzustuerzen.
        direction_x, direction_y = math.cos(robot_yaw_rad), math.sin(robot_yaw_rad)
    else:
        direction_x, direction_y = dx / dist_robot_to_center, dy / dist_robot_to_center

    fov_rad = math.radians(camera_horizontal_fov_deg) * fov_safety_margin_ratio
    fov_rad = max(1e-3, min(math.pi - 1e-3, fov_rad))

    required_distance_for_fov = (
        spread_radius_m / math.tan(fov_rad / 2.0) if spread_radius_m > 1e-9 else 0.0
    )
    min_distance_for_safety = spread_radius_m + minimum_person_distance_m
    candidate_distance = max(required_distance_for_fov, min_distance_for_safety)

    target_x = center_x - direction_x * candidate_distance
    target_y = center_y - direction_y * candidate_distance

    travel_distance_m = math.hypot(target_x - robot_x, target_y - robot_y)
    if required_distance_for_fov > maximum_travel_distance_m + dist_robot_to_center:
        # Selbst OHNE jede weitere Einschraenkung waere die Gruppe zu
        # breit, um sie innerhalb der erlaubten Fahrstrecke vollstaendig
        # ins Bild zu bekommen -- Auftrag: "bei zu grosser Gruppe um
        # Zusammenruecken bitten" (eigener, unterscheidbarer Grund).
        return GroupObservationPoseResult(False, "gruppe_zu_breit")
    if travel_distance_m > maximum_travel_distance_m:
        return GroupObservationPoseResult(False, "ziel_ausserhalb_maximaler_fahrstrecke")

    # Verteidigung in der Tiefe: der Mindestabstand gilt zur NAECHSTEN
    # Person, nicht nur zum (geometrisch garantierten) Zentrum -- direkt
    # nachgemessen statt nur der Formel zu vertrauen.
    nearest_distance_m = min(math.hypot(p[0] - target_x, p[1] - target_y) for p in member_positions)
    if nearest_distance_m < minimum_person_distance_m:
        return GroupObservationPoseResult(False, "mindestabstand_zur_naechsten_person_unterschritten")

    if zones is not None:
        from .zone_config import point_in_any_keepout
        if point_in_any_keepout(zones, target_x, target_y):
            return GroupObservationPoseResult(False, "zielpose_in_keepout_zone")

    if costmap_free_fn is not None and not costmap_free_fn(target_x, target_y):
        return GroupObservationPoseResult(False, "zielpose_ausserhalb_karte_oder_in_hindernis")

    target_yaw_rad = math.atan2(center_y - target_y, center_x - target_x)
    expected_span_rad = 2.0 * math.atan2(spread_radius_m, candidate_distance) \
        if candidate_distance > 1e-9 else 0.0

    return GroupObservationPoseResult(
        True, "ok", target_x=target_x, target_y=target_y, target_yaw_rad=target_yaw_rad,
        expected_angular_span_rad=expected_span_rad, distance_to_nearest_person_m=nearest_distance_m,
        all_members_expected_visible=True,
    )
