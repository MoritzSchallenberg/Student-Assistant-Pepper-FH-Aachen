"""
Interesse-Score fuer einen Personen-Track (Arbeitspaket 5).

Bewusst als reine, testbare Funktion ohne ROS-Abhaengigkeiten gebaut --
TrackHistory sammelt einfache Kennzahlen ueber mehrere Frames, score()
gewichtet die in Abschnitt 5 genannten positiven/negativen Signale.

EHRLICHKEITSHINWEIS: "Person sieht/steht in Richtung Pepper" wird hier nur
NAEHERUNGSWEISE aus der 2D-Bounding-Box-Position (mittig im Bild) und
-- falls vorhanden -- der Schulterlinien-Orientierung aus den Pose-
Keypoints abgeleitet, nicht aus echter Blickrichtungs-/Kopfpose-Schaetzung
(das waere ein eigenes Forschungsthema). Alle Gewichte/Schwellen sind
ueber Parameter einstellbar, siehe config/perception_params.yaml.
"""
from dataclasses import dataclass, field


@dataclass
class InterestWeights:
    facing_camera: float = 0.20
    stable_multi_frame: float = 0.15
    approaching_slowly: float = 0.20
    stopped_in_front: float = 0.15
    waving_or_raised_arm: float = 0.20
    good_distance: float = 0.10

    crossing_fast: float = -0.30
    moving_away_fast: float = -0.25
    too_far: float = -0.20
    single_frame_only: float = -0.50
    invalid_depth: float = -0.10
    stale_data: float = -0.50
    in_keepout_zone: float = -1.00  # harter Ausschluss


@dataclass
class TrackHistory:
    """Minimaler rollierender Zustand pro Track, den perception_node.py
    zwischen Frames pflegt und interest_scoring.score() uebergibt."""
    frame_count: int = 0
    positions_m: list = field(default_factory=list)  # [(x, y, t), ...] in map/base_link-naeherung
    last_wrist_above_shoulder: bool = False
    image_center_offset: float = 1.0  # 0=Bildmitte, 1=Bildrand
    distance_m: float = None
    has_valid_depth: bool = False
    age_s: float = 0.0
    time_since_seen_s: float = 0.0
    in_keepout_zone: bool = False
    # Entwicklungsauftrag 1, Abschnitt 4: echte Zeitstempel statt der
    # bisherigen "+= 1.0 pro Frame"-Naeherung, siehe perception_node.py.
    first_seen_s: float = None
    last_seen_wall_s: float = 0.0
    depth_confidence: float = 0.0


GOOD_DISTANCE_RANGE_M = (1.0, 2.5)
STALE_THRESHOLD_S = 1.0
APPROACH_SPEED_MAX_MPS = 0.6   # langsames Naehern
CROSS_SPEED_MIN_MPS = 0.8      # "laeuft nur vorbei"
AWAY_SPEED_MIN_MPS = 0.5


def _radial_velocity(history: TrackHistory):
    """Grobe Annaeherungsgeschwindigkeit (negativ = naehert sich Pepper,
    positiv = entfernt sich), aus den letzten beiden Positionen."""
    if len(history.positions_m) < 2:
        return None
    (x0, y0, t0), (x1, y1, t1) = history.positions_m[-2], history.positions_m[-1]
    dt = t1 - t0
    if dt <= 0:
        return None
    d0 = (x0 ** 2 + y0 ** 2) ** 0.5
    d1 = (x1 ** 2 + y1 ** 2) ** 0.5
    return (d1 - d0) / dt


def _lateral_speed(history: TrackHistory):
    if len(history.positions_m) < 2:
        return None
    (x0, y0, t0), (x1, y1, t1) = history.positions_m[-2], history.positions_m[-1]
    dt = t1 - t0
    if dt <= 0:
        return None
    return ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / dt


def score(history: TrackHistory, weights: InterestWeights = None) -> float:
    """Gibt einen Score in [0, 1] zurueck (auf diesen Bereich geklemmt)."""
    w = weights or InterestWeights()
    total = 0.0

    if history.in_keepout_zone:
        return 0.0
    if history.time_since_seen_s > STALE_THRESHOLD_S:
        total += w.stale_data
    if history.frame_count <= 1:
        total += w.single_frame_only
    else:
        total += w.stable_multi_frame

    if history.image_center_offset < 0.3:
        total += w.facing_camera

    radial_v = _radial_velocity(history)
    lateral_v = _lateral_speed(history)
    if radial_v is not None:
        if radial_v < 0 and abs(radial_v) <= APPROACH_SPEED_MAX_MPS:
            total += w.approaching_slowly
        if radial_v > 0 and abs(radial_v) >= AWAY_SPEED_MIN_MPS:
            total += w.moving_away_fast
        if abs(radial_v) < 0.1 and history.distance_m is not None and history.distance_m < 2.0:
            total += w.stopped_in_front
    if lateral_v is not None and lateral_v >= CROSS_SPEED_MIN_MPS:
        total += w.crossing_fast

    if history.last_wrist_above_shoulder:
        total += w.waving_or_raised_arm

    if history.distance_m is not None:
        if not (GOOD_DISTANCE_RANGE_M[0] <= history.distance_m <= GOOD_DISTANCE_RANGE_M[1]):
            total += w.too_far
        else:
            total += w.good_distance
        if not history.has_valid_depth:
            total += w.invalid_depth

    return max(0.0, min(1.0, total))
