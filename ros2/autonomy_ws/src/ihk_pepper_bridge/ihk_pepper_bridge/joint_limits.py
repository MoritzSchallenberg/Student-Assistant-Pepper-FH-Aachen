"""
Gelenkgrenzen fuer Pepper 1.8 (rad), zur Validierung bevor ein Winkel an
ALMotion geschickt wird.

Herkunft:
- Als LIVE_VERIFIED markierte Werte wurden waehrend der Session per
  `qicli call ALMotion.getLimits <Gelenk>` direkt am echten Roboter
  abgefragt (siehe docs/STATUS.md/docs/CAPABILITIES.md).
- Alle anderen Werte sind Standard-Referenzwerte aus der oeffentlichen
  Aldebaran/SoftBank-NAOqi-Dokumentation fuer Pepper 1.8 und wurden in
  dieser Session NICHT live nachgemessen (Pepper war nicht immer
  angeschlossen). Vor sicherheitskritischer Nutzung mit echtem Roboter
  gegenpruefen: `qicli call ALMotion.getLimits <Gelenk>`.
"""

# (min_rad, max_rad, live_verified)
JOINT_LIMITS = {
    "HeadYaw": (-2.0857, 2.0857, False),
    "HeadPitch": (-0.7068, 0.4451, False),

    "LShoulderPitch": (-2.0857, 2.0857, False),
    "LShoulderRoll": (0.0087, 1.5620, True),
    "LElbowYaw": (-2.0857, 2.0857, False),
    # Urspruenglich (-1.5620, -0.0087) aus Doku-Erinnerung uebernommen --
    # das widersprach aber der eigenen, live in dieser Session mehrfach
    # erfolgreich getesteten T-Pose-Sequenz (LElbowRoll=0.0). Beim
    # gesture_catalog-Test aufgefallen und korrigiert (siehe
    # docs/IMPLEMENTATION_REPORT.md). Obere Grenze mit kleinem Puffer ueber 0,
    # da 0.0 nachweislich sicher ist -- exakte Doku-Grenze weiter offen,
    # vor sicherheitskritischer Nutzung live mit getLimits nachpruefen.
    "LElbowRoll": (-1.5620, 0.05, False),
    "LWristYaw": (-1.8239, 1.8239, True),
    "LHand": (0.0, 1.0, False),

    "RShoulderPitch": (-2.0857, 2.0857, False),
    "RShoulderRoll": (-1.5620, -0.0087, True),
    "RElbowYaw": (-2.0857, 2.0857, False),
    # Siehe Kommentar bei LElbowRoll -- symmetrisch korrigiert.
    "RElbowRoll": (-0.05, 1.5620, False),
    "RWristYaw": (-1.8239, 1.8239, True),
    "RHand": (0.0, 1.0, False),

    "HipRoll": (-0.5149, 0.5149, False),
    "HipPitch": (-1.0385, 1.0385, False),
    "KneePitch": (-0.5149, 0.5149, False),
}


class JointLimitError(ValueError):
    pass


def validate_angle(joint: str, angle: float, strict: bool = True) -> float:
    """Prueft/klemmt einen Zielwinkel gegen die bekannten Gelenkgrenzen.

    strict=True: wirft JointLimitError bei Ueberschreitung (fuer
                  sicherheitskritische Pfade, z.B. Behavior-Tree-Aktionen).
    strict=False: klemmt den Wert auf die Grenze (fuer tolerantere Pfade,
                  z.B. interaktives Testen).
    Unbekannte Gelenke werden durchgereicht (kein Limit hinterlegt) --
    Aufrufer sollte das ueber das Rueckgabe-Tupel von get_limits() pruefen.
    """
    limits = JOINT_LIMITS.get(joint)
    if limits is None:
        return angle
    lo, hi, _ = limits
    if lo <= angle <= hi:
        return angle
    if strict:
        raise JointLimitError(
            f"{joint}: Winkel {angle} ausserhalb der Grenzen [{lo}, {hi}]"
        )
    return max(lo, min(hi, angle))


def get_limits(joint: str):
    """(min, max, live_verified) oder None falls Gelenk unbekannt."""
    return JOINT_LIMITS.get(joint)
