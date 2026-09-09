"""
Verbindet die grobe "braucht dieser Befehl ueberhaupt eine Rolle"-
Entscheidung (roles.py) mit der vollen Autorisierungspruefung fuer
privilegierte Befehle (authorization_policy.py::check_authorization(),
Auftrag Abschnitt 8) -- fuer den deterministischen Befehls-Router
(Entwicklungsauftrag 04-B, AP7, Abschnitt 10). Reine Logik, KEIN ROS --
command_router_node.py bindet das an echte Topics/Services.

Rollenfreie Befehle (stop/cancel/interrupt_and_look -- min_role_for_command()
liefert None) brauchen KEINE Section-8-Pruefung (Liveness/Track-
Uebereinstimmung/Zusatzbestaetigung waeren hier unpassend, "jede
Gespraechsperson darf sie verwenden", siehe Auftrag Abschnitt 12) --
NUR rollen-gebundene Befehle (follow_speaker) durchlaufen die volle
Pruefkette."""
from __future__ import annotations

from dataclasses import dataclass

from .authorization_policy import PrivilegedCommandRequest, check_authorization
from .roles import ROLE_STUDENT, is_command_voice_forbidden, min_role_for_command

AUTHORIZATION_NOT_REQUIRED = "not_required"
AUTHORIZATION_GRANTED = "granted"
AUTHORIZATION_DENIED = "denied"


@dataclass(frozen=True)
class CommandDecision:
    authorization_status: str
    role: str
    reason: str = ""


def decide_command_authorization(
    command: str,
    policy: str,
    known_identity: bool,
    role: str,
    recognition_confidence: float,
    minimum_confidence: float,
    liveness_passed: bool,
    speaking_track_id: int,
    identity_track_id: int,
    secondary_confirmation_valid: bool,
    safety_state_valid: bool,
) -> CommandDecision:
    if is_command_voice_forbidden(command):
        return CommandDecision(AUTHORIZATION_DENIED, ROLE_STUDENT, "befehl_nie_per_sprache_erlaubt")

    required_role = min_role_for_command(command)
    if required_role is None:
        return CommandDecision(
            AUTHORIZATION_NOT_REQUIRED, role if known_identity else ROLE_STUDENT, "")

    req = PrivilegedCommandRequest(
        known_identity=known_identity, role=role,
        recognition_confidence=recognition_confidence, minimum_confidence=minimum_confidence,
        liveness_passed=liveness_passed, speaking_track_id=speaking_track_id,
        identity_track_id=identity_track_id,
        secondary_confirmation_valid=secondary_confirmation_valid,
        safety_state_valid=safety_state_valid, required_min_role=required_role,
    )
    authorized, reason = check_authorization(policy, req)
    return CommandDecision(AUTHORIZATION_GRANTED if authorized else AUTHORIZATION_DENIED, role, reason)
