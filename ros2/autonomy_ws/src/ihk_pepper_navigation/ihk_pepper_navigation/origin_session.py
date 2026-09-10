"""
Sitzungsgebundene Ursprungspose (Entwicklungsauftrag 04-B, AP7,
Abschnitt 9/12; erweitert in AP7.1, Abschnitt 3.4/16). Reine Logik, KEIN
ROS -- person_approach_node.py ruft capture()/validate() ueber den
CaptureOrigin-Service bzw. die ReturnToOrigin-Action auf.

Bewusst NUR im Prozessspeicher (kein Persistieren ueber einen Neustart
hinaus, siehe Auftrag: "Ursprung ist ausschliesslich sitzungsgebunden") --
ein Neustart des Nodes bedeutet zwangslaeufig auch das Ende jeder
laufenden Sitzung.

Ungueltigkeitsregeln (Auftrag Abschnitt 12 "Ursprungsinvalidierung",
AP7.1 Abschnitt 16 "Bindungsregeln fuer Ursprungspunkte"):
- Kartenwechsel/neu initialisierte Lokalisierung invalidieren ALLE
  gespeicherten Urspruenge global (invalidate_all(), von
  person_approach_node.py bei /mapping_active False->True bzw.
  localization_valid False->True aufgerufen) -- ein einzelner Ursprung
  kann sich nicht selbst als "noch im selben Koordinatensystem gueltig"
  bestaetigen. ZUSAETZLICH (AP7.1): jeder Aufruf von invalidate_all()
  erhoeht einen monotonen map_generation_id-Zaehler; validate() prueft
  diesen Zaehler EXPLIZIT gegen den zum Erfassungszeitpunkt gespeicherten
  Wert -- Verteidigung in der Tiefe, falls ein kuenftiger Aufrufer
  invalidate_all() je nicht mehr zuverlaessig VOR jeder validate()-
  Pruefung aufruft. EHRLICHER HINWEIS: es gibt in dieser Sitzung KEINEN
  echten Kartenserver/keine echte Karten-ID (kein RTAB-Map/map_server
  angebunden) -- map_generation_id ist deshalb ein reiner, lokaler
  Generationszaehler dieses Prozesses, KEINE echte Karten-ID. Ein
  Neustart des Nodes bedeutet ohnehin das Ende jeder Sitzung (siehe
  oben), daher ist ein prozessweiter Zaehler fuer diesen Zweck
  ausreichend.
- Sitzungsende invalidiert nur die eigenen Urspruenge
  (invalidate_session()).
- Veraltung wird NICHT hier, sondern bei jeder validate()-Pruefung ueber
  max_age_s durchgesetzt (Ablaufzeitpunkt haengt vom Aufrufer/Goal ab,
  nicht vom Speicher selbst).
- AP7.1, Abschnitt 3.4: "ein alter/fremder Origin darf NIE fuer eine neue
  Interaktion wiederverwendet werden" -- zusaetzlich zu session_id wird
  jetzt optional eine interaction_id gebunden (Art der Interaktion, z.B.
  "single_person_conversation"/"authorized_follow", NICHT zwangslaeufig
  eine pro Instanz eindeutige ID -- die Instanz-Eindeutigkeit liefert
  bereits session_id). validate() lehnt ab, wenn eine uebergebene
  interaction_id nicht mit der beim capture() hinterlegten
  uebereinstimmt -- ein Ursprung aus einer Follow-Sitzung kann so NIE
  faelschlich fuer eine Einzelgespraechs-Rueckkehr (oder umgekehrt)
  verwendet werden, selbst wenn (theoretisch) dieselbe session_id
  wiederverwendet wuerde."""
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
    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 3.4: Art der Interaktion
    # (z.B. "single_person_conversation"/"authorized_follow"), Grund
    # sowie die Karten-Generation zum Erfassungszeitpunkt -- siehe
    # Moduldoku oben.
    interaction_id: str = ""
    reason: str = ""
    map_generation_id: int = 0


class OriginStore:
    def __init__(self, now_fn=time.time):
        self._now_fn = now_fn
        self._origins: Dict[str, OriginRecord] = {}
        self._map_generation_id = 0

    def capture(
        self, session_id: str, frame_id: str, x: float, y: float, yaw_rad: float,
        initial_track_id: int, person_id: str = "", group_id: str = "",
        interaction_id: str = "", reason: str = "",
    ) -> OriginRecord:
        record = OriginRecord(
            origin_id=str(uuid.uuid4()), session_id=session_id, frame_id=frame_id,
            x=x, y=y, yaw_rad=yaw_rad, captured_at_s=self._now_fn(),
            initial_track_id=initial_track_id, person_id=person_id, group_id=group_id,
            interaction_id=interaction_id, reason=reason,
            map_generation_id=self._map_generation_id,
        )
        self._origins[record.origin_id] = record
        return record

    def get(self, origin_id: str) -> Optional[OriginRecord]:
        return self._origins.get(origin_id)

    def validate(
        self, origin_id: str, session_id: str, max_age_s: float, interaction_id: str = "",
    ) -> Tuple[bool, str, Optional[OriginRecord]]:
        """Reine Pruefung, kein Seiteneffekt (im Unterschied zu
        AuthorizationGrantCache.validate_and_consume() wird ein Ursprung
        NICHT verbraucht -- ReturnToOrigin kann mehrfach angefragt
        werden, z.B. nach einem abgebrochenen ersten Versuch).
        interaction_id="" (Standard) bedeutet "keine Interaktionsbindung
        pruefen" -- bestehende Aufrufer, die (noch) keine interaction_id
        fuehren, bleiben dadurch unveraendert funktionsfaehig."""
        record = self._origins.get(origin_id)
        if record is None:
            return False, "ursprung_unbekannt", None
        if record.session_id != session_id:
            return False, "ursprung_gehoert_anderer_sitzung", None
        if interaction_id and record.interaction_id and record.interaction_id != interaction_id:
            return False, "ursprung_gehoert_anderer_interaktion", None
        if record.map_generation_id != self._map_generation_id:
            # Verteidigung in der Tiefe -- invalidate_all() loescht
            # betroffene Urspruenge bereits vollstaendig, dieser Zweig
            # sollte daher in der Praxis nie erreicht werden.
            return False, "karte_hat_sich_geaendert", None
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
        sitzungsweise. Erhoeht zusaetzlich map_generation_id (AP7.1)."""
        count = len(self._origins)
        self._origins.clear()
        self._map_generation_id += 1
        return count
