"""
Interaktions-Zustandsmaschine (Arbeitspaket 6) -- reine Logik, keine
ROS-Abhaengigkeiten, damit sie isoliert testbar bleibt. supervisor_node.py
bindet das an ROS-Topics/Timer.
"""
import time
from enum import IntEnum


class InteractionState(IntEnum):
    IDLE = 0
    ATTRACT = 1
    ENGAGED = 2
    PRESENTING = 3
    NAVIGATING = 4
    ERROR = 5
    SAFE_STOP = 6


class InteractionStateMachine:
    def __init__(
        self,
        attract_interest_threshold: float = 0.5,
        engage_interest_threshold: float = 0.7,
        engaged_timeout_s: float = 20.0,
        attract_timeout_s: float = 10.0,
    ):
        self.attract_interest_threshold = attract_interest_threshold
        self.engage_interest_threshold = engage_interest_threshold
        self.engaged_timeout_s = engaged_timeout_s
        self.attract_timeout_s = attract_timeout_s

        self.state = InteractionState.IDLE
        self._last_interest_seen_t = None
        self._last_engagement_signal_t = None
        self._state_entered_t = time.time()

    def _transition(self, new_state: InteractionState):
        if new_state != self.state:
            self.state = new_state
            self._state_entered_t = time.time()

    def on_person_tracks(self, max_interest_score: float, now: float = None):
        now = now or time.time()
        if self.state in (InteractionState.ERROR, InteractionState.SAFE_STOP):
            return  # Sicherheitszustaende werden nur explizit verlassen

        if max_interest_score >= self.attract_interest_threshold:
            self._last_interest_seen_t = now
        if max_interest_score >= self.engage_interest_threshold:
            self._last_engagement_signal_t = now

        if self.state == InteractionState.IDLE:
            if max_interest_score >= self.attract_interest_threshold:
                self._transition(InteractionState.ATTRACT)

        elif self.state == InteractionState.ATTRACT:
            if max_interest_score >= self.engage_interest_threshold:
                self._transition(InteractionState.ENGAGED)
            elif self._last_interest_seen_t and (now - self._last_interest_seen_t) > self.attract_timeout_s:
                self._transition(InteractionState.IDLE)

        elif self.state == InteractionState.ENGAGED:
            if self._last_engagement_signal_t and (now - self._last_engagement_signal_t) > self.engaged_timeout_s:
                self._transition(InteractionState.IDLE)

    def on_dialogue_speaking_or_active(self, now: float = None):
        """Vom DialogManager kommt ein Lebenszeichen (Person spricht mit
        Pepper) -- haelt ENGAGED aktiv, verhindert Timeout-Rueckfall."""
        now = now or time.time()
        self._last_engagement_signal_t = now
        if self.state == InteractionState.ATTRACT:
            self._transition(InteractionState.ENGAGED)

    def start_presentation(self):
        if self.state not in (InteractionState.ERROR, InteractionState.SAFE_STOP):
            self._transition(InteractionState.PRESENTING)

    def end_presentation(self):
        if self.state == InteractionState.PRESENTING:
            self._transition(InteractionState.IDLE)

    def start_navigation(self):
        if self.state not in (InteractionState.ERROR, InteractionState.SAFE_STOP):
            self._transition(InteractionState.NAVIGATING)

    def end_navigation(self):
        if self.state == InteractionState.NAVIGATING:
            self._transition(InteractionState.IDLE)

    def trigger_safety_event(self):
        """Jeder Zustand -> SAFE_STOP (Anforderung Abschnitt 6)."""
        self._transition(InteractionState.SAFE_STOP)

    def trigger_critical_error(self):
        """Jeder aktive Zustand -> ERROR."""
        self._transition(InteractionState.ERROR)

    def clear_safety_event(self):
        """Nur explizit, z.B. durch Supervisor/Bediener -- kein
        automatischer Ausstieg aus SAFE_STOP/ERROR."""
        if self.state in (InteractionState.SAFE_STOP, InteractionState.ERROR):
            self._transition(InteractionState.IDLE)
