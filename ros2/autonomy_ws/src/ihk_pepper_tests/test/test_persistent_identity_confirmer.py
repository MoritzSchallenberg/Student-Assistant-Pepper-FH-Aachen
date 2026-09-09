"""
Tests fuer persistent_identity_confirmer.py (Entwicklungsauftrag 04-B,
AP7, Abschnitt 7).
"""
from ihk_pepper_identity.identity_matching import IdentityMatchResult
from ihk_pepper_identity.persistent_identity_confirmer import PersistentIdentityConfirmer


def _match(person_id, matched=True):
    return IdentityMatchResult(person_id=person_id, matched=matched, similarity=0.9, margin=0.2)


def test_single_match_does_not_confirm():
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=3)
    assert confirmer.observe_match(1, _match("p1")) is False
    assert confirmer.is_confirmed(1) is False


def test_three_consecutive_matches_confirm():
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=3)
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    result = confirmer.observe_match(1, _match("p1"))
    assert result is True
    assert confirmer.is_confirmed(1) is True
    assert confirmer.confirmed_person_id(1) == "p1"


def test_a_single_non_match_resets_the_streak():
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=3)
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match(None, matched=False))  # ein Ausreisser
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    assert confirmer.is_confirmed(1) is False  # erst 2 aufeinanderfolgende seit dem Reset


def test_switching_person_id_resets_the_streak():
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=3)
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p2"))  # andere Person auf demselben Track
    confirmer.observe_match(1, _match("p2"))
    assert confirmer.is_confirmed(1) is False


def test_confirmation_expires_after_validity_window():
    fake_time = [0.0]
    confirmer = PersistentIdentityConfirmer(
        required_consecutive_matches=2, confirmation_validity_s=5.0, now_fn=lambda: fake_time[0])
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    assert confirmer.is_confirmed(1) is True
    fake_time[0] = 10.0
    assert confirmer.is_confirmed(1) is False


def test_different_tracks_are_independent():
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=2)
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(2, _match("p2"))
    assert confirmer.is_confirmed(1) is True
    assert confirmer.is_confirmed(2) is False


def test_clear_track_removes_confirmation():
    confirmer = PersistentIdentityConfirmer(required_consecutive_matches=2)
    confirmer.observe_match(1, _match("p1"))
    confirmer.observe_match(1, _match("p1"))
    assert confirmer.is_confirmed(1) is True
    confirmer.clear_track(1)
    assert confirmer.is_confirmed(1) is False


def test_unknown_track_is_never_confirmed():
    confirmer = PersistentIdentityConfirmer()
    assert confirmer.is_confirmed(999) is False
    assert confirmer.confirmed_person_id(999) is None
