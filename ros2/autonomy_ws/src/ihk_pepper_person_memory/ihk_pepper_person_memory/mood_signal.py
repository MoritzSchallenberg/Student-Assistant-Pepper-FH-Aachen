"""
Vertrag fuer Stimmungs-/Emotionssignale (Entwicklungsauftrag 1,
Abschnitt 9): IMMER ein unsicheres Beobachtungssignal mit Konfidenz und
Zeitstempel, NIE eine Tatsache oder dauerhafte Eigenschaft einer Person.
Der vorhandene Code (apps/web/pepper/qicli.py::get_mood/get_robot_mood)
liefert bereits Rohwerte -- dieser Vertrag ist die Huelle, die spaeter
verhindert, dass so ein Wert als gesicherte Tatsache weitergereicht wird.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MoodObservation:
    label: str  # z.B. Rohwert aus qicli.get_mood()/get_robot_mood()
    confidence: float
    observed_at_iso: str
    person_id: Optional[str] = None  # nur wenn eine Identity-Zuordnung vorliegt

    def is_usable_as_fact(self) -> bool:
        """Absichtlich IMMER False -- macht explizit, dass eine
        Stimmungsbeobachtung in dieser Architektur nie als Tatsache
        (z.B. in einem ResponsePlan als 'Quelle') behandelt werden darf."""
        return False
