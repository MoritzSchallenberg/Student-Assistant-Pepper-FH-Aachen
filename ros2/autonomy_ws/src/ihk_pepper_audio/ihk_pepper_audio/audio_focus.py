"""
Gespraechsbezogene Audiofokussierung -- reine, ROS-freie Zustandsmaschine
(Entwicklungsauftrag 04-B, AP6, Abschnitt 10). Verwaltet NUR den
Zustand/die Zielrichtung, fuehrt selbst KEINE Audioverarbeitung durch --
DirectionalAudioBackend liefert weiterhin die eigentliche Richtungs-/
Pegelschaetzung (siehe directional_audio.py), diese Klasse entscheidet
nur, OB/WELCHE Person aktuell der Zielfokus ist und wann er verloren
geht.

Zustaende (Auftrag Abschnitt 10):
IDLE_WIDE -> WAKEWORD_DETECTED -> ORIENTING_TO_SOUND ->
VISUAL_CONFIRMATION -> CONVERSATION_FOCUS <-> PEPPER_SPEAKING ->
RETURNING_TO_IDLE -> (zurueck zu IDLE_WIDE). AUDIO_DEGRADED ist ein
Nebenzustand -- wird gesetzt, wenn die Zielperson laenger als
target_loss_timeout_s nicht mehr aktualisiert wurde, WAEHREND
CONVERSATION_FOCUS/PEPPER_SPEAKING aktiv war (fail-closed: kein
falsches Fortsetzen eines Gespraechs mit einer verschwundenen Person,
siehe snapshot().valid).

EHRLICHER STAND: diese Klasse implementiert die vollstaendige
Zustandsmaschine und ist vollstaendig unit-getestet. Der ROS-Wrapper
(audio_focus_node.py) treibt sie aktuell nur ueber die Signale, die
bereits auf Topics verfuegbar sind (WakewordEvent, /pepper_bridge/speaking,
/interaction_state) -- die BT-internen Zwischenschritte
(OrientToSound-Erfolg, FindPersonNearSoundRay-Bestaetigung) sind noch
NICHT als eigene Topics sichtbar, daher bleiben on_person_confirmed()/
on_target_track_update() vorbereitet, aber im aktuellen Node noch nicht
automatisch angebunden (siehe docs/AUDIO_FOCUS_AND_BEAMFORMING.md fuer
den genauen Stand und den empfohlenen naechsten Schritt)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class AudioFocusMode(str, Enum):
    IDLE_WIDE = "IDLE_WIDE"
    WAKEWORD_DETECTED = "WAKEWORD_DETECTED"
    ORIENTING_TO_SOUND = "ORIENTING_TO_SOUND"
    VISUAL_CONFIRMATION = "VISUAL_CONFIRMATION"
    CONVERSATION_FOCUS = "CONVERSATION_FOCUS"
    PEPPER_SPEAKING = "PEPPER_SPEAKING"
    RETURNING_TO_IDLE = "RETURNING_TO_IDLE"
    AUDIO_DEGRADED = "AUDIO_DEGRADED"


@dataclass(frozen=True)
class AudioFocusStateData:
    mode: AudioFocusMode
    selected_track_id: int
    target_azimuth_rad: float
    valid: bool
    reason: str = ""


class AudioFocusStateMachine:
    """now_fn injizierbar (gleiches Muster wie
    ActuatorArbiter(now_fn=time.monotonic)), damit Timeout-Logik in
    Tests ohne echtes Warten pruefbar ist."""

    def __init__(
        self,
        target_loss_timeout_s: float = 2.0,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        self.target_loss_timeout_s = target_loss_timeout_s
        self._now_fn = now_fn
        self._mode = AudioFocusMode.IDLE_WIDE
        self._selected_track_id = -1
        self._target_azimuth_rad = 0.0
        self._last_target_update: Optional[float] = None

    @property
    def mode(self) -> AudioFocusMode:
        return self._mode

    def on_wakeword_detected(self, azimuth_rad: float) -> None:
        if self._mode != AudioFocusMode.IDLE_WIDE:
            return  # Abschnitt 8: kein Unterbrechen einer laufenden Interaktion
        self._mode = AudioFocusMode.WAKEWORD_DETECTED
        self._target_azimuth_rad = azimuth_rad

    def on_orientation_started(self) -> None:
        if self._mode == AudioFocusMode.WAKEWORD_DETECTED:
            self._mode = AudioFocusMode.ORIENTING_TO_SOUND

    def on_orientation_failed(self, reason: str = "") -> None:
        if self._mode in (AudioFocusMode.WAKEWORD_DETECTED, AudioFocusMode.ORIENTING_TO_SOUND):
            self._mode = AudioFocusMode.RETURNING_TO_IDLE

    def on_visual_confirmation_started(self) -> None:
        if self._mode == AudioFocusMode.ORIENTING_TO_SOUND:
            self._mode = AudioFocusMode.VISUAL_CONFIRMATION

    def on_person_confirmed(self, track_id: int, azimuth_rad: float) -> None:
        self._mode = AudioFocusMode.CONVERSATION_FOCUS
        self._selected_track_id = track_id
        self._target_azimuth_rad = azimuth_rad
        self._last_target_update = self._now_fn()

    def on_person_not_confirmed(self, reason: str = "") -> None:
        if self._mode == AudioFocusMode.VISUAL_CONFIRMATION:
            self._mode = AudioFocusMode.RETURNING_TO_IDLE

    def on_target_track_update(self, track_id: int, azimuth_rad: float) -> bool:
        """Aktualisiert die Zielrichtung, WENN track_id noch der aktuell
        ausgewaehlten Person entspricht. Gibt False zurueck (ignoriert
        das Update), wenn eine ANDERE Person gemeldet wird -- verhindert,
        dass ein fremder Track versehentlich zum neuen Fokus wird."""
        if track_id != self._selected_track_id:
            return False
        self._target_azimuth_rad = azimuth_rad
        self._last_target_update = self._now_fn()
        if self._mode == AudioFocusMode.AUDIO_DEGRADED:
            self._mode = AudioFocusMode.CONVERSATION_FOCUS
        return True

    def on_pepper_speaking_changed(self, speaking: bool) -> None:
        if speaking and self._mode == AudioFocusMode.CONVERSATION_FOCUS:
            self._mode = AudioFocusMode.PEPPER_SPEAKING
        elif not speaking and self._mode == AudioFocusMode.PEPPER_SPEAKING:
            self._mode = AudioFocusMode.CONVERSATION_FOCUS

    def on_conversation_ended(self) -> None:
        self._mode = AudioFocusMode.RETURNING_TO_IDLE

    def tick(self) -> None:
        """Regelmaessig aufzurufen (unabhaengig von einzelnen
        Ereignissen) -- prueft Timeouts und schliesst RETURNING_TO_IDLE
        endgueltig ab."""
        now = self._now_fn()
        if self._mode in (AudioFocusMode.CONVERSATION_FOCUS, AudioFocusMode.PEPPER_SPEAKING):
            if (self._last_target_update is not None
                    and (now - self._last_target_update) > self.target_loss_timeout_s):
                self._mode = AudioFocusMode.AUDIO_DEGRADED
        elif self._mode == AudioFocusMode.AUDIO_DEGRADED:
            if (self._last_target_update is not None
                    and (now - self._last_target_update) > self.target_loss_timeout_s * 2):
                # Person seit sehr langer Zeit verloren -- endgueltig
                # zurueck zu Idle, kein ewiges "degraded" haengen bleiben.
                self._mode = AudioFocusMode.RETURNING_TO_IDLE
        elif self._mode == AudioFocusMode.RETURNING_TO_IDLE:
            self._mode = AudioFocusMode.IDLE_WIDE
            self._selected_track_id = -1
            self._target_azimuth_rad = 0.0
            self._last_target_update = None

    def snapshot(self) -> AudioFocusStateData:
        valid = self._mode in (AudioFocusMode.CONVERSATION_FOCUS, AudioFocusMode.PEPPER_SPEAKING)
        reason = "degraded_target_lost" if self._mode == AudioFocusMode.AUDIO_DEGRADED else ""
        return AudioFocusStateData(
            mode=self._mode, selected_track_id=self._selected_track_id,
            target_azimuth_rad=self._target_azimuth_rad, valid=valid, reason=reason,
        )
