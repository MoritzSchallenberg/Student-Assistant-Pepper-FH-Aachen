"""
FaceDetectorBackend-Familie (Entwicklungsauftrag 04-B, AP7.1, Abschnitt
5). Findet Gesichts-Bounding-Boxen in einem Kamerabild -- ergaenzt
face_identity_backend.py, das AUSDRUECKLICH bereits bekannte
Bounding-Boxen voraussetzt (siehe dessen
FaceIdentityBackend.observe_transient()-Vertrag: "dieses Backend
erkennt keine neuen Gesichter selbst"). face_identity_node.py ruft
ERST detect() hier, dann observe_transient()/identify_persistent()
dort auf, mit den hier gefundenen Bounding-Boxen.

Austauschbar (gleiches Prinzip wie face_identity_backend.py/
MotionTransport/DirectionalAudioBackend): DisabledFaceDetector
(sicherer Default), MockFaceDetector (Tests), LocalOnnxFaceDetector
(echtes, lokales CPU-Inferenz-Backend). KEINE Cloud-Gesichtserkennung
(Auftrag Abschnitt 5: "Eine externe Cloud-Gesichtserkennung ist nicht
zulaessig") -- es gibt strukturell keinen HTTP-Client/keine
Netzwerkabhaengigkeit in diesem Modul.

Terminologie (Auftrag Abschnitt 5/6): ein reiner Zentrierungswert einer
Bounding-Box (wie hier optional mitgeliefert) heisst face_centering_score,
NIE "Blickrichtung"/"Gaze" -- echte Blickrichtung wuerde ein eigenes,
dafuer vorgesehenes Modell brauchen (hier NICHT vorhanden). Derselbe
Grundsatz gilt fuer face_identity_backend.py::gaze_toward_camera_score
(dort bereits als rein geometrischer Schaetzwert dokumentiert, nicht
Gegenstand dieses Commits -- siehe docs/IDENTITY_RUNTIME.md fuer die
Terminologie-Uebersicht)."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class FaceDetection:
    """Ein einzelnes erkanntes Gesicht in EINEM Kamerabild. Enthaelt
    KEINE Identitaet, KEIN Embedding -- reine Geometrie/Metadaten, siehe
    Auftrag Abschnitt 5."""

    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    confidence: float
    measured_at_s: float
    backend_name: str
    # Optionale Landmarken (z.B. Augen/Nase/Mund), Backend-spezifisches
    # Format -- None, wenn das Backend keine liefert.
    landmarks: Optional[list] = None
    # Optionaler Qualitaetswert (z.B. Schaerfe/Belichtung), 0..1 -- None,
    # wenn das Backend keinen liefert. NIE mit face_centering_score
    # verwechseln (siehe Moduldoku).
    quality_score: Optional[float] = None
    face_centering_score: Optional[float] = None


class FaceDetectorBackendError(RuntimeError):
    pass


class FaceDetectorModelNotFoundError(FaceDetectorBackendError):
    """Auftrag Abschnitt 5: 'fehlendes Modell blockiert das
    Gesamtsystem nicht' + 'keine automatische Modellbeschaffung im
    Produktionsstart' -- wird beim Fehlen der Modelldatei geworfen,
    KEIN automatischer Download-Versuch irgendwo in diesem Modul."""


class FaceDetectorBackend(ABC):
    @abstractmethod
    def detect(self, image, timestamp: float) -> List[FaceDetection]:
        """image: RGB-Frame (numpy-Array oder aequivalent, Backend-
        spezifisch). timestamp: Aufnahmezeitpunkt (monotonic
        Sekunden) -- wird unveraendert in jede FaceDetection
        uebernommen (measured_at_s), damit der Aufrufer erkannte
        Gesichter NIE ungeprueft mit Sensordaten eines anderen
        Zeitpunkts kombiniert (Auftrag Abschnitt 6: 'Sensorinformationen
        unterschiedlicher Zeitpunkte duerfen nicht ungeprueft kombiniert
        werden')."""
        ...


class DisabledFaceDetector(FaceDetectorBackend):
    """Sicherer Default -- erkennt NIE ein Gesicht. Fuer jeden Modus,
    in dem keine Gesichtserkennung laufen soll (Standard, bis explizit
    ein anderes Backend konfiguriert wird). Ein Frame-Fehler in diesem
    Backend ist strukturell unmoeglich (kein Modell, keine Inferenz)."""

    def detect(self, image, timestamp: float) -> List[FaceDetection]:
        return []


class MockFaceDetector(FaceDetectorBackend):
    """Fest injizierbares Ergebnis fuer Tests -- gleiches Prinzip wie
    MockIdentityBackend/MockDirectionalBackend."""

    def __init__(self, detect_fn=None, fixed_detections: Optional[List[FaceDetection]] = None):
        self._detect_fn = detect_fn
        self._fixed_detections = fixed_detections

    def detect(self, image, timestamp: float) -> List[FaceDetection]:
        if self._detect_fn is not None:
            return self._detect_fn(image, timestamp)
        return list(self._fixed_detections or [])


class LocalOnnxFaceDetector(FaceDetectorBackend):
    """CPU-faehiges, lokales ONNX-Inferenz-Backend (Auftrag Abschnitt
    5: 'CPU-Betrieb auf dem NUC ist moeglich', 'Modellpfad ist
    konfigurierbar').

    EHRLICHER STAND (hwverificationrequired, siehe docs/IDENTITY_RUNTIME.md):
    in dieser Session ist KEIN echtes Gesichtserkennungs-ONNX-Modell
    vorhanden -- Konstruktion schlaegt fail-closed fehl, wenn:
      - die Modelldatei nicht existiert (FaceDetectorModelNotFoundError,
        KEIN automatischer Download-Versuch),
      - onnxruntime nicht installiert ist (FaceDetectorBackendError).
    Ein Fehler bei EINEM einzelnen Frame (z.B. defektes Bild) darf den
    Node NICHT beenden -- detect() faengt jede Inferenz-Ausnahme selbst
    ab und liefert bei einem Fehler eine LEERE Liste statt eine
    Exception nach aussen zu werfen (Auftrag Abschnitt 5: 'Fehler eines
    einzelnen Frames beenden den Node nicht')."""

    def __init__(self, model_path: str, minimum_confidence: float = 0.5,
                 model_version: str = "", model_sha256: str = ""):
        if not model_path or not os.path.isfile(model_path):
            raise FaceDetectorModelNotFoundError(
                f"Gesichtserkennungsmodell nicht gefunden: {model_path!r} -- "
                "kein automatischer Download (Entwicklungsauftrag 04-B, "
                "AP7.1, Abschnitt 5)."
            )
        try:
            import onnxruntime
        except ImportError as e:
            raise FaceDetectorBackendError(
                "onnxruntime ist nicht installiert -- LocalOnnxFaceDetector "
                "kann nicht verwendet werden."
            ) from e
        self.model_path = model_path
        self.minimum_confidence = minimum_confidence
        # Dokumentierbar (Auftrag Abschnitt 5: 'Modellversion und
        # Pruefsumme sind dokumentierbar') -- rein informativ, keine
        # eigene Validierung hier (siehe identityctl validate-store fuer
        # den Template-Store; eine Modell-Pruefsummenpruefung waere ein
        # separates, hier nicht vorhandenes Werkzeug).
        self.model_version = model_version
        self.model_sha256 = model_sha256
        self._session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name

    def detect(self, image, timestamp: float) -> List[FaceDetection]:
        if image is None:
            return []
        try:
            return self._run_inference(image, timestamp)
        except Exception:
            # Auftrag Abschnitt 5: ein einzelner defekter Frame darf den
            # Node nicht beenden -- fail-closed auf "kein Gesicht
            # erkannt" statt einer Exception nach aussen.
            return []

    def _run_inference(self, image, timestamp: float) -> List[FaceDetection]:
        """Die eigentliche Inferenz ist NICHT gegen ein echtes Modell
        verifiziert (siehe Klassendoku) -- dieser Pfad ist strukturell
        vorbereitet, aber ohne ein reales Modell in dieser Session nie
        tatsaechlich mit echten Ausgaben durchlaufen."""
        import numpy as np

        tensor = np.asarray(image, dtype=np.float32)
        if tensor.ndim == 3:
            tensor = np.transpose(tensor, (2, 0, 1))[None, ...]  # NCHW
        outputs = self._session.run(None, {self._input_name: tensor})
        # Erwartetes Ausgabeformat (uebliche Konvention fuer einfache
        # Gesichtsdetektoren): outputs[0] eine Liste von
        # (x, y, w, h, confidence)-Zeilen.
        detections = []
        for row in np.asarray(outputs[0]):
            x, y, w, h, confidence = (float(v) for v in row[:5])
            if confidence < self.minimum_confidence:
                continue
            detections.append(FaceDetection(
                bbox_x=int(x), bbox_y=int(y), bbox_width=int(w), bbox_height=int(h),
                confidence=confidence, measured_at_s=timestamp,
                backend_name="local_onnx",
            ))
        return detections
