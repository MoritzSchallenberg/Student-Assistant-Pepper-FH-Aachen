from ihk_pepper_interaction.interaction_state import InteractionStateMachine, InteractionState


def test_idle_to_attract_to_engaged():
    sm = InteractionStateMachine(attract_interest_threshold=0.5, engage_interest_threshold=0.7)
    assert sm.state == InteractionState.IDLE
    sm.on_person_tracks(0.6)
    assert sm.state == InteractionState.ATTRACT
    sm.on_person_tracks(0.8)
    assert sm.state == InteractionState.ENGAGED


def test_attract_times_out_back_to_idle():
    sm = InteractionStateMachine(attract_interest_threshold=0.5, engage_interest_threshold=0.7,
                                  attract_timeout_s=5.0)
    sm.on_person_tracks(0.6, now=100.0)
    assert sm.state == InteractionState.ATTRACT
    sm.on_person_tracks(0.0, now=107.0)  # 7s spaeter, kein Interesse mehr
    assert sm.state == InteractionState.IDLE


def test_safety_event_from_any_state_goes_to_safe_stop():
    sm = InteractionStateMachine()
    # IDLE->ENGAGED braucht zwei Aufrufe: der erste hebt nur nach ATTRACT,
    # selbst bei einem sehr hohen Score (siehe on_person_tracks-Logik --
    # bewusst so: jede Person bekommt zuerst den "ich hab dich bemerkt"-
    # Zustand, auch bei eindeutigem Interesse im allerersten Frame).
    sm.on_person_tracks(0.9)
    assert sm.state == InteractionState.ATTRACT
    sm.on_person_tracks(0.9)
    assert sm.state == InteractionState.ENGAGED
    sm.trigger_safety_event()
    assert sm.state == InteractionState.SAFE_STOP


def test_safe_stop_ignores_further_interest_signals():
    sm = InteractionStateMachine()
    sm.trigger_safety_event()
    sm.on_person_tracks(1.0)
    assert sm.state == InteractionState.SAFE_STOP


def test_clear_safety_event_returns_to_idle():
    sm = InteractionStateMachine()
    sm.trigger_safety_event()
    sm.clear_safety_event()
    assert sm.state == InteractionState.IDLE
