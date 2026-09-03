"""
Zeitlich robuste Wink-Erkennung (Entwicklungsauftrag 1, Abschnitt 5).
Reines, ROS-freies Modul (wie interest_scoring.py) -- wird pro Frame von
perception_node.py mit den ohnehin vorhandenen YOLO-Pose-Keypoints
aufgerufen, statt als eigener ROS2-Node/-Prozess: ein zweiter Prozess
muesste dieselben rohen Keypoints erst ueber ein neues,
bandbreitenintensives Topic duplizieren (Designentscheidung, siehe
docs/ARCHITECTURE_REALSense_BT.md).

Zustandsfolge pro (track_id, Seite): IDLE -> ARM_RAISED -> WAVE_CANDIDATE
-> WAVE_CONFIRMED -> COOLDOWN. Ein einzelnes Bild mit erhobener Hand kann
NIE WAVE_CONFIRMED erreichen -- das verlangt zusaetzlich
min_direction_changes echte, ausreichend grosse Richtungswechsel UEBER
min_duration_s UND min_valid_frames.
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

DEFAULT_MIN_KEYPOINT_CONFIDENCE = 0.3
# Bruchteil der Schulter-Ellenbogen-Laenge ("Bone Length") als
# koerpergroessen-unabhaengige Einheit fuer Schwellenwerte.
DEFAULT_RAISE_MARGIN_BONE_FRAC = 0.15
DEFAULT_MIN_SWING_AMPLITUDE_BONE_FRAC = 0.25
DEFAULT_MIN_DIRECTION_CHANGES = 2
DEFAULT_MIN_DURATION_S = 0.6
DEFAULT_MIN_VALID_FRAMES = 4
DEFAULT_MAX_GAP_S = 0.5
DEFAULT_COOLDOWN_S = 3.0


class WaveState(str, Enum):
    IDLE = "idle"
    ARM_RAISED = "arm_raised"
    WAVE_CANDIDATE = "wave_candidate"
    WAVE_CONFIRMED = "wave_confirmed"


@dataclass
class WaveDetectorConfig:
    min_keypoint_confidence: float = DEFAULT_MIN_KEYPOINT_CONFIDENCE
    raise_margin_bone_frac: float = DEFAULT_RAISE_MARGIN_BONE_FRAC
    min_swing_amplitude_bone_frac: float = DEFAULT_MIN_SWING_AMPLITUDE_BONE_FRAC
    min_direction_changes: int = DEFAULT_MIN_DIRECTION_CHANGES
    min_duration_s: float = DEFAULT_MIN_DURATION_S
    min_valid_frames: int = DEFAULT_MIN_VALID_FRAMES
    max_gap_s: float = DEFAULT_MAX_GAP_S
    cooldown_s: float = DEFAULT_COOLDOWN_S


@dataclass
class PoseObservation:
    """Rohbeobachtung EINES Arms (Schulter/Ellenbogen/Handgelenk) in
    EINEM Frame. Bildkonvention: x waechst nach rechts, y nach unten."""

    timestamp_s: float
    shoulder_xy: Optional[Tuple[float, float]]
    shoulder_confidence: float
    elbow_xy: Optional[Tuple[float, float]]
    elbow_confidence: float
    wrist_xy: Optional[Tuple[float, float]]
    wrist_confidence: float


@dataclass
class WaveEvent:
    """Entspricht ihk_pepper_interfaces/msg/WaveGestureEvent.msg -- dieses
    Modul ist ROS-frei, perception_node.py wandelt das 1:1 in die
    ROS-Nachricht um."""

    track_id: int
    side: str  # "L" | "R"
    gesture_name: str  # "wave_right" | "wave_left" -- passend zu den Katalognamen
    confidence: float
    stable: bool  # True nur bei WAVE_CONFIRMED
    observed_duration_s: float
    last_seen_s: float
    state: str  # WaveState-Wert, fuer Diagnose/Tests


@dataclass
class _TrackSideState:
    state: WaveState = WaveState.IDLE
    raised_since_s: Optional[float] = None
    last_update_s: Optional[float] = None
    last_wrist_x: Optional[float] = None
    extreme_x: Optional[float] = None
    direction: int = 0  # -1, 0 (noch unbestimmt), +1
    direction_changes: int = 0
    valid_frames: int = 0
    cooldown_until_s: Optional[float] = None


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class WaveDetector:
    """Haelt den Zustand PRO (track_id, Seite). Aufrufer ruft update()
    einmal pro Frame und Seite auf. reset_track() MUSS aufgerufen werden,
    sobald ByteTrack eine track_id als verloren meldet -- eine spaetere
    Wiederverwendung derselben Nummer zaehlt sonst faelschlich als
    Fortsetzung einer alten Wink-Sequenz (Track-ID-Kontinuitaet)."""

    def __init__(self, config: Optional[WaveDetectorConfig] = None):
        self.config = config or WaveDetectorConfig()
        self._states: Dict[Tuple[int, str], _TrackSideState] = {}

    def reset_track(self, track_id: int) -> None:
        for side in ("L", "R"):
            self._states.pop((track_id, side), None)

    def update(self, track_id: int, side: str, pose: PoseObservation) -> Optional[WaveEvent]:
        cfg = self.config
        key = (track_id, side)
        st = self._states.setdefault(key, _TrackSideState())

        # Cooldown: Mehrfachausloesung verhindern, bis die Zeit abgelaufen ist.
        if st.cooldown_until_s is not None:
            if pose.timestamp_s < st.cooldown_until_s:
                st.last_update_s = pose.timestamp_s
                return None
            st = _TrackSideState()
            self._states[key] = st

        # Zu grosse zeitliche Datenluecke -> Sequenz verwerfen, neu beginnen.
        if st.last_update_s is not None and (pose.timestamp_s - st.last_update_s) > cfg.max_gap_s:
            st = _TrackSideState()
            self._states[key] = st

        valid = (
            pose.shoulder_xy is not None and pose.shoulder_confidence >= cfg.min_keypoint_confidence
            and pose.elbow_xy is not None and pose.elbow_confidence >= cfg.min_keypoint_confidence
            and pose.wrist_xy is not None and pose.wrist_confidence >= cfg.min_keypoint_confidence
        )
        st.last_update_s = pose.timestamp_s
        if not valid:
            # Kurzer Konfidenz-Ausreisser: weder bestaetigen noch die
            # laufende Sequenz sofort verwerfen (das erledigt max_gap_s
            # zeitbasiert), aber auch kein gueltiger Frame.
            return None

        bone_len = _dist(pose.shoulder_xy, pose.elbow_xy)
        if bone_len <= 1e-6:
            return None
        raised = pose.wrist_xy[1] < (pose.shoulder_xy[1] - cfg.raise_margin_bone_frac * bone_len)

        if not raised:
            if st.state != WaveState.IDLE:
                self._states[key] = _TrackSideState()
            return None

        if st.raised_since_s is None:
            st.raised_since_s = pose.timestamp_s
        st.valid_frames += 1
        if st.state == WaveState.IDLE:
            st.state = WaveState.ARM_RAISED

        wrist_x = pose.wrist_xy[0]
        min_amp = cfg.min_swing_amplitude_bone_frac * bone_len
        if st.last_wrist_x is None:
            st.extreme_x = wrist_x
        elif st.direction == 0:
            if abs(wrist_x - st.extreme_x) >= min_amp:
                st.direction = 1 if wrist_x > st.extreme_x else -1
                st.extreme_x = wrist_x
        elif st.direction == 1:
            if wrist_x > st.extreme_x:
                st.extreme_x = wrist_x
            elif (st.extreme_x - wrist_x) >= min_amp:
                st.direction_changes += 1
                st.direction = -1
                st.extreme_x = wrist_x
        else:  # direction == -1
            if wrist_x < st.extreme_x:
                st.extreme_x = wrist_x
            elif (wrist_x - st.extreme_x) >= min_amp:
                st.direction_changes += 1
                st.direction = 1
                st.extreme_x = wrist_x
        st.last_wrist_x = wrist_x

        if st.direction_changes >= 1 and st.state == WaveState.ARM_RAISED:
            st.state = WaveState.WAVE_CANDIDATE

        observed_duration = pose.timestamp_s - st.raised_since_s
        gesture_name = "wave_right" if side == "R" else "wave_left"

        confirmed = (
            st.state in (WaveState.ARM_RAISED, WaveState.WAVE_CANDIDATE)
            and st.direction_changes >= cfg.min_direction_changes
            and st.valid_frames >= cfg.min_valid_frames
            and observed_duration >= cfg.min_duration_s
        )
        if confirmed:
            st.state = WaveState.WAVE_CONFIRMED
            st.cooldown_until_s = pose.timestamp_s + cfg.cooldown_s
            return WaveEvent(
                track_id=track_id, side=side, gesture_name=gesture_name,
                confidence=min(1.0, st.direction_changes / max(cfg.min_direction_changes, 1)),
                stable=True, observed_duration_s=observed_duration,
                last_seen_s=pose.timestamp_s, state=st.state.value,
            )

        return WaveEvent(
            track_id=track_id, side=side, gesture_name=gesture_name,
            confidence=0.0, stable=False, observed_duration_s=observed_duration,
            last_seen_s=pose.timestamp_s, state=st.state.value,
        )
