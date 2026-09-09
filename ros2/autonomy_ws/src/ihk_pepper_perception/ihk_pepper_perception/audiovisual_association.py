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
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 11: Frame-Validierung --
    # has_3d_position=True allein reicht NICHT, ein Track muss zusaetzlich
    # tatsaechlich bereits im erwarteten Basis-Frame vorliegen (nicht
    # z.B. noch im Kamera-Optik-Frame, falls perception_node.py's TF-
    # Transformation je fehlschlaegt) UND von der erwarteten Kamera
    # stammen -- Defaults hier entsprechen dem in der Praxis korrekten
    # Fall, damit bestehende Aufrufer/Tests ohne diese Felder unveraendert
    # funktionieren.
    frame_id: str = "base_link"
    source_camera: str = "realsense"
    # Echtes, sensorgemessenes distance_m aus PersonTrack.msg (nicht die
    # planare sqrt(x^2+y^2)-Naeherung) -- durchgereicht nach
    # AssociationResult/AudioVisualTarget.msg, Entwicklungsauftrag 04-B,
    # AP6.1, Abschnitt 4.
    distance_m: float = 0.0


@dataclass(frozen=True)
class AssociationResult:
    """selected_track_id == -1 bedeutet 'keine Auswahl' (gleiche
    Sentinel-Konvention wie kNoSelectedTrackId im Behavior Tree/
    AudioFocusState.msg)."""

    selected_track_id: int
    valid: bool
    reason: str
    angular_error_deg: float = 0.0
    # Peilwinkel (RAD, nicht Grad) + Distanz des AUSGEWAEHLTEN Tracks
    # relativ zu base_link -- 0.0 bei valid=False (keine erfundene
    # Richtung/Distanz, Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4).
    target_azimuth_rad: float = 0.0
    distance_m: float = 0.0
    # Erkennungskonfidenz des AUSGEWAEHLTEN Tracks (aus PersonTrack.confidence,
    # NICHT die Guete der Zuordnung selbst) -- 0.0 bei valid=False.
    confidence: float = 0.0
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
    required_frame_id: str = "base_link",
    required_source_camera: str = "realsense",
) -> AssociationResult:
    """Reine Funktion, keine Seiteneffekte. Ablauf exakt nach Auftrag
    Abschnitt 13, um die Frame-Validierung aus Abschnitt 11 ergaenzt:
    1. Frame-/Kamera-Herkunft jedes Tracks pruefen (has_3d_position
       ALLEIN reicht nicht -- ein Track in einem falschen/unbekannten
       Frame oder von einer falschen Quelle wird verworfen, NIE benutzt).
    2. Peilwinkel je verbleibendem Track berechnen.
    3. Mit dem Schallstrahl vergleichen.
    4. Nach Winkelfehler sortieren.
    5. Kandidaten ausserhalb des Grenzwerts verwerfen.
    6. Ist der Abstand zwischen bestem und zweitbestem Kandidaten zu
       klein, waehle niemanden.
    """
    sound_azimuth_deg = math.degrees(sound_azimuth_rad)

    candidates = []
    for t in tracks:
        if not t.has_3d_position:
            continue
        if t.frame_id != required_frame_id:
            continue
        if t.source_camera != required_source_camera:
            continue
        if t.age_s > maximum_track_age_s:
            continue
        if t.confidence < minimum_track_confidence:
            continue
        if not t.stable:
            continue
        if t.in_keepout_zone:
            continue
        track_bearing_deg = bearing_deg(t.position_x_m, t.position_y_m)
        error_deg = _angle_diff_deg(track_bearing_deg, sound_azimuth_deg)
        if error_deg > maximum_angular_error_deg:
            continue
        candidates.append((t.track_id, error_deg, track_bearing_deg, t.distance_m, t.confidence))

    if not candidates:
        return AssociationResult(
            selected_track_id=-1, valid=False, reason="keine_person_im_winkelkorridor")

    candidates.sort(key=lambda c: c[1])
    best_id, best_error, best_bearing_deg, best_distance_m, best_confidence = candidates[0]
    best_azimuth_rad = math.radians(best_bearing_deg)

    if len(candidates) == 1:
        return AssociationResult(
            selected_track_id=best_id, valid=True, reason="", angular_error_deg=best_error,
            target_azimuth_rad=best_azimuth_rad, distance_m=best_distance_m,
            confidence=best_confidence,
        )

    _second_id, second_error, _second_bearing_deg, _second_distance_m, _second_confidence = candidates[1]
    margin = second_error - best_error
    if margin < minimum_ambiguity_margin_deg:
        return AssociationResult(
            selected_track_id=-1, valid=False, reason="mehrdeutig",
            angular_error_deg=best_error, ambiguity_margin_deg=margin,
        )
    return AssociationResult(
        selected_track_id=best_id, valid=True, reason="",
        angular_error_deg=best_error, ambiguity_margin_deg=margin,
        target_azimuth_rad=best_azimuth_rad, distance_m=best_distance_m,
        confidence=best_confidence,
    )
