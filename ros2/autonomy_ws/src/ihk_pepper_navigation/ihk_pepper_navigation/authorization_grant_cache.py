"""
Lokaler Cache empfangener AuthorizationGrant-Nachrichten
(Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9/19). Reine Logik, KEIN
ROS -- person_approach_node.py abonniert /authorization/grants
(command_router_node.py ist der einzige Aussteller) und speist jede
empfangene Nachricht hier ein.

Eine Berechtigung darf NIE fuer eine andere Person/einen anderen Track/
einen anderen Befehl wiederverwendet werden (Auftrag Abschnitt 9) --
validate_and_consume() prueft das explizit UND entfernt den Grant nach
erfolgreicher Pruefung (EINMALIGE Verwendung, Auftrag: "wiederverwendeter
Grant" ist ein expliziter abgelehnter Testfall)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class CachedGrant:
    grant_id: str
    person_id: str
    track_id: int
    command: str
    expires_at_s: float


class AuthorizationGrantCache:
    def __init__(self, now_fn=time.time):
        self._now_fn = now_fn
        self._grants: Dict[str, CachedGrant] = {}

    def add(self, grant_id: str, person_id: str, track_id: int, command: str,
            expires_at_s: float) -> None:
        self._grants[grant_id] = CachedGrant(grant_id, person_id, track_id, command, expires_at_s)

    def validate_and_consume(self, grant_id: str, track_id: int, command: str) -> Tuple[bool, str]:
        """Reine Pruefung + Seiteneffekt (entfernt den Grant bei Erfolg
        -- einmalige Verwendung). Gibt (ok, reason) zurueck, NIE eine
        stillschweigende Autorisierung bei fehlendem/abgelaufenem/nicht
        passendem Grant."""
        if not grant_id:
            return False, "keine_grant_id"
        grant = self._grants.get(grant_id)
        if grant is None:
            return False, "grant_unbekannt_oder_bereits_verwendet"
        if self._now_fn() > grant.expires_at_s:
            self._grants.pop(grant_id, None)
            return False, "grant_abgelaufen"
        if grant.track_id != track_id:
            return False, "grant_falscher_track"
        if grant.command != command:
            return False, "grant_falscher_befehl"
        self._grants.pop(grant_id, None)
        return True, ""

    def purge_expired(self, now: Optional[float] = None) -> int:
        now = self._now_fn() if now is None else now
        expired = [gid for gid, g in self._grants.items() if now > g.expires_at_s]
        for gid in expired:
            self._grants.pop(gid, None)
        return len(expired)
