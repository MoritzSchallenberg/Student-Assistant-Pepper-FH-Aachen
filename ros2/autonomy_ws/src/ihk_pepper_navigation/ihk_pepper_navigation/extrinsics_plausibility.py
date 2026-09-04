"""
Plausibilitaetspruefung fuer die konfigurierten RealSense-Montagewerte
(Entwicklungsauftrag 2, Abschnitt 6 "AP3 -- Kameramontage und TF-Kette").
Kein ROS -- reine Pruef-Logik, aufgerufen von realsense_static_tf.launch.py
(Warnung beim Start) und unit-getestet.

Ergaenzt die bereits vorhandene is_calibrated=false-Warnung (Entwicklungsauftrag 1)
um eine echte Wertepruefung: Pepper ist laut Datenblatt ca. 1.2m hoch, eine
kopfmontierte Kamera kann realistischerweise nicht mehrere Meter von
base_link entfernt sein. Erkennt grob falsche/vertauschte Konfigurationswerte
(z.B. Meter statt Zentimeter vertauscht) -- ersetzt KEINE echte Vermessung,
siehe docs/REALSENSE_CALIBRATION.md.
"""
import math
from dataclasses import dataclass

# Deutlich ueber Peppers Gesamthoehe (~1.2m) -- ein plausibler Rahmen fuer
# eine kopfmontierte Kamera relativ zu base_link (Torso), keine praezise
# Grenze.
MAX_PLAUSIBLE_TRANSLATION_M = 2.0


@dataclass
class ExtrinsicsPlausibilityResult:
    plausible: bool
    reason: str


def check_extrinsics_plausibility(translation_m: dict, rotation_rpy_rad: dict) -> ExtrinsicsPlausibilityResult:
    """Reine Funktion, keine Seiteneffekte. plausible=False bei jedem
    unplausiblen Wert -- ersetzt nicht die eigentliche Kalibrierung
    (is_calibrated bleibt der massgebliche Status), warnt aber zusaetzlich
    vor offensichtlich falschen Zahlen."""
    magnitude = math.sqrt(
        translation_m["x"] ** 2 + translation_m["y"] ** 2 + translation_m["z"] ** 2)
    if magnitude > MAX_PLAUSIBLE_TRANSLATION_M:
        return ExtrinsicsPlausibilityResult(
            False, f"translation_unplausibel_{magnitude:.2f}m_ueber_{MAX_PLAUSIBLE_TRANSLATION_M}m")

    for axis in ("roll", "pitch", "yaw"):
        value = rotation_rpy_rad[axis]
        if not (-math.pi <= value <= math.pi):
            return ExtrinsicsPlausibilityResult(False, f"{axis}_ausserhalb_minus_pi_bis_pi")

    return ExtrinsicsPlausibilityResult(True, "ok")
