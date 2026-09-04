"""
Motion Guard: letzte, hardwarenahe Sicherheitsinstanz vor /cmd_vel
(Entwicklungsauftrag 2, Abschnitt 11 "AP8"). Kein ROS -- reine
Zustandslogik, gleiches Muster wie safety_gate.py. motion_guard_node.py
ist der duenne ROS-Wrapper: leitet einen Fahrbefehl NUR weiter, wenn
evaluate_motion_guard() erlaubt=True liefert, sonst wird sofort
Nullgeschwindigkeit publiziert und der eingehende Befehl verworfen.

Bewusst REDUNDANT zu ihk_pepper_interaction/safety_gate.py: SafetyGate
aggregiert bereits viele Sicherheitseingaenge zu SafetyState.allow_motion
(Auftrag 1), Motion Guard prueft Bumper/Not-Halt zusaetzlich noch einmal
selbst UND die neuen, in SafetyGate noch nicht verdrahteten Auftrag-2-
Signale (RealSense-Diagnose, Odometrie-/Lokalisierungsguete, Kopfpose,
Gestenablauf, Befehlsalter). Das ist Absicht -- eine "letzte Instanz"
darf sich nicht blind auf eine einzelne vorgelagerte Aggregation
verlassen (Auftrag: "Ein LLM, Dialogknoten oder Behavior-Tree-Knoten
darf diese Schutzschicht nicht umgehen oder selbststaendig freischalten").
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MotionGuardInputs:
    live_motion_mode_active: bool
    safety_allow_motion: bool
    realsense_diagnostics_valid: bool
    odometry_valid: bool
    localization_valid: bool
    obstacle_data_valid: bool
    head_navigation_pose_valid: bool
    bumper_active: bool
    emergency_stop: bool
    gesture_in_progress: bool
    cmd_age_s: Optional[float]
    max_cmd_age_s: float


@dataclass
class MotionGuardResult:
    allow: bool
    reason: str


def evaluate_motion_guard(inputs: MotionGuardInputs) -> MotionGuardResult:
    """Reine Funktion, keine Seiteneffekte. Sicherer Default: JEDER
    einzelne Grund fuehrt sofort zu allow=False -- kein "insgesamt
    ueberwiegt es schon". Hardware-nahe Gruende (Bumper/Not-Halt) zuerst,
    dann Modus-/Freigabe-Fragen, dann Datenguete, zuletzt Timing."""
    if inputs.bumper_active:
        return MotionGuardResult(False, "bumper_active")
    if inputs.emergency_stop:
        return MotionGuardResult(False, "emergency_stop")
    if not inputs.live_motion_mode_active:
        return MotionGuardResult(False, "live_motion_mode_inactive")
    if not inputs.safety_allow_motion:
        return MotionGuardResult(False, "safety_allow_motion_false")
    if not inputs.realsense_diagnostics_valid:
        return MotionGuardResult(False, "realsense_diagnostics_invalid")
    if not inputs.odometry_valid:
        return MotionGuardResult(False, "odometry_invalid")
    if not inputs.localization_valid:
        return MotionGuardResult(False, "localization_invalid")
    if not inputs.obstacle_data_valid:
        return MotionGuardResult(False, "obstacle_data_invalid")
    if not inputs.head_navigation_pose_valid:
        return MotionGuardResult(False, "head_not_in_navigation_pose")
    if inputs.gesture_in_progress:
        return MotionGuardResult(False, "gesture_in_progress")
    if inputs.cmd_age_s is None or inputs.cmd_age_s > inputs.max_cmd_age_s:
        return MotionGuardResult(False, "cmd_vel_timeout")
    return MotionGuardResult(True, "ok")
