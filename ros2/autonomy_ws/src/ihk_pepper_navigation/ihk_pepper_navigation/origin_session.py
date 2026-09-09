"""
Sitzungsgebundene Ursprungspose (Entwicklungsauftrag 04-B, AP7,
Abschnitt 9/12). Reine Logik, KEIN ROS -- person_approach_node.py ruft
capture()/validate() ueber den CaptureOrigin-Service bzw. die
ReturnToOrigin-Action auf.

Bewusst NUR im Prozessspeicher (kein Persistieren ueber einen Neustart
hinaus, siehe Auftrag: "Ursprung ist ausschliesslich sitzungsgebunden") --
ein Neustart des Nodes bedeutet zwangslaeufig auch das Ende jeder
laufenden Sitzung.

Ungueltigkeitsregeln (Auftrag Abschnitt 12 "Ursprungsinvalidierung"):
Kartenwechsel und neu initialisierte Lokalisierung invalidieren ALLE
gespeicherten Urspruenge global (invalidate_all(), von
person_approach_node.py bei /mapping_active False->True bzw.
localization_valid False->True aufgerufen) -- ein einzelner Ursprung
kann sich nicht selbst als "noch im selben Koordinatensystem gueltig"
bestaetigen. Sitzungsende invalidiert nur die eigenen Urspruenge
(invalidate_session()). Veraltung wird NICHT hier, sondern bei jeder
validate()-Pruefung ueber max_age_s durchgesetzt (Ablaufzeitpunkt haengt
vom Aufrufer/Goal ab, nicht vom Speicher selbst)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class OriginRecord:
    origin_id: str
    session_id: str
    frame_id: str
    x: float
    y: float
    yaw_rad: float
    captured_at_s: float
    initial_track_id: int
    person_id: str = ""
    group_id: str = ""


class OriginStore:
    def __init__(self, now_fn=time.time):
        self._now_fn = now_fn
        self._origins: Dict[str, OriginRecord] = {}

    def capture(
        self, session_id: str, frame_id: str, x: float, y: float, yaw_rad: float,
        initial_track_id: int, person_id: str = "", group_id: str = "",
    ) -> OriginRecord:
        record = OriginRecord(
            origin_id=str(uuid.uuid4()), session_id=session_id, frame_id=frame_id,
            x=x, y=y, yaw_rad=yaw_rad, captured_at_s=self._now_fn(),
            initial_track_id=initial_track_id, person_id=person_id, group_id=group_id,
        )
        self._origins[record.origin_id] = record
        return record

    def get(self, origin_id: str) -> Optional[OriginRecord]:
        return self._origins.get(origin_id)

    def validate(
        self, origin_id: str, session_id: str, max_age_s: float,
    ) -> Tuple[bool, str, Optional[OriginRecord]]:
        """Reine Pruefung, kein Seiteneffekt (im Unterschied zu
        AuthorizationGrantCache.validate_and_consume() wird ein Ursprung
        NICHT verbraucht -- ReturnToOrigin kann mehrfach angefragt
        werden, z.B. nach einem abgebrochenen ersten Versuch)."""
        record = self._origins.get(origin_id)
        if record is None:
            return False, "ursprung_unbekannt", None
        if record.session_id != session_id:
            return False, "ursprung_gehoert_anderer_sitzung", None
        if max_age_s > 0.0 and (self._now_fn() - record.captured_at_s) > max_age_s:
            return False, "ursprung_veraltet", None
        return True, "", record

    def invalidate_session(self, session_id: str) -> int:
        stale_ids = [oid for oid, r in self._origins.items() if r.session_id == session_id]
        for oid in stale_ids:
            del self._origins[oid]
        return len(stale_ids)

    def invalidate_all(self) -> int:
        """Kartenwechsel/neu initialisierte Lokalisierung (Auftrag
        Abschnitt 12) -- JEDER gespeicherte Ursprung koennte sich auf ein
        nicht mehr gueltiges Koordinatensystem beziehen, daher global statt
        sitzungsweise."""
        count = len(self._origins)
        self._origins.clear()
        return count
