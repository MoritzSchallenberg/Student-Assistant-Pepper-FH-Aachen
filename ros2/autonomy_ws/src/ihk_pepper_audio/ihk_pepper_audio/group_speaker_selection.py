"""
Aktive-Sprecher-Auswahl innerhalb einer bestaetigten Gesprächsgruppe
(Entwicklungsauftrag 04-B, AP7, Abschnitt 17). Reine Zustandsmaschine,
KEIN ROS -- vergleicht eine gemessene Schallrichtung AUSSCHLIESSLICH
gegen die Peilungen bereits bestaetigter Gruppenmitglieder (siehe
group_tracking.py) -- eine fremde Richtung ausserhalb der Gruppe kann
dadurch strukturell NIE zum neuen Fokus werden.

Ein Sprecherwechsel braucht (Auftrag Abschnitt 17): aktuelle
Sprachaktivitaet, passende DoA, mehrere BESTAETIGENDE Audioframes,
ausreichenden Abstand zum zweitbesten Kandidaten -- ein einzelner
passender Frame reicht NIE (gleiches Prinzip wie
persistent_identity_confirmer.py). Bei Mehrdeutigkeit bleibt der
BISHERIGE aktive Sprecher bestehen (Steering wechselt nicht blind),
der Aufrufer bekommt aber reason="mehrdeutig" zurueck, um diese
Aeusserung NICHT personenbezogen zu speichern (Auftrag: "der Dialog
darf fortgesetzt werden, aber keine personenbezogene Erinnerung
zugeordnet werden")."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class GroupMemberBearing:
    track_id: int
    bearing_rad: float


@dataclass(frozen=True)
class SpeakerSelectionResult:
    # -1 = noch kein aktiver Sprecher bestaetigt.
    selected_track_id: int
    changed: bool
    reason: str = ""


def _angle_diff_rad(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


class ActiveSpeakerSelector:
    def __init__(
        self,
        maximum_angular_error_rad: float = math.radians(20.0),
        minimum_ambiguity_margin_rad: float = math.radians(10.0),
        required_confirming_frames: int = 3,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        self.maximum_angular_error_rad = maximum_angular_error_rad
        self.minimum_ambiguity_margin_rad = minimum_ambiguity_margin_rad
        self.required_confirming_frames = required_confirming_frames
        self._now_fn = now_fn
        self._current_speaker_track_id = -1
        self._candidate_track_id = -1
        self._candidate_streak = 0

    def observe(
        self,
        vad_active: bool,
        doa_azimuth_rad: float,
        doa_valid: bool,
        members: List[GroupMemberBearing],
    ) -> SpeakerSelectionResult:
        """EIN Aufruf pro neuem Audioframe/DoA-Sample. members: NUR
        bestaetigte, aktuell sichtbare Gruppenmitglieder -- ein Kandidat
        ausserhalb dieser Liste kann nie gewinnen."""
        if not vad_active or not doa_valid or not members:
            self._candidate_track_id = -1
            self._candidate_streak = 0
            return SpeakerSelectionResult(
                self._current_speaker_track_id, False, "keine_sprachaktivitaet_oder_richtung")

        scored = sorted(
            ((m.track_id, _angle_diff_rad(m.bearing_rad, doa_azimuth_rad)) for m in members),
            key=lambda item: item[1],
        )
        best_id, best_err = scored[0]
        if best_err > self.maximum_angular_error_rad:
            self._candidate_track_id = -1
            self._candidate_streak = 0
            return SpeakerSelectionResult(
                self._current_speaker_track_id, False, "keine_passende_gruppenperson")

        if len(scored) > 1:
            _second_id, second_err = scored[1]
            if (second_err - best_err) < self.minimum_ambiguity_margin_rad:
                self._candidate_track_id = -1
                self._candidate_streak = 0
                return SpeakerSelectionResult(self._current_speaker_track_id, False, "mehrdeutig")

        if best_id == self._current_speaker_track_id:
            self._candidate_track_id = -1
            self._candidate_streak = 0
            return SpeakerSelectionResult(self._current_speaker_track_id, False, "")

        if best_id != self._candidate_track_id:
            self._candidate_track_id = best_id
            self._candidate_streak = 1
        else:
            self._candidate_streak += 1

        if self._candidate_streak >= self.required_confirming_frames:
            self._current_speaker_track_id = best_id
            self._candidate_track_id = -1
            self._candidate_streak = 0
            return SpeakerSelectionResult(best_id, True, "")

        return SpeakerSelectionResult(self._current_speaker_track_id, False, "sammle_bestaetigungen")

    def current_speaker(self) -> int:
        return self._current_speaker_track_id

    def clear(self) -> None:
        self._current_speaker_track_id = -1
        self._candidate_track_id = -1
        self._candidate_streak = 0
