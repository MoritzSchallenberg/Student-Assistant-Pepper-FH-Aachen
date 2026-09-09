"""
Tests fuer group_speaker_selection.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 17).
"""
import math

from ihk_pepper_audio.group_speaker_selection import ActiveSpeakerSelector, GroupMemberBearing


def _members(*pairs):
    return [GroupMemberBearing(track_id=tid, bearing_rad=math.radians(deg)) for tid, deg in pairs]


def test_no_speaker_selected_before_enough_confirming_frames():
    selector = ActiveSpeakerSelector(required_confirming_frames=3)
    members = _members((1, 0.0), (2, 90.0))
    result = selector.observe(True, math.radians(0.0), True, members)
    assert result.changed is False
    assert result.selected_track_id == -1


def test_speaker_confirmed_after_enough_frames():
    selector = ActiveSpeakerSelector(required_confirming_frames=3)
    members = _members((1, 0.0), (2, 90.0))
    selector.observe(True, math.radians(0.0), True, members)
    selector.observe(True, math.radians(0.0), True, members)
    result = selector.observe(True, math.radians(0.0), True, members)
    assert result.changed is True
    assert result.selected_track_id == 1
    assert selector.current_speaker() == 1


def test_no_vad_resets_the_confirmation_streak():
    selector = ActiveSpeakerSelector(required_confirming_frames=3)
    members = _members((1, 0.0), (2, 90.0))
    selector.observe(True, math.radians(0.0), True, members)
    selector.observe(False, math.radians(0.0), True, members)  # Ausreisser: keine Sprachaktivitaet
    selector.observe(True, math.radians(0.0), True, members)
    result = selector.observe(True, math.radians(0.0), True, members)
    assert result.changed is False  # erst 2 aufeinanderfolgende seit dem Reset


def test_ambiguous_direction_never_selects_a_new_speaker():
    selector = ActiveSpeakerSelector(required_confirming_frames=1, minimum_ambiguity_margin_rad=math.radians(10.0))
    # Zwei Mitglieder fast gleich nah an der gemessenen Richtung.
    members = _members((1, 5.0), (2, -5.0))
    result = selector.observe(True, math.radians(0.0), True, members)
    assert result.changed is False
    assert result.reason == "mehrdeutig"


def test_direction_outside_the_group_never_becomes_the_new_focus():
    selector = ActiveSpeakerSelector(required_confirming_frames=1, maximum_angular_error_rad=math.radians(20.0))
    members = _members((1, 0.0), (2, 90.0))
    # Eine Richtung weit ausserhalb JEDER Gruppenperson.
    result = selector.observe(True, math.radians(179.0), True, members)
    assert result.changed is False
    assert result.reason == "keine_passende_gruppenperson"
    assert result.selected_track_id == -1


def test_switch_to_a_different_member_requires_fresh_confirmations():
    selector = ActiveSpeakerSelector(required_confirming_frames=2)
    members = _members((1, 0.0), (2, 90.0))
    selector.observe(True, math.radians(0.0), True, members)
    result = selector.observe(True, math.radians(0.0), True, members)
    assert result.selected_track_id == 1

    # Sprecher 2 spricht jetzt -- braucht wieder required_confirming_frames.
    r1 = selector.observe(True, math.radians(90.0), True, members)
    assert r1.changed is False
    assert r1.selected_track_id == 1  # weiterhin der ALTE Sprecher, bis bestaetigt
    r2 = selector.observe(True, math.radians(90.0), True, members)
    assert r2.changed is True
    assert r2.selected_track_id == 2


def test_missing_doa_or_empty_group_never_crashes_and_keeps_current_speaker():
    selector = ActiveSpeakerSelector(required_confirming_frames=1)
    members = _members((1, 0.0))
    selector.observe(True, math.radians(0.0), True, members)
    result = selector.observe(True, 0.0, False, members)  # DoA ungueltig
    assert result.reason == "keine_sprachaktivitaet_oder_richtung"
    result2 = selector.observe(True, math.radians(0.0), True, [])  # keine Mitglieder
    assert result2.reason == "keine_sprachaktivitaet_oder_richtung"


def test_clear_resets_the_selector():
    selector = ActiveSpeakerSelector(required_confirming_frames=1)
    members = _members((1, 0.0))
    selector.observe(True, math.radians(0.0), True, members)
    assert selector.current_speaker() == 1
    selector.clear()
    assert selector.current_speaker() == -1


def test_repeatedly_confirming_the_same_speaker_reports_no_change():
    selector = ActiveSpeakerSelector(required_confirming_frames=1)
    members = _members((1, 0.0))
    r1 = selector.observe(True, math.radians(0.0), True, members)
    assert r1.changed is True
    r2 = selector.observe(True, math.radians(0.0), True, members)
    assert r2.changed is False
    assert r2.selected_track_id == 1
