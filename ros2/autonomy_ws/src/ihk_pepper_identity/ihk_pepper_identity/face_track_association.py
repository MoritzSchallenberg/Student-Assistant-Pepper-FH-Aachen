"""
Ordnet erkannte Gesichter (FaceDetection, face_detector_backend.py)
räumlich Personen-Tracks zu (Entwicklungsauftrag 04-B, AP7.1, Abschnitt
6). Reine Geometrie, KEIN ROS -- face_identity_node.py ruft dies pro
Frame auf, NACH FaceDetectorBackend.detect() und VOR
FaceIdentityBackend.observe_transient()/identify_persistent().

Ein Gesicht darf NIE gleichzeitig mehreren Tracks zugeordnet werden
(Auftrag: 'Ein Gesicht darf nicht gleichzeitig mehreren Tracks
zugeordnet werden'). match_faces_to_tracks() liefert pro Track
höchstens EIN Gesicht -- fail-closed (kein Eintrag) bei Mehrdeutigkeit,
zu geringer Überlappung oder fehlender Tiefenplausibilität."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .face_detector_backend import FaceDetection


@dataclass(frozen=True)
class TrackBoundingBox:
    """Reduzierte Sicht auf einen PersonTrack (Entwicklungsauftrag 3),
    nur die fuer die Zuordnung relevanten Felder -- face_identity_node.py
    baut das aus der echten PersonTrackArray-Nachricht."""

    track_id: int
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    has_3d_position: bool = False
    distance_m: float = float("nan")
    depth_confidence: float = 0.0


@dataclass(frozen=True)
class FaceTrackMatch:
    track_id: int
    face: FaceDetection
    iou: float
    center_distance_px: float


def bbox_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    """a, b jeweils (x, y, w, h). 0.0 bei keiner Ueberlappung oder einer
    entarteten (Breite/Hoehe <= 0) Box -- NIE eine Division durch
    Null."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    inter_x0 = max(ax, bx)
    inter_y0 = max(ay, by)
    inter_x1 = min(ax + aw, bx + bw)
    inter_y1 = min(ay + ah, by + bh)
    inter_w = max(0.0, inter_x1 - inter_x0)
    inter_h = max(0.0, inter_y1 - inter_y0)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0
    union_area = aw * ah + bw * bh - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


def bbox_center_distance(a: Tuple[float, float, float, float],
                          b: Tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    acx, acy = ax + aw / 2.0, ay + ah / 2.0
    bcx, bcy = bx + bw / 2.0, by + bh / 2.0
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


def _face_bbox(face: FaceDetection) -> Tuple[float, float, float, float]:
    return (face.bbox_x, face.bbox_y, face.bbox_width, face.bbox_height)


def _track_bbox(track: TrackBoundingBox) -> Tuple[float, float, float, float]:
    return (track.bbox_x, track.bbox_y, track.bbox_width, track.bbox_height)


def match_faces_to_tracks(
    faces: List[FaceDetection],
    tracks: List[TrackBoundingBox],
    minimum_iou: float = 0.3,
    ambiguity_margin: float = 0.1,
) -> Dict[int, FaceTrackMatch]:
    """Liefert {track_id: FaceTrackMatch} -- NUR fuer Tracks mit einer
    eindeutigen, ausreichend ueberlappenden Zuordnung. Ein Track fehlt
    im Ergebnis (fail-closed, kein Eintrag), wenn:
      - kein Gesicht mit IoU >= minimum_iou ueberlappt,
      - der beste und zweitbeste IoU-Kandidat sich um weniger als
        ambiguity_margin unterscheiden (Mehrdeutigkeit -- zwei Gesichter
        ueberlappen die Box fast gleich gut),
      - dasselbe Gesicht bereits einem ANDEREN Track mit hoeherem IoU
        zugeordnet wurde (globale Eindeutigkeit -- ein Gesicht wird nie
        zweimal vergeben).

    Greedy nach global bestem IoU zuerst zugewiesen (nicht track-
    Reihenfolge), damit bei einem Konflikt zwischen zwei Tracks um
    dasselbe Gesicht der eindeutig bessere Treffer gewinnt und der
    andere Track sauber leer bleibt statt eine zweitklassige, evtl.
    falsche Zuordnung zu bekommen."""
    # Alle (track, face, iou, center_distance)-Kandidaten ueber der
    # Mindest-IoU sammeln.
    candidates: List[Tuple[float, TrackBoundingBox, FaceDetection, float]] = []
    per_track_ious: Dict[int, List[float]] = {t.track_id: [] for t in tracks}
    for track in tracks:
        t_bbox = _track_bbox(track)
        for face in faces:
            iou = bbox_iou(t_bbox, _face_bbox(face))
            per_track_ious[track.track_id].append(iou)
            if iou >= minimum_iou:
                dist = bbox_center_distance(t_bbox, _face_bbox(face))
                candidates.append((iou, track, face, dist))

    # Mehrdeutigkeit PRO TRACK vorab ausschliessen: wenn der beste und
    # zweitbeste IoU-Wert für einen Track zu nah beieinander liegen,
    # wird dieser Track komplett gesperrt (in keiner Zuweisung
    # berücksichtigt), unabhängig vom globalen Greedy-Schritt unten.
    ambiguous_track_ids = set()
    for track_id, ious in per_track_ious.items():
        sorted_ious = sorted(ious, reverse=True)
        if len(sorted_ious) >= 2 and sorted_ious[0] >= minimum_iou:
            if (sorted_ious[0] - sorted_ious[1]) < ambiguity_margin:
                ambiguous_track_ids.add(track_id)

    candidates.sort(key=lambda c: c[0], reverse=True)

    result: Dict[int, FaceTrackMatch] = {}
    used_face_ids = set()
    for iou, track, face, dist in candidates:
        if track.track_id in ambiguous_track_ids:
            continue
        if track.track_id in result:
            continue
        if id(face) in used_face_ids:
            continue
        result[track.track_id] = FaceTrackMatch(
            track_id=track.track_id, face=face, iou=iou, center_distance_px=dist)
        used_face_ids.add(id(face))
    return result


def is_depth_plausible(track: TrackBoundingBox, minimum_depth_confidence: float,
                        minimum_distance_m: float, maximum_distance_m: float) -> bool:
    """Reine Plausibilitaetspruefung (Auftrag Abschnitt 6: 'Tiefenwerte
    auf Aktualitaet und Plausibilitaet pruefen') -- fail-closed False
    bei fehlender 3D-Position/zu geringer Tiefen-Konfidenz/einer
    Distanz ausserhalb des plausiblen Bereichs (z.B. 0.0m oder
    NaN-Artefakte einer fehlgeschlagenen Entprojektion)."""
    if not track.has_3d_position:
        return False
    if track.depth_confidence < minimum_depth_confidence:
        return False
    distance = track.distance_m
    if distance != distance:  # NaN-Check ohne math-Import
        return False
    return minimum_distance_m <= distance <= maximum_distance_m
