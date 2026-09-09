"""
Autorisierungsrichtlinie fuer privilegierte Sprachbefehle
(Entwicklungsauftrag 04-B, AP7, Abschnitt 8). Reine Konstanten +
Pruefungen, KEINE ROS-Abhaengigkeit -- ein Gesichtserkennungsergebnis
allein autorisiert NIE eine Bewegung (Auftrag: "kann durch Fotos oder
Bildschirme angegriffen werden").

Gleiches Fail-Closed-Prinzip wie audio_node.py::activation_mode
(Entwicklungsauftrag 04-B, AP6.1, Abschnitt 13) -- ein unbekannter/
nicht erlaubter Policy-Wert wird NIE stillschweigend als "erlaubt"
behandelt, und `role_only_development` ist in Produktion hart gesperrt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

POLICY_DISABLED = "disabled"
POLICY_ROLE_PLUS_CONFIRMATION = "role_plus_confirmation"
POLICY_ROLE_ONLY_DEVELOPMENT = "role_only_development"

VALID_POLICIES = (POLICY_DISABLED, POLICY_ROLE_PLUS_CONFIRMATION, POLICY_ROLE_ONLY_DEVELOPMENT)


class AuthorizationPolicyError(ValueError):
    pass


def validate_policy(policy: str, production_mode: bool) -> None:
    """Wirft AuthorizationPolicyError bei ungueltigem Wert ODER bei
    role_only_development in production_mode=true (Auftrag Abschnitt 8:
    "muss im Produktionsmodus hart abgelehnt werden") -- an derselben
    Stelle wie audio_node.py's continuous_development-Guard aufgerufen
    (beim Node-Start, nicht erst beim ersten Befehl)."""
    if policy not in VALID_POLICIES:
        raise AuthorizationPolicyError(
            f"Unbekannte privileged_motion_policy '{policy}'. Erlaubt: "
            f"{', '.join(VALID_POLICIES)}."
        )
    if production_mode and policy == POLICY_ROLE_ONLY_DEVELOPMENT:
        raise AuthorizationPolicyError(
            "privileged_motion_policy=role_only_development ist mit "
            "production_mode=true gesperrt (Entwicklungsauftrag 04-B, AP7, "
            "Abschnitt 8) -- Rolle allein (ohne Zusatzbestaetigung) darf in "
            "Produktion niemals eine privilegierte Bewegung autorisieren."
        )


@dataclass(frozen=True)
class PrivilegedCommandRequest:
    """Alle sieben in Auftrag Abschnitt 8 geforderten Voraussetzungen
    fuer role_plus_confirmation, als Datencontainer -- die eigentliche
    Pruefung bleibt eine reine Funktion (siehe check_authorization()),
    damit sie ohne ROS/echte Sensorik testbar ist."""

    known_identity: bool
    role: str
    recognition_confidence: float
    minimum_confidence: float
    liveness_passed: bool
    speaking_track_id: int
    identity_track_id: int
    secondary_confirmation_valid: bool
    safety_state_valid: bool
    required_min_role: str


def check_authorization(policy: str, req: PrivilegedCommandRequest):
    """Reine Funktion. Gibt (authorized: bool, reason: str) zurueck --
    NIE True ohne dass JEDE einschlaegige Bedingung erfuellt ist
    (fail-closed: ein einzelner fehlender Nachweis reicht fuer eine
    Ablehnung)."""
    if policy == POLICY_DISABLED:
        return False, "privileged_motion_disabled"

    if policy == POLICY_ROLE_ONLY_DEVELOPMENT:
        # NUR fuer Entwicklung/Tests -- validate_policy() sperrt diesen
        # Zweig bereits in production_mode=true, hier zusaetzlich
        # geprueft, falls check_authorization() je isoliert aufgerufen wird.
        from .roles import role_at_least
        if not role_at_least(req.role, req.required_min_role):
            return False, "role_insufficient"
        return True, ""

    if policy != POLICY_ROLE_PLUS_CONFIRMATION:
        return False, f"unbekannte_policy:{policy}"

    from .roles import role_at_least

    if not req.known_identity:
        return False, "identity_unknown"
    if not role_at_least(req.role, req.required_min_role):
        return False, "role_insufficient"
    if req.recognition_confidence < req.minimum_confidence:
        return False, "recognition_confidence_zu_niedrig"
    if not req.liveness_passed:
        return False, "liveness_nicht_bestanden"
    if req.speaking_track_id != req.identity_track_id:
        return False, "track_id_stimmt_nicht_mit_identitaet_ueberein"
    if not req.secondary_confirmation_valid:
        return False, "keine_zusatzbestaetigung"
    if not req.safety_state_valid:
        return False, "safety_state_ungueltig"
    return True, ""
