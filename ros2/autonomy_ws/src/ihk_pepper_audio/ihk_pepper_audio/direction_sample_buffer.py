"""
DirectionSampleBuffer: begrenzter Zeitpuffer fuer Richtungsproben
(Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5). Reine, ROS-freie Logik.

Ersetzt die bisherige globale "letzte Richtung"-Variable (`audio_node.py::
_latest_direction`), die eine Richtung mit einer nicht zugehoerigen
Wakeword-Aufnahme kombinieren konnte -- jede Richtungsprobe gehoert
jetzt zu genau einem Zeitstempel (`monotonic_stamp_s`), ein Wakeword-
Ereignis waehlt gezielt NUR Proben aus seinem eigenen
Aeusserungs-Zeitfenster, nie die zufaellig "letzte" Probe.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TimedDirectionSample:
    ros_stamp_ns: int
    monotonic_stamp_s: float
    frame_id: str
    azimuth_rad: float
    confidence: float
    valid: bool


class DirectionSampleBuffer:
    """now_fn injizierbar (gleiches Muster wie ActuatorArbiter/
    WakewordGate), damit Alterungslogik in Tests ohne echtes Warten
    pruefbar ist."""

    def __init__(self, max_duration_s: float = 3.0, now_fn=time.monotonic):
        self.max_duration_s = max_duration_s
        self._now_fn = now_fn
        self._samples: "deque[TimedDirectionSample]" = deque()

    def push(self, sample: TimedDirectionSample) -> bool:
        """Gibt False zurueck (verwirft die Probe stillschweigend), wenn
        Azimut/Konfidenz nicht endlich sind oder der Winkel außerhalb
        von [-pi, pi] liegt -- NaN/Inf/unsinnige Werte duerfen nie in
        den Puffer gelangen."""
        if not math.isfinite(sample.azimuth_rad) or not math.isfinite(sample.confidence):
            return False
        if not (-math.pi <= sample.azimuth_rad <= math.pi):
            return False
        self._samples.append(sample)
        self._evict_old()
        return True

    def _evict_old(self) -> None:
        now = self._now_fn()
        while self._samples and (now - self._samples[0].monotonic_stamp_s) > self.max_duration_s:
            self._samples.popleft()

    def select_for_window(
        self,
        window_start_monotonic_s: float,
        window_end_monotonic_s: float,
        min_confidence: float = 0.0,
    ) -> Optional[TimedDirectionSample]:
        """Waehlt alle GUELTIGEN Proben, deren monotonic_stamp_s im
        angegebenen Fenster liegt, und fuehrt sie ueber einen
        zirkulaeren, konfidenzgewichteten Mittelwert zusammen (robust
        gegen den +-pi-Uebergang, anders als ein naiver arithmetischer
        Mittelwert). Gibt None zurueck, wenn keine passende Probe
        existiert -- der Aufrufer MUSS das als "keine gueltige Richtung"
        behandeln, nie einen Ersatzwert erfinden."""
        self._evict_old()
        candidates = [
            s for s in self._samples
            if s.valid
            and window_start_monotonic_s <= s.monotonic_stamp_s <= window_end_monotonic_s
            and s.confidence >= min_confidence
        ]
        if not candidates:
            return None

        sin_sum = sum(math.sin(s.azimuth_rad) * s.confidence for s in candidates)
        cos_sum = sum(math.cos(s.azimuth_rad) * s.confidence for s in candidates)
        if sin_sum == 0.0 and cos_sum == 0.0:
            # Alle Konfidenzen 0, oder die Winkel heben sich exakt auf --
            # kein belastbarer gewichteter Mittelwert moeglich.
            return None
        azimuth = math.atan2(sin_sum, cos_sum)
        confidence = sum(s.confidence for s in candidates) / len(candidates)
        latest = max(candidates, key=lambda s: s.monotonic_stamp_s)
        return TimedDirectionSample(
            ros_stamp_ns=latest.ros_stamp_ns,
            monotonic_stamp_s=latest.monotonic_stamp_s,
            frame_id=latest.frame_id,
            azimuth_rad=azimuth,
            confidence=confidence,
            valid=True,
        )

    def __len__(self) -> int:
        return len(self._samples)
