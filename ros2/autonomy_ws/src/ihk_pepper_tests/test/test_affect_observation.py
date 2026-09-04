import time

from ihk_pepper_person_memory.affect_observation import (
    AffectObservation,
    IdentityObservation,
    PersonContext,
)


def test_affect_observation_is_never_a_reliable_fact():
    obs = AffectObservation(
        label="happy", confidence=0.9,
        observed_at_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        source="pepper_mood_api",
    )
    assert obs.is_reliable_fact() is False


def test_affect_observation_age_s_computes_elapsed_time():
    past = time.gmtime(time.time() - 30)
    obs = AffectObservation(
        label="neutral", confidence=0.5,
        observed_at_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", past),
        source="pepper_mood_api",
    )
    assert obs.age_s() >= 29.0


def test_affect_observation_high_confidence_still_not_a_fact():
    obs = AffectObservation(
        label="happy", confidence=1.0, observed_at_iso="2026-09-04T10:00:00Z",
        source="future_vision_model",
    )
    assert obs.is_reliable_fact() is False


def test_identity_observation_never_carries_implicit_confirmation():
    obs = IdentityObservation(track_id=42, confidence=0.95, observed_at_iso="2026-09-04T10:00:00Z")
    assert obs.confirmed_person_id is None


def test_person_context_defaults_to_unknown():
    ctx = PersonContext()
    assert ctx.known is False
    assert ctx.person_id is None
    assert ctx.latest_affect is None


def test_person_context_can_carry_latest_affect():
    affect = AffectObservation(
        label="curious", confidence=0.4, observed_at_iso="2026-09-04T10:00:00Z",
        source="pepper_mood_api", track_id=7,
    )
    ctx = PersonContext(known=True, display_name="Max", person_id="p1", latest_affect=affect)
    assert ctx.latest_affect.is_reliable_fact() is False
