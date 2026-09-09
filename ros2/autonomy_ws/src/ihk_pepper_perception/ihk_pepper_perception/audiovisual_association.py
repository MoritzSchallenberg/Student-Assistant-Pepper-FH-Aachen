"""
Audiovisuelle Personenzuordnung (Entwicklungsauftrag 04-B, AP6,
Abschnitt 13). Reine, ROS-freie Logik -- ordnet eine gemessene
Schallrichtung (bereits nach base_link transformiert) genau EINER Person
aus den aktuellen RealSense-Personentracks zu, oder KEINER, wenn die
Zuordnung mehrdeutig ist. Kein Gesichtserkennungsmodell -- Mehrdeutigkeit
fuehrt IMMER zu "keine Auswahl", niemals zu einem geratenen Ergebnis
(Auftrag: "Es darf keine Gesichtserkennung verwendet werden, um eine
mehrdeutige Richtungszuordnung zu 'erraten'").

Winkelkonvention: REP-103 (Rechte-Hand-Regel um die Z-Achse) --
Peilwinkel/Azimut 0 = geradeaus (positive X-Achse), positiv = nach
links gedreht. x/y hier sind Meter in base_link (x=vorwaerts, y=links).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class TrackCandidate:
    """Duck-getypter Auszug aus einer echten PersonTrack-Nachricht --
    der ROS-Wrapper (audiovisual_association_node.py) baut diese Liste
    aus dem zuletzt empfangenen PersonTrackArray + einer Keepout-Zonen-
    Pruefung."""

    track_id: int
    confidence: float
    has_3d_position: bool
    position_x_m: float
    position_y_m: float
    stable: bool
    age_s: float
    in_keepout_zone: bool = False


@dataclass(frozen=True)
class AssociationResult:
    """selected_track_id == -1 bedeutet 'keine Auswahl' (gleiche
    Sentinel-Konvention wie kNoSelectedTrackId im Behavior Tree/
    AudioFocusState.msg)."""

    selected_track_id: int
    valid: bool
    reason: str
    angular_error_deg: float = 0.0
    ambiguity_margin_deg: float = 0.0


def bearing_deg(x_m: float, y_m: float) -> float:
    """Peilwinkel eines 3D-Punkts in base_link relativ zur
    Vorwaertsrichtung, in Grad (REP-103: positiv = nach links)."""
    return math.degrees(math.atan2(y_m, x_m))


def _angle_diff_deg(a_deg: float, b_deg: float) -> float:
    """Kleinster Winkelunterschied in Grad, robust gegen den
    -180/180-Grad-Uebergang."""
    diff = (a_deg - b_deg + 180.0) % 360.0 - 180.0
    return abs(diff)


def associate_person_to_sound(
    tracks: List[TrackCandidate],
    sound_azimuth_rad: float,
    maximum_track_age_s: float = 0.5,
    minimum_track_confidence: float = 0.70,
    maximum_angular_error_deg: float = 20.0,
    minimum_ambiguity_margin_deg: float = 10.0,
) -> AssociationResult:
    """Reine Funktion, keine Seiteneffekte. Ablauf exakt nach Auftrag
    Abschnitt 13:
    1. Peilwinkel je gueltigem Track berechnen.
    2. Mit dem Schallstrahl vergleichen.
    3. Nach Winkelfehler sortieren.
    4. Kandidaten ausserhalb des Grenzwerts verwerfen.
    5. Ist der Abstand zwischen bestem und zweitbestem Kandidaten zu
       klein, waehle niemanden.
    """
    sound_azimuth_deg = math.degrees(sound_azimuth_rad)

    candidates = []
    for t in tracks:
        if not t.has_3d_position:
            continue
        if t.age_s > maximum_track_age_s:
            continue
        if t.confidence < minimum_track_confidence:
            continue
        if not t.stable:
            continue
        if t.in_keepout_zone:
            continue
        error_deg = _angle_diff_deg(bearing_deg(t.position_x_m, t.position_y_m), sound_azimuth_deg)
        if error_deg > maximum_angular_error_deg:
            continue
        candidates.append((t.track_id, error_deg))

    if not candidates:
        return AssociationResult(
            selected_track_id=-1, valid=False, reason="keine_person_im_winkelkorridor")

    candidates.sort(key=lambda c: c[1])
    best_id, best_error = candidates[0]

    if len(candidates) == 1:
        return AssociationResult(
            selected_track_id=best_id, valid=True, reason="", angular_error_deg=best_error)

    _second_id, second_error = candidates[1]
    margin = second_error - best_error
    if margin < minimum_ambiguity_margin_deg:
        return AssociationResult(
            selected_track_id=-1, valid=False, reason="mehrdeutig",
            angular_error_deg=best_error, ambiguity_margin_deg=margin,
        )
    return AssociationResult(
        selected_track_id=best_id, valid=True, reason="",
        angular_error_deg=best_error, ambiguity_margin_deg=margin,
    )
