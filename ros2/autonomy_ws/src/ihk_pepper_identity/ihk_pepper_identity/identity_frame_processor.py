"""
Reine Orchestrierung EINES Kamera-Frames (Entwicklungsauftrag 04-B,
AP7.1, Abschnitt 6). KEIN ROS -- face_identity_node.py ruft
process_frame() nach jedem synchronisierten Farbe+Tiefe+CameraInfo+
PersonTrackArray-Frame auf.

Reihenfolge, exakt nach Auftrag Abschnitt 6:
  2. Gesichter erkennen -- bereits vor diesem Aufruf geschehen
     (face_detector.detect(), siehe face_detector_backend.py); faces
     wird hier nur noch entgegengenommen.
  3./4. raeumliche Zuordnung + Mehrdeutigkeitsablehnung:
     match_faces_to_tracks() (face_track_association.py).
  5. Tiefenwerte auf Aktualitaet/Plausibilitaet pruefen:
     is_depth_plausible().
  6. Liveness aus mehreren Tiefenwerten im Gesichtsbereich bewerten:
     check_liveness() (liveness.py).
  7. Identitaet nur ueber mehrere Frames bestaetigen:
     PersistentIdentityConfirmer.observe_match()
     (persistent_identity_confirmer.py).
  8. persistente Zuordnung NUR mit gueltiger Einwilligung:
     consent_lookup_fn() wird UNMITTELBAR VOR jeder Verwendung eines
     Bestaetigungsergebnisses erneut geprueft -- ein seit der letzten
     Bestaetigung erfolgter Widerruf wirkt SOFORT, es gibt keinen
     zwischengespeicherten Consent-Status.
  9. Ergebnis mit Ablaufzeit (valid_until_s) je Track.
  10. jeder Track, der eine der Stufen 3-8 nicht besteht, faellt auf
      known=False zurueck (NIE ein erfundenes Ergebnis).

Rollenaufloesung ist AUSDRUECKLICH NICHT Teil dieses Moduls (Auftrag
Abschnitt 8/AP7.1.4: "Die Identity-Komponente darf hoechstens eine
Person-ID liefern. Die Rolle wird aus der vertrauenswuerdigen
Personen-Registry geladen.") -- PersonIdentityFrameResult enthaelt
bewusst KEIN role-Feld, der Aufrufer (face_identity_node.py) loest die
Rolle getrennt auf (siehe role_resolution.py)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Tuple

from .face_detector_backend import FaceDetection
from .face_identity_backend import FaceIdentityBackend
from .face_track_association import TrackBoundingBox, is_depth_plausible, match_faces_to_tracks
from .identity_matching import match_embedding
from .liveness import check_liveness
from .persistent_identity_confirmer import PersistentIdentityConfirmer


@dataclass(frozen=True)
class PersonIdentityFrameResult:
    track_id: int
    known: bool
    person_id: str = ""
    consent_granted: bool = False
    recognition_confidence: float = 0.0
    liveness_passed: bool = False
    reason: str = ""
    valid_until_s: float = 0.0


@dataclass(frozen=True)
class IdentityFrameConfig:
    minimum_iou: float = 0.3
    ambiguity_margin: float = 0.1
    minimum_depth_confidence: float = 0.3
    minimum_track_distance_m: float = 0.3
    maximum_track_distance_m: float = 4.0
    minimum_liveness_valid_samples: int = 20
    minimum_liveness_depth_std_m: float = 0.008
    minimum_match_similarity: float = 0.55
    minimum_match_margin: float = 0.05
    result_validity_s: float = 2.0


def _unknown(track_id: int, now_s: float, config: IdentityFrameConfig, reason: str,
             liveness_passed: bool = False, recognition_confidence: float = 0.0) -> PersonIdentityFrameResult:
    return PersonIdentityFrameResult(
        track_id=track_id, known=False, liveness_passed=liveness_passed,
        recognition_confidence=recognition_confidence, reason=reason,
        valid_until_s=now_s + config.result_validity_s,
    )


def process_frame(
    tracks: List[TrackBoundingBox],
    faces: List[FaceDetection],
    depth_patch_fn: Callable[[FaceDetection], List[float]],
    identity_backend: FaceIdentityBackend,
    confirmer: PersistentIdentityConfirmer,
    template_candidates_fn: Callable[[], List[Tuple[str, bytes]]],
    consent_lookup_fn: Callable[[str], bool],
    image,
    now_s: float,
    config: IdentityFrameConfig,
) -> List[PersonIdentityFrameResult]:
    matches = match_faces_to_tracks(faces, tracks, config.minimum_iou, config.ambiguity_margin)
    results: List[PersonIdentityFrameResult] = []

    for track in tracks:
        match = matches.get(track.track_id)
        if match is None:
            confirmer.clear_track(track.track_id)
            results.append(_unknown(track.track_id, now_s, config, "kein_gesicht_eindeutig_zugeordnet"))
            continue

        if not is_depth_plausible(
                track, config.minimum_depth_confidence,
                config.minimum_track_distance_m, config.maximum_track_distance_m):
            confirmer.clear_track(track.track_id)
            results.append(_unknown(track.track_id, now_s, config, "tiefe_nicht_plausibel"))
            continue

        depth_values = depth_patch_fn(match.face)
        liveness = check_liveness(
            depth_values, config.minimum_liveness_depth_std_m, config.minimum_liveness_valid_samples)
        if not liveness.passed:
            confirmer.clear_track(track.track_id)
            results.append(_unknown(track.track_id, now_s, config, f"liveness:{liveness.reason}"))
            continue

        bbox = (match.face.bbox_x, match.face.bbox_y, match.face.bbox_width, match.face.bbox_height)
        embedding_result = identity_backend.identify_persistent(image, bbox)
        if not embedding_result.valid or embedding_result.embedding is None:
            confirmer.clear_track(track.track_id)
            results.append(_unknown(
                track.track_id, now_s, config, f"einbettung:{embedding_result.reason}",
                liveness_passed=True))
            continue

        candidates = template_candidates_fn()
        match_result = match_embedding(
            embedding_result.embedding, candidates,
            config.minimum_match_similarity, config.minimum_match_margin)
        confirmed = confirmer.observe_match(track.track_id, match_result)
        if not confirmed:
            results.append(_unknown(
                track.track_id, now_s, config, "noch_nicht_mehrfach_bestaetigt",
                liveness_passed=True, recognition_confidence=match_result.similarity))
            continue

        person_id = confirmer.confirmed_person_id(track.track_id)
        if not consent_lookup_fn(person_id):
            # Widerruf seit der letzten Bestaetigung -- der Track darf
            # NICHT weiter als bestaetigt gelten.
            confirmer.clear_track(track.track_id)
            results.append(_unknown(
                track.track_id, now_s, config, "einwilligung_widerrufen_oder_fehlend",
                liveness_passed=True))
            continue

        results.append(PersonIdentityFrameResult(
            track_id=track.track_id, known=True, person_id=person_id, consent_granted=True,
            recognition_confidence=match_result.similarity, liveness_passed=True, reason="",
            valid_until_s=now_s + config.result_validity_s,
        ))

    return results
