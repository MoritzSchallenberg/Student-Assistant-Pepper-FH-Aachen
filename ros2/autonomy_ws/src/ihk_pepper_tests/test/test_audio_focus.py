"""
Tests fuer audio_focus.py (Entwicklungsauftrag 04-B, AP6, Abschnitt 10).
"""
from ihk_pepper_audio.audio_focus import AudioFocusMode, AudioFocusStateMachine


def _machine(now=1000.0, target_loss_timeout_s=2.0):
    box = {"t": now}
    m = AudioFocusStateMachine(target_loss_timeout_s=target_loss_timeout_s, now_fn=lambda: box["t"])
    return m, box


def test_starts_idle_wide():
    m, _ = _machine()
    assert m.mode == AudioFocusMode.IDLE_WIDE
    assert m.snapshot().valid is False


def test_wakeword_transitions_to_orienting():
    m, _ = _machine()
    m.on_wakeword_detected(azimuth_rad=0.5)
    m.on_orientation_started()
    assert m.mode == AudioFocusMode.ORIENTING_TO_SOUND


def test_wakeword_ignored_when_not_idle():
    m, _ = _machine()
    m.on_wakeword_detected(azimuth_rad=0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(track_id=3, azimuth_rad=0.5)
    assert m.mode == AudioFocusMode.CONVERSATION_FOCUS
    m.on_wakeword_detected(azimuth_rad=1.0)  # sollte ignoriert werden
    assert m.mode == AudioFocusMode.CONVERSATION_FOCUS


def test_orientation_failure_returns_to_idle_eventually():
    m, _ = _machine()
    m.on_wakeword_detected(azimuth_rad=0.5)
    m.on_orientation_started()
    m.on_orientation_failed("timeout")
    assert m.mode == AudioFocusMode.RETURNING_TO_IDLE
    m.tick()
    assert m.mode == AudioFocusMode.IDLE_WIDE


def test_person_not_confirmed_returns_to_idle():
    m, _ = _machine()
    m.on_wakeword_detected(azimuth_rad=0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_not_confirmed("mehrdeutig")
    assert m.mode == AudioFocusMode.RETURNING_TO_IDLE


def test_person_confirmed_sets_conversation_focus_and_valid():
    m, _ = _machine()
    m.on_wakeword_detected(azimuth_rad=0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(track_id=7, azimuth_rad=0.4)
    snapshot = m.snapshot()
    assert snapshot.mode == AudioFocusMode.CONVERSATION_FOCUS
    assert snapshot.selected_track_id == 7
    assert snapshot.valid is True


def test_pepper_speaking_switches_mode_and_back():
    m, _ = _machine()
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    m.on_pepper_speaking_changed(True)
    assert m.mode == AudioFocusMode.PEPPER_SPEAKING
    m.on_pepper_speaking_changed(False)
    assert m.mode == AudioFocusMode.CONVERSATION_FOCUS


def test_target_track_update_ignored_for_wrong_track():
    m, _ = _machine()
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    accepted = m.on_target_track_update(track_id=99, azimuth_rad=1.0)
    assert accepted is False
    assert m.snapshot().target_azimuth_rad == 0.5


def test_target_track_update_accepted_for_correct_track():
    m, _ = _machine()
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    accepted = m.on_target_track_update(track_id=7, azimuth_rad=0.9)
    assert accepted is True
    assert m.snapshot().target_azimuth_rad == 0.9


def test_target_loss_timeout_marks_degraded():
    m, box = _machine(now=1000.0, target_loss_timeout_s=2.0)
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    box["t"] = 1000.0 + 3.0  # ueber dem Timeout
    m.tick()
    assert m.mode == AudioFocusMode.AUDIO_DEGRADED
    assert m.snapshot().valid is False


def test_degraded_recovers_on_fresh_update_for_same_track():
    m, box = _machine(now=1000.0, target_loss_timeout_s=2.0)
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    box["t"] = 1003.0
    m.tick()
    assert m.mode == AudioFocusMode.AUDIO_DEGRADED
    m.on_target_track_update(track_id=7, azimuth_rad=0.6)
    assert m.mode == AudioFocusMode.CONVERSATION_FOCUS


def test_degraded_for_too_long_returns_to_idle():
    m, box = _machine(now=1000.0, target_loss_timeout_s=2.0)
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    box["t"] = 1005.0  # ueber dem einfachen Timeout -> degraded
    m.tick()
    assert m.mode == AudioFocusMode.AUDIO_DEGRADED
    box["t"] = 1010.0  # ueber dem DOPPELTEN Timeout -> endgueltig idle
    m.tick()
    assert m.mode == AudioFocusMode.RETURNING_TO_IDLE


def test_conversation_ended_returns_to_idle():
    m, _ = _machine()
    m.on_wakeword_detected(0.5)
    m.on_orientation_started()
    m.on_visual_confirmation_started()
    m.on_person_confirmed(7, 0.5)
    m.on_conversation_ended()
    assert m.mode == AudioFocusMode.RETURNING_TO_IDLE
    m.tick()
    assert m.mode == AudioFocusMode.IDLE_WIDE
    assert m.snapshot().selected_track_id == -1
