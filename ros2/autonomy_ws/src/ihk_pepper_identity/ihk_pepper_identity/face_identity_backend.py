"""
FaceIdentityBackend-Familie (Entwicklungsauftrag 04-B, AP7, Abschnitt
7). Austauschbar (gleiches Prinzip wie MotionTransport/
ReSpeakerAudioTransport/DirectionalAudioBackend): DisabledIdentityBackend
(sicherer Default -- KEINE Erkennung), MockIdentityBackend (Tests),
LocalOnnxIdentityBackend (echtes, lokales CPU-Inferenz-Backend, siehe
dessen Klassendoku fuer den ehrlichen, HARDWAREVERIFICATIONREQUIRED-Stand).

ZWEI GETRENNTE FUNKTIONEN (Auftrag Abschnitt 7), bewusst als zwei
Methoden mit unterschiedlichen Rueckgabetypen, damit sie strukturell
nicht verwechselt werden koennen:

    observe_transient()   -- Gruppengespraeche: Gesicht vorhanden?
                              ausreichend gross? Blick grob zu Pepper?
                              KEINE Einbettung berechnet, KEINE
                              dauerhafte Speicherung, kein Namensbezug.
    identify_persistent()  -- NUR fuer bereits eingewilligte Personen
                              (der Aufrufer entscheidet das VORHER, das
                              Backend selbst kennt kein Consent-Modell) --
                              berechnet eine Einbettung fuer den
                              Abgleich gegen biometric_template_store.py.

Gesichtsbilder werden NIRGENDS in diesem Modul gespeichert -- jede
process()-Methode nimmt ein Bild nur zur Laufzeit entgegen, gibt
niemals das Bild selbst zurueck.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class TransientFaceObservation:
    """Fluechtiges Ergebnis fuer EIN erkanntes Gesicht -- keine
    Einbettung, kein Namensbezug (Auftrag Abschnitt 7/15: "bedeutet
    nicht automatisch: Bild speichern/unbekannte Person registrieren")."""

    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    face_visible: bool
    face_sufficiently_large: bool
    gaze_toward_camera_score: float  # 0.0 (abgewandt) .. 1.0 (direkt zugewandt)
    reason: str = ""


@dataclass(frozen=True)
class FaceEmbeddingResult:
    """Ergebnis EINER Einbettungsberechnung fuer den persistenten Pfad.
    embedding=None bei jedem Fehlschlag -- NIE ein erfundener Vektor."""

    embedding: Optional[bytes]
    valid: bool
    confidence: float
    reason: str = ""


class FaceIdentityBackendError(RuntimeError):
    pass


class FaceIdentityModelNotFoundError(FaceIdentityBackendError):
    """Auftrag Abschnitt 7: 'beim Fehlen des Modells fail-closed
    bleiben' + 'beim Start kein Modell automatisch herunterladen' --
    diese Ausnahme wird beim Fehlen der Modelldatei geworfen, es gibt
    KEINEN automatischen Download-Versuch irgendwo in diesem Modul."""


class FaceIdentityBackend(ABC):
    @abstractmethod
    def observe_transient(self, image, face_bboxes: List[tuple]) -> List[TransientFaceObservation]:
        """image: RGB-Frame (numpy-Array oder aequivalent, Backend-
        spezifisch). face_bboxes: bereits vorhandene Gesichts-Bounding-
        Boxen (x,y,w,h) -- dieses Backend erkennt keine neuen Gesichter
        selbst, es bewertet nur bereits gefundene (Erkennung selbst ist
        Aufgabe eines vorgelagerten Detektors, hier nicht Teil des
        Vertrags, um dieses Modul klein/austauschbar zu halten)."""
        ...

    @abstractmethod
    def identify_persistent(self, image, face_bbox: tuple) -> FaceEmbeddingResult:
        ...


class DisabledIdentityBackend(FaceIdentityBackend):
    """Sicherer Default -- KEINE Erkennung, jede Anfrage liefert ehrlich
    'deaktiviert'. Fuer jeden Modus, in dem keine Gesichtserkennung
    laufen soll (Standard, bis explizit ein anderes Backend konfiguriert
    wird)."""

    def observe_transient(self, image, face_bboxes: List[tuple]) -> List[TransientFaceObservation]:
        return [
            TransientFaceObservation(
                bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                face_visible=False, face_sufficiently_large=False,
                gaze_toward_camera_score=0.0, reason="identity_backend_disabled",
            )
            for (x, y, w, h) in face_bboxes
        ]

    def identify_persistent(self, image, face_bbox: tuple) -> FaceEmbeddingResult:
        return FaceEmbeddingResult(embedding=None, valid=False, confidence=0.0,
                                    reason="identity_backend_disabled")


class MockIdentityBackend(FaceIdentityBackend):
    """Fest injizierbares Ergebnis fuer Tests -- gleiches Prinzip wie
    MockDirectionalBackend/MockPcmTransport."""

    def __init__(self, transient_fn=None, persistent_fn=None,
                 fixed_transient: Optional[List[TransientFaceObservation]] = None,
                 fixed_persistent: Optional[FaceEmbeddingResult] = None):
        self._transient_fn = transient_fn
        self._persistent_fn = persistent_fn
        self._fixed_transient = fixed_transient
        self._fixed_persistent = fixed_persistent

    def observe_transient(self, image, face_bboxes: List[tuple]) -> List[TransientFaceObservation]:
        if self._transient_fn is not None:
            return self._transient_fn(image, face_bboxes)
        return self._fixed_transient or []

    def identify_persistent(self, image, face_bbox: tuple) -> FaceEmbeddingResult:
        if self._persistent_fn is not None:
            return self._persistent_fn(image, face_bbox)
        return self._fixed_persistent or FaceEmbeddingResult(
            embedding=None, valid=False, confidence=0.0, reason="kein_fixed_persistent_gesetzt")


class LocalOnnxIdentityBackend(FaceIdentityBackend):
    """CPU-faehiges, lokales ONNX-Inferenz-Backend (Auftrag Abschnitt 7:
    "lokal auf dem NUC laufen koennen, CPU-faehig sein, ueber einen
    Modellpfad konfiguriert, nach Installation offline funktionieren").

    EHRLICHER STAND (hwverificationrequired, siehe
    docs/FACE_IDENTITY_AND_PRIVACY.md): in dieser Session ist KEIN
    echtes Gesichtserkennungs-ONNX-Modell vorhanden -- die Inferenz-
    Pipeline unten (Normalisierung -> ein Eingabe-Tensor -> ein
    Ausgabe-Tensor als Einbettung) folgt der ueblichen Konvention
    fuer Gesichts-Einbettungsmodelle (z.B. ArcFace-artige Netze), wurde
    aber NIE gegen ein tatsaechliches Modell verifiziert. Konstruktion
    schlaegt fail-closed fehl, wenn:
      - die Modelldatei nicht existiert (FaceIdentityModelNotFoundError,
        KEIN automatischer Download-Versuch),
      - onnxruntime nicht installiert ist (FaceIdentityBackendError).
    Erkennung selbst (Gesichts-Bounding-Boxen) ist NICHT Teil dieses
    Backends (siehe FaceIdentityBackend-Klassendoku) -- observe_transient()
    bewertet nur bereits vorhandene Boxen anhand ihrer Groesse/Position,
    OHNE ein zweites Modell fuer Blickrichtung (das waere ein weiteres,
    hier nicht vorhandenes Modell -- gaze_toward_camera_score bleibt ein
    grober geometrischer Schaetzwert aus der Bounding-Box-Position, KEINE
    echte Blickrichtungsschaetzung)."""

    EMBEDDING_INPUT_SIZE = (112, 112)  # ueblich fuer ArcFace-artige Modelle

    def __init__(self, model_path: str, minimum_face_size_px: int = 60,
                 gaze_center_tolerance_ratio: float = 0.35):
        if not model_path or not os.path.isfile(model_path):
            raise FaceIdentityModelNotFoundError(
                f"Gesichtserkennungsmodell nicht gefunden: {model_path!r} -- "
                "kein automatischer Download (Entwicklungsauftrag 04-B, AP7, "
                "Abschnitt 7)."
            )
        try:
            import onnxruntime
        except ImportError as e:
            raise FaceIdentityBackendError(
                "onnxruntime ist nicht installiert -- LocalOnnxIdentityBackend "
                "kann nicht verwendet werden."
            ) from e
        self.model_path = model_path
        self.minimum_face_size_px = minimum_face_size_px
        self.gaze_center_tolerance_ratio = gaze_center_tolerance_ratio
        self._session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name

    def observe_transient(self, image, face_bboxes: List[tuple]) -> List[TransientFaceObservation]:
        observations = []
        image_height = getattr(image, "shape", (0, 0))[0] if image is not None else 0
        image_width = getattr(image, "shape", (0, 0))[1] if image is not None else 0
        for (x, y, w, h) in face_bboxes:
            sufficiently_large = min(w, h) >= self.minimum_face_size_px
            gaze_score = _bbox_center_gaze_score(
                x, y, w, h, image_width, image_height, self.gaze_center_tolerance_ratio)
            observations.append(TransientFaceObservation(
                bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                face_visible=True, face_sufficiently_large=sufficiently_large,
                gaze_toward_camera_score=gaze_score,
                reason="" if sufficiently_large else "gesicht_zu_klein",
            ))
        return observations

    def identify_persistent(self, image, face_bbox: tuple) -> FaceEmbeddingResult:
        import numpy as np

        x, y, w, h = face_bbox
        if w <= 0 or h <= 0 or image is None:
            return FaceEmbeddingResult(embedding=None, valid=False, confidence=0.0,
                                        reason="ungueltige_bounding_box")
        try:
            crop = image[y:y + h, x:x + w]
            resized = _resize_nearest(crop, self.EMBEDDING_INPUT_SIZE)
            tensor = np.asarray(resized, dtype=np.float32)
            tensor = (tensor / 127.5) - 1.0  # uebliche [-1,1]-Normalisierung
            tensor = np.transpose(tensor, (2, 0, 1))[None, ...]  # NCHW
            outputs = self._session.run(None, {self._input_name: tensor})
            embedding = np.asarray(outputs[0]).astype(np.float32).tobytes()
        except Exception as e:
            return FaceEmbeddingResult(embedding=None, valid=False, confidence=0.0,
                                        reason=f"inferenz_fehlgeschlagen:{type(e).__name__}")
        return FaceEmbeddingResult(embedding=embedding, valid=True, confidence=1.0, reason="")


def _bbox_center_gaze_score(x, y, w, h, image_width, image_height, tolerance_ratio) -> float:
    """Grober GEOMETRISCHER Schaetzwert (KEINE echte Blickrichtungs-
    schaetzung, siehe Klassendoku) -- ein Gesicht nahe der Bildmitte
    gilt als eher zu Pepper gewandt als eines am Bildrand."""
    if image_width <= 0 or image_height <= 0:
        return 0.0
    face_center_x = x + w / 2.0
    face_center_y = y + h / 2.0
    offset_x = abs(face_center_x - image_width / 2.0) / (image_width / 2.0)
    offset_y = abs(face_center_y - image_height / 2.0) / (image_height / 2.0)
    offset = max(offset_x, offset_y)
    score = max(0.0, 1.0 - offset / max(tolerance_ratio, 1e-6))
    return min(1.0, score)


def _resize_nearest(crop, target_size):
    """Nearest-Neighbor-Resize ohne OpenCV-Abhaengigkeit (cv_bridge ist
    in diesem Workspace bereits fuer Tiefenbilder vorhanden, aber ein
    einfacher Nearest-Neighbor-Resize reicht hier und vermeidet eine
    weitere Abhaengigkeit nur fuer diesen einen Schritt)."""
    import numpy as np

    src_h, src_w = crop.shape[0], crop.shape[1]
    target_w, target_h = target_size
    if src_h == 0 or src_w == 0:
        raise ValueError("leerer Bildausschnitt")
    row_idx = (np.arange(target_h) * src_h / target_h).astype(np.int64).clip(0, src_h - 1)
    col_idx = (np.arange(target_w) * src_w / target_w).astype(np.int64).clip(0, src_w - 1)
    return crop[row_idx][:, col_idx]
