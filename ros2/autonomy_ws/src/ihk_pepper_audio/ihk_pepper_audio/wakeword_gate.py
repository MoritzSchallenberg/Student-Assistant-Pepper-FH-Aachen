"""
WakewordGate: reine Logik-Entscheidung, OB aus einer erkannten
Aktivierungswort-Erkennung ein WakewordEvent werden darf
(Entwicklungsauftrag 04-B, AP6, Abschnitt 8). Kein rclpy, keine
Audioverarbeitung selbst -- WakewordDetector (wakeword.py) erkennt das
Keyword selbst, ReSpeakerCoreV2Source/DirectionalAudioBackend liefern
die Richtung, dieses Modul entscheidet nur, ob/als was daraus ein
Ereignis wird (Cooldown/Entprellung, Gespraechszustand, Mindestkonfidenz).

WICHTIG: der tatsaechliche Gespraechszustand (conversation_active) MUSS
vom Aufrufer aus einer ZENTRALEN Quelle abgeleitet werden (Supervisor-/
Dialog-/Interaktionszustand -- siehe audio_node.py, das dafuer
"interaction_state" abonniert). Dieses Modul vertraut dem uebergebenen
Wert, erfindet ihn nicht selbst: "Der aktuelle lokale
_session_active-Mechanismus darf nicht alleinige Wahrheitsquelle
bleiben" (Auftrag Abschnitt 8).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class WakewordEventData:
    event_id: str
    keyword: str
    keyword_confidence: float
    azimuth_rad: float
    direction_confidence: float
    direction_valid: bool
    monotonic_timestamp: float


class WakewordGate:
    """cooldown_s: Mindestabstand zwischen zwei erzeugten Ereignissen
    (Entprellung -- ein "Pepper... Pepper" darf nicht zwei Ereignisse
    binnen Millisekunden ausloesen). now_fn/id_fn injizierbar (gleiches
    Muster wie ActuatorArbiter(now_fn=...)), damit Cooldown-Logik in
    Tests ohne echtes Warten pruefbar ist."""

    def __init__(
        self,
        cooldown_s: float = 3.0,
        now_fn: Callable[[], float] = time.monotonic,
        id_fn: Optional[Callable[[], str]] = None,
    ):
        self.cooldown_s = cooldown_s
        self._now_fn = now_fn
        self._id_fn = id_fn or (lambda: str(uuid.uuid4()))
        self._last_event_monotonic: Optional[float] = None

    def evaluate(
        self,
        keyword_detected: bool,
        keyword_confidence: float,
        conversation_active: bool,
        azimuth_rad: float = 0.0,
        direction_confidence: float = 0.0,
        direction_valid: bool = False,
        min_keyword_confidence: float = 0.5,
    ) -> Optional[WakewordEventData]:
        """Gibt None zurueck, wenn KEIN Ereignis erzeugt werden soll --
        das ist der Normalfall (kein Keyword, zu geringe Konfidenz,
        laufendes Gespraech, oder noch im Cooldown seit dem letzten
        Ereignis)."""
        if not keyword_detected:
            return None
        if keyword_confidence < min_keyword_confidence:
            return None
        if conversation_active:
            # Abschnitt 8: "Ein weiteres 'Pepper' waehrend eines
            # laufenden Gespraechs darf... keine laufende Interaktion
            # unterbrechen."
            return None
        now = self._now_fn()
        if self._last_event_monotonic is not None and (now - self._last_event_monotonic) < self.cooldown_s:
            return None
        self._last_event_monotonic = now
        return WakewordEventData(
            event_id=self._id_fn(), keyword="pepper", keyword_confidence=keyword_confidence,
            azimuth_rad=azimuth_rad, direction_confidence=direction_confidence,
            direction_valid=direction_valid, monotonic_timestamp=now,
        )


def is_event_fresh(event_monotonic_timestamp: float, now: float, max_age_s: float) -> bool:
    """Wiederverwendbare Altersschwelle -- dieselbe Pruefung, die
    OrientToSound/die Behavior-Tree-Knoten spaeter gegen ein empfangenes
    WakewordEvent anwenden (max_measurement_age_s), hier als reine
    Funktion fuer Tests/Wiederverwendung isoliert."""
    return (now - event_monotonic_timestamp) <= max_age_s
