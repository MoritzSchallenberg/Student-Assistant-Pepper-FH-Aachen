"""
Ereignisgebundene sekundäre Autorisierung (Entwicklungsauftrag 04-B,
AP7.1, Abschnitt 9). ERSETZT die globale
/authorization/secondary_confirmation-Bool-Nachricht -- eine einzelne
geteilte Bool-Nachricht kann strukturell NICHT beweisen, welche
Person/welcher Track/welcher Befehl/welche Sitzung bestätigt wurde, ob
die Bestätigung noch gültig ist, oder ob sie bereits verwendet wurde
(Auftrag Abschnitt 3.2). Reine Zustandsverwaltung, KEIN ROS --
command_router_node.py bindet dies an echte Topics/Services
(AuthorizationRequest.msg/AuthorizationDecision.msg/
ConfirmAuthorization.srv).

Jede Bestätigung ist GENAU EINMAL verwendbar (confirm() entfernt den
Request bei JEDEM Ausgang -- Erfolg, Ablehnung, oder ein
Bindungsfehler). Eine Wiederverwendung, ein falscher Nonce, ein
abgelaufener Request, ein Trackwechsel, eine andere Person, ein
geänderter Befehl oder ein ungültiger Sicherheitszustand führen
IMMER zur Ablehnung -- niemals zu einer stillschweigenden Freigabe."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class AuthorizationRequestRecord:
    request_id: str
    event_id: str
    interaction_id: str
    session_id: str
    track_id: int
    person_id: str
    role: str
    command: str
    requested_capability: str
    created_at_s: float
    expires_at_s: float
    nonce: str
    reason: str


@dataclass(frozen=True)
class CurrentContext:
    """Der AKTUELLE Zustand zum Zeitpunkt der Bestätigung -- confirm()
    vergleicht dies gegen den Stand zum Zeitpunkt der Anfrage
    (Auftrag: 'dieselbe Person bzw. derselbe Track noch vorhanden',
    'Bestätigung nach Trackwechsel'/'nach Sitzungsende' ablehnen)."""

    track_id: int
    person_id: str
    role: str
    command: str
    session_id: str
    safety_state_valid: bool


class ScopedAuthorizationStore:
    def __init__(self, now_fn: Callable[[], float] = time.time,
                 id_fn: Callable[[], str] = lambda: str(uuid.uuid4())):
        self._now_fn = now_fn
        self._id_fn = id_fn
        self._requests: Dict[str, AuthorizationRequestRecord] = {}

    def create_request(
        self, event_id: str, interaction_id: str, session_id: str, track_id: int,
        person_id: str, role: str, command: str, requested_capability: str,
        reason: str, validity_s: float,
    ) -> AuthorizationRequestRecord:
        now = self._now_fn()
        record = AuthorizationRequestRecord(
            request_id=self._id_fn(), event_id=event_id, interaction_id=interaction_id,
            session_id=session_id, track_id=track_id, person_id=person_id, role=role,
            command=command, requested_capability=requested_capability,
            created_at_s=now, expires_at_s=now + validity_s,
            nonce=self._id_fn(), reason=reason,
        )
        self._requests[record.request_id] = record
        return record

    def get(self, request_id: str) -> Optional[AuthorizationRequestRecord]:
        return self._requests.get(request_id)

    def confirm(
        self, request_id: str, nonce: str, approve: bool, current: CurrentContext,
    ) -> Tuple[bool, str]:
        """Reine Prüfung + Seiteneffekt (entfernt den Request bei JEDEM
        Ausgang -- einmalige Verwendung). Prüft in dieser Reihenfolge:
        Existenz -> Nonce -> Ablauf -> Ablehnung durch den Bestätigenden
        -> Track/Person/Rolle/Befehl/Sitzung unverändert -> aktueller
        Sicherheitszustand gültig."""
        record = self._requests.get(request_id)
        if record is None:
            return False, "request_unbekannt_oder_bereits_verwendet"
        if record.nonce != nonce:
            # Falscher Nonce verbraucht den Request NICHT -- sonst
            # koennte ein einzelner Ratefehler eine echte, noch nicht
            # entschiedene Anfrage versehentlich blockieren.
            return False, "falscher_nonce"
        if self._now_fn() > record.expires_at_s:
            del self._requests[request_id]
            return False, "request_abgelaufen"
        if not approve:
            del self._requests[request_id]
            return False, "abgelehnt"
        if record.track_id != current.track_id:
            del self._requests[request_id]
            return False, "track_hat_sich_geaendert"
        if record.person_id != current.person_id:
            del self._requests[request_id]
            return False, "person_hat_sich_geaendert"
        if record.role != current.role:
            del self._requests[request_id]
            return False, "rolle_hat_sich_geaendert"
        if record.command != current.command:
            del self._requests[request_id]
            return False, "befehl_hat_sich_geaendert"
        if record.session_id != current.session_id:
            del self._requests[request_id]
            return False, "sitzung_hat_sich_geaendert"
        if not current.safety_state_valid:
            del self._requests[request_id]
            return False, "sicherheitszustand_ungueltig"
        del self._requests[request_id]
        return True, ""

    def purge_expired(self, now: Optional[float] = None) -> list:
        """Gibt die IDs der entfernten, abgelaufenen Requests zurueck
        (der Aufrufer kann dafuer je eine AuthorizationDecision(confirmed=False)
        veroeffentlichen -- 'Timeout... bedeutet Ablehnung', Auftrag
        Abschnitt 10)."""
        now = self._now_fn() if now is None else now
        expired = [rid for rid, r in self._requests.items() if now > r.expires_at_s]
        for rid in expired:
            del self._requests[rid]
        return expired
