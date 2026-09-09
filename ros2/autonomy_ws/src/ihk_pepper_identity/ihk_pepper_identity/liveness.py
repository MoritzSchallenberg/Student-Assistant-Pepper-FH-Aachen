"""
Liveness-Pruefung (Entwicklungsauftrag 04-B, AP7, Abschnitt 7/8): stellt
sicher, dass vor der Kamera eine REALE Person steht, kein Foto/Bildschirm
(Auftrag Abschnitt 8: "Gesichtserkennung kann durch Fotos oder
Bildschirme angegriffen werden").

EHRLICHER STAND: dies ist eine EINFACHE, tiefenbasierte Heuristik --
ein Foto/Bildschirm ist (naeherungsweise) FLACH, ein echtes Gesicht hat
eine messbare Tiefenvarianz (Nase/Wangen/Augenhoehlen). Nutzt bereits
vorhandene RealSense-Tiefendaten (dieselbe Quelle wie
perception_node.py::estimate_patch_depth) -- KEIN separates
Blinzel-/Bewegungs-Liveness-Modell, das waere ein weiteres, hier nicht
vorhandenes Modell. Ersetzt KEINE dedizierte Anti-Spoofing-Loesung,
ist aber ein echter, kamerabasierter Signalpfad, keine reine
Formalitaet (ein FLACHES Foto besteht diese Pruefung NICHT).

NICHT gegen echte Spoofing-Versuche (Fotoabzuege/Tablets) hardware-
getestet -- siehe docs/FACE_IDENTITY_AND_PRIVACY.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LivenessResult:
    passed: bool
    depth_std_m: float
    reason: str = ""


def check_liveness(depth_values_m, minimum_depth_std_m: float = 0.008,
                    minimum_valid_samples: int = 20) -> LivenessResult:
    """depth_values_m: flache Liste/Array von Tiefenwerten (Meter) aus
    dem Gesichts-Bounding-Box-Bereich -- NaN/0/negative Werte (kein
    gueltiger Tiefenwert) werden ausgefiltert, NIE als 0-Tiefe
    interpretiert (gleiches Prinzip wie estimate_patch_depth.py:
    ungueltige Tiefenwerte fuehren zu einem Ausschluss, nie zu einer
    erfundenen Zahl)."""
    valid = [v for v in depth_values_m if v is not None and math.isfinite(v) and v > 0.0]
    if len(valid) < minimum_valid_samples:
        return LivenessResult(passed=False, depth_std_m=0.0, reason="zu_wenig_gueltige_tiefenwerte")

    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / len(valid)
    std = math.sqrt(variance)

    if std < minimum_depth_std_m:
        return LivenessResult(passed=False, depth_std_m=std, reason="zu_flach_moeglicherweise_foto")
    return LivenessResult(passed=True, depth_std_m=std, reason="")
