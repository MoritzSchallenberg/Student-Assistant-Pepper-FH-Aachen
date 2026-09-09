"""
Leitet Aktuator-Arbiter-Ressourcen deterministisch aus Gelenknamen ab
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 4). Reine Funktion -- weder
eine Gestenbeschreibung noch ein LLM legt diese Zuordnung fest, sie
kommt ausschliesslich aus dieser fest verdrahteten Tabelle.
"""
from .actuator_arbiter import BASE, HEAD, LEFT_ARM, RIGHT_ARM, SPEECH, TORSO

# Exakt die Tabelle aus dem Auftrag. Praefix-Vergleich (kein exaktes
# Dictionary), damit z.B. sowohl "LShoulderPitch" als auch ein
# kuenftiges "LShoulderYaw" ohne Codeaenderung erfasst werden.
_HEAD_PREFIXES = ("HeadYaw", "HeadPitch")
_LEFT_ARM_PREFIXES = ("LShoulder", "LElbow", "LWrist", "LHand")
_RIGHT_ARM_PREFIXES = ("RShoulder", "RElbow", "RWrist", "RHand")
_TORSO_PREFIXES = ("HipRoll", "HipPitch", "KneePitch")


def resource_for_joint(joint_name: str) -> str | None:
    """Liefert die zustaendige Ressource fuer EIN Gelenk, oder None,
    wenn das Gelenk keiner bekannten Ressource zugeordnet werden kann
    (ein Aufrufer sollte das als Fehler behandeln, nicht stillschweigend
    ignorieren -- siehe resources_for_joint_names())."""
    if joint_name in _HEAD_PREFIXES:
        return HEAD
    if joint_name.startswith(_LEFT_ARM_PREFIXES):
        return LEFT_ARM
    if joint_name.startswith(_RIGHT_ARM_PREFIXES):
        return RIGHT_ARM
    if joint_name in _TORSO_PREFIXES:
        return TORSO
    return None


def resources_for_joint_names(joint_names) -> frozenset:
    """Deterministische Ableitung fuer eine kompilierte Geste/Trajektorie.
    Wirft ValueError bei einem unbekannten Gelenk -- eine Geste, deren
    Ressourcen nicht zugeordnet werden koennen, darf nie stillschweigend
    ohne Lease laufen."""
    resources = set()
    for joint in joint_names:
        resource = resource_for_joint(joint)
        if resource is None:
            raise ValueError(f"Gelenk '{joint}' hat keine bekannte Aktuator-Arbiter-Ressource")
        resources.add(resource)
    return frozenset(resources)


def resources_for_gesture(gesture) -> frozenset:
    """gesture: gesture_catalog.Gesture (v1 oder v2) -- nutzt die
    bestehende affected_joints()-Methode (Entwicklungsauftrag 1/3),
    keine zweite Gelenkliste."""
    return resources_for_joint_names(gesture.affected_joints())


def resources_for_speech() -> frozenset:
    return frozenset({SPEECH})


def resources_for_base() -> frozenset:
    return frozenset({BASE})
