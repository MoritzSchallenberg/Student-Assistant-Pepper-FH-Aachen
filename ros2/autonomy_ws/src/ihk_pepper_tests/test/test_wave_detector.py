from ihk_pepper_perception.wave_detector import (
    PoseObservation,
    WaveDetector,
    WaveDetectorConfig,
)

SHOULDER = (0.0, 10.0)
ELBOW = (0.0, 11.0)  # bone_len = 1.0 -- alle Schwellenwerte sind Vielfache davon


def _pose(t, wrist_x, wrist_y=9.0, wrist_conf=0.9, shoulder_conf=0.9, elbow_conf=0.9):
    return PoseObservation(
        timestamp_s=t,
        shoulder_xy=SHOULDER, shoulder_confidence=shoulder_conf,
        elbow_xy=ELBOW, elbow_confidence=elbow_conf,
        wrist_xy=(wrist_x, wrist_y), wrist_confidence=wrist_conf,
    )


def _oscillating_sequence():
    """6 Frames ueber 0.75s, Handgelenk pendelt 0.0<->1.0 -- entspricht
    genau 2 Richtungswechseln, siehe Handrechnung im Kommentar von
    wave_detector.py."""
    return [
        _pose(0.00, 0.0),
        _pose(0.15, 0.5),
        _pose(0.30, 1.0),
        _pose(0.45, 0.5),
        _pose(0.60, 0.0),
        _pose(0.75, 0.5),
    ]


def test_single_raised_frame_is_not_a_wave():
    detector = WaveDetector()
    event = detector.update(1, "R", _pose(0.0, 0.0))
    assert event is not None
    assert event.stable is False
    assert event.state == "arm_raised"


def test_repeated_sideways_movement_confirms_wave():
    detector = WaveDetector()
    event = None
    for pose in _oscillating_sequence():
        event = detector.update(42, "R", pose)
    assert event is not None
    assert event.stable is True
    assert event.state == "wave_confirmed"
    assert event.gesture_name == "wave_right"
    assert event.observed_duration_s >= 0.6


def test_left_side_reports_wave_left():
    detector = WaveDetector()
    event = None
    for pose in _oscillating_sequence():
        event = detector.update(7, "L", pose)
    assert event.stable is True
    assert event.gesture_name == "wave_left"


def test_track_switch_discards_in_progress_sequence():
    detector = WaveDetector()
    seq = _oscillating_sequence()
    # Erste 4 Frames: baut einen Richtungswechsel auf (WAVE_CANDIDATE),
    # aber noch nicht bestaetigt.
    for pose in seq[:4]:
        event = detector.update(5, "R", pose)
    assert event.state == "wave_candidate"
    assert event.stable is False

    # Track "verloren" -- z.B. ByteTrack hat die Person kurz verloren.
    detector.reset_track(5)

    # Dieselbe Fortsetzung darf jetzt NICHT als nahtlose Sequenz zaehlen.
    event = detector.update(5, "R", seq[4])
    assert event.state in ("arm_raised", "wave_candidate")
    assert event.stable is False


def test_low_keypoint_confidence_is_discarded():
    detector = WaveDetector()
    low_conf_pose = _pose(0.0, 0.0, wrist_conf=0.05)
    event = detector.update(1, "R", low_conf_pose)
    assert event is None


def test_cooldown_prevents_immediate_retrigger():
    detector = WaveDetector()
    event = None
    for pose in _oscillating_sequence():
        event = detector.update(9, "R", pose)
    assert event.stable is True

    # Sofortige weitere Bewegung waehrend der Cooldown-Zeit (Default 3s)
    # darf kein zweites Ereignis auslösen.
    again = detector.update(9, "R", _pose(0.9, 1.0))
    assert again is None


def test_arm_lowered_resets_sequence():
    detector = WaveDetector()
    for pose in _oscillating_sequence()[:3]:
        detector.update(3, "R", pose)
    # Arm sinkt unter die Schwelle -- Sequenz muss verworfen werden.
    lowered = _pose(0.9, 0.5, wrist_y=10.5)
    assert detector.update(3, "R", lowered) is None
    # Danach beginnt eine neue erhobene Beobachtung wieder bei arm_raised.
    event = detector.update(3, "R", _pose(1.0, 0.0))
    assert event.state == "arm_raised"


def test_config_thresholds_are_respected():
    strict = WaveDetectorConfig(min_direction_changes=5)
    detector = WaveDetector(strict)
    event = None
    for pose in _oscillating_sequence():
        event = detector.update(1, "R", pose)
    assert event.stable is False  # nur 2 Richtungswechsel, 5 gefordert
