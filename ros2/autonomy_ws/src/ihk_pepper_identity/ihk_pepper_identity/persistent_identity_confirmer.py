"""
Mehrframe-Bestaetigung fuer die persistente Identitaetszuordnung
(Entwicklungsauftrag 04-B, AP7, Abschnitt 7: "Mindestkonfidenz,
Mehrframe-Bestaetigung, Liveness-Pruefung, begrenzte Gueltigkeitsdauer,
mehrdeutige Ergebnisse werden abgelehnt"). Reine Zustandsmaschine PRO
track_id, kein Backend-/DB-/ROS-Zugriff -- now_fn injizierbar (gleiches
Muster wie ActuatorArbiter/AudioFocusStateMachine/WakewordGate).

EIN einzelner uebereinstimmender Frame reicht NIE fuer eine Bestaetigung
-- erst nach required_consecutive_matches AUFEINANDERFOLGENDEN Treffern
fuer DIESELBE person_id gilt ein Track als bestaetigt, und auch dann
nur fuer confirmation_validity_s (danach muss erneut bestaetigt werden,
kein ewiges Vertrauen auf eine einmal getroffene Zuordnung)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass
class _TrackConfirmationState:
    person_id: Optional[str] = None
    consecutive_matches: int = 0
    confirmed: bool = False
    confirmed_at: Optional[float] = None


class PersistentIdentityConfirmer:
    def __init__(
        self,
        required_consecutive_matches: int = 3,
        confirmation_validity_s: float = 30.0,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        self.required_consecutive_matches = required_consecutive_matches
        self.confirmation_validity_s = confirmation_validity_s
        self._now_fn = now_fn
        self._states: Dict[int, _TrackConfirmationState] = {}

    def observe_match(self, track_id: int, match_result) -> bool:
        """match_result: identity_matching.py::IdentityMatchResult (oder
        ein Objekt mit .matched/.person_id). Gibt True zurueck, sobald
        track_id bestaetigt ist. Ein NICHT passender Frame setzt den
        Zaehler fuer diesen Track sofort zurueck -- kein "fast
        bestaetigt"-Zustand, der ueber einen einzelnen Fehlschlag hinweg
        bestehen bleibt."""
        state = self._states.setdefault(track_id, _TrackConfirmationState())
        if not match_result.matched:
            state.consecutive_matches = 0
            state.person_id = None
            state.confirmed = False
            return False
        if state.person_id != match_result.person_id:
            state.person_id = match_result.person_id
            state.consecutive_matches = 1
        else:
            state.consecutive_matches += 1
        if state.consecutive_matches >= self.required_consecutive_matches:
            state.confirmed = True
            state.confirmed_at = self._now_fn()
        return state.confirmed

    def is_confirmed(self, track_id: int) -> bool:
        state = self._states.get(track_id)
        if state is None or not state.confirmed:
            return False
        if self._now_fn() - state.confirmed_at > self.confirmation_validity_s:
            return False
        return True

    def confirmed_person_id(self, track_id: int) -> Optional[str]:
        if not self.is_confirmed(track_id):
            return None
        return self._states[track_id].person_id

    def clear_track(self, track_id: int) -> None:
        self._states.pop(track_id, None)
