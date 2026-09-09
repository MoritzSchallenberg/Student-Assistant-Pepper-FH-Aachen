"""
Zentraler Aktuator-Arbiter -- reine, ROS-freie Kernlogik
(Entwicklungsauftrag 04-B, AP5B). Koordiniert alle Zugriffe auf Peppers
physische Aktoren ueber zeitlich begrenzte Leases, bevor
ihk_pepper_bridge ueberhaupt einen Transport anfasst.

Bewusst reiner Python-Zustandsautomat -- kein rclpy, keine Blockierung,
kein Warten. acquire()/renew()/release() sind synchrone
Sofort-Entscheidungen (gewaehrt/abgelehnt), niemals ein wartender
Aufruf -- das schliesst Deadlocks strukturell aus (kein Aufrufer haelt
je einen Teil der angeforderten Ressourcen, waehrend er auf den Rest
wartet: entweder alle Ressourcen werden atomar gewaehrt, oder keine).

Sicherheitsgrenze: dieser Arbiter ist KEINE Authentifizierungsschicht
gegen absichtlich boesartige ROS2-Nodes (ROS2 bietet in diesem Projekt
keine Node-Authentifizierung). Die tatsaechliche Aktorgrenze bleiben
Pepper-Bridge und Motion Guard (siehe docs/ACTUATOR_ARBITER.md).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

# ---- Ressourcen (Entwicklungsauftrag 04-B, Abschnitt 4) ----

SPEECH = "SPEECH"
HEAD = "HEAD"
LEFT_ARM = "LEFT_ARM"
RIGHT_ARM = "RIGHT_ARM"
TORSO = "TORSO"
BASE = "BASE"
LEDS = "LEDS"
TABLET = "TABLET"

ALL_RESOURCES = frozenset({SPEECH, HEAD, LEFT_ARM, RIGHT_ARM, TORSO, BASE, LEDS, TABLET})
# LEDS/TABLET sind laut Auftrag "nicht zwingend exklusiv" -- sie nehmen
# nie an Konflikt-/Preemptionspruefungen teil (siehe _is_exclusive()).
NON_EXCLUSIVE_RESOURCES = frozenset({LEDS, TABLET})

# Zusaetzliche, nicht rein ressourcenbasierte Ausschlussregeln
# (Abschnitt 8): TORSO und BASE duerfen nie gleichzeitig eine Lease
# halten (Umknicken/Fallrisiko beim gleichzeitigen Fahren+Neigen), auch
# wenn beide Anforderungen fuer sich genommen je eine eigene,
# unbelegte Ressource waeren.
MUTUALLY_EXCLUSIVE_RESOURCE_PAIRS = frozenset({frozenset({TORSO, BASE})})

# ---- Prioritaeten (Entwicklungsauftrag 04-B, Abschnitt 5) --
# NIEDRIGERE Zahl = HOEHERE Prioritaet (Rang 1 gewinnt gegen Rang 10).
# Serverseitig aus dieser vertrauenswuerdigen Konstantenliste bestimmt --
# ein LLM oder ein frei befuellbares Action-Feld kann diese Werte NICHT
# beeinflussen (kein Priority-Feld existiert in irgendeinem LLM-Vertrag).

PRIORITY_EMERGENCY_STOP = 1
PRIORITY_HARDWARE_FAULT = 2
PRIORITY_USER_STOP = 3
PRIORITY_SAFETY_ABORT = 4
PRIORITY_RETURN_TO_SAFE = 5
PRIORITY_NAVIGATION = 6
PRIORITY_DIALOGUE = 7
PRIORITY_PRESENTATION = 8
PRIORITY_ATTRACT = 9
PRIORITY_IDLE = 10

# Leases mit einer Prioritaet <= dieser Schwelle gelten als
# sicherheitskritisch -- sie koennen NICHT durch normale Praemption
# verdraengt werden (nur durch eine noch hoehere/gleiche
# Sicherheitsprioritaet oder emergency_revoke_all()).
SAFETY_CRITICAL_PRIORITY_THRESHOLD = PRIORITY_SAFETY_ABORT

DEFAULT_LEASE_TTL_S = 30.0


@dataclass
class Lease:
    """Eine gewaehrte Aktuator-Belegung. resources ist ein frozenset --
    eine Lease ist entweder vollstaendig gewaehrt oder gar nicht
    (atomare Mehrfachressourcen, Abschnitt 4)."""

    lease_id: str
    owner_id: str
    purpose: str
    resources: frozenset
    priority: int
    started_at: float
    expires_at: float
    goal_id: str = ""
    preempted: bool = False
    preempted_reason: str = ""

    def is_safety_critical(self) -> bool:
        return self.priority <= SAFETY_CRITICAL_PRIORITY_THRESHOLD


@dataclass
class AcquireResult:
    granted: bool
    lease: Optional[Lease] = None
    reason: str = ""
    conflicting_owners: list = field(default_factory=list)
    preempted_leases: list = field(default_factory=list)


def _is_exclusive(resource: str) -> bool:
    return resource not in NON_EXCLUSIVE_RESOURCES


def _conflicts(resources_a: frozenset, resources_b: frozenset) -> bool:
    exclusive_a = {r for r in resources_a if _is_exclusive(r)}
    exclusive_b = {r for r in resources_b if _is_exclusive(r)}
    if exclusive_a & exclusive_b:
        return True
    for pair in MUTUALLY_EXCLUSIVE_RESOURCE_PAIRS:
        if (pair & exclusive_a) and (pair & exclusive_b):
            return True
    return False


class ActuatorArbiter:
    """Reiner Zustandsautomat. now_fn injizierbar (monotone Uhr,
    Entwicklungsauftrag-Vorgabe) -- Standard time.monotonic, in Tests
    durch eine steuerbare Fake-Uhr ersetzbar (gleiches Prinzip wie
    CircuitBreaker/FreshBool an anderer Stelle in diesem Projekt)."""

    def __init__(self, now_fn=time.monotonic):
        self._now_fn = now_fn
        self._leases: dict[str, Lease] = {}

    def _now(self) -> float:
        return self._now_fn()

    def _expire_stale(self) -> None:
        now = self._now()
        expired = [lid for lid, lease in self._leases.items() if lease.expires_at <= now]
        for lid in expired:
            del self._leases[lid]

    def active_leases(self) -> list:
        self._expire_stale()
        return list(self._leases.values())

    def is_locked(self, resource: str) -> bool:
        self._expire_stale()
        return any(resource in lease.resources for lease in self._leases.values())

    def get_lease(self, lease_id: str) -> Optional[Lease]:
        self._expire_stale()
        return self._leases.get(lease_id)

    def acquire(
        self, owner_id: str, resources, purpose: str, priority: int,
        safety_ok: bool, ttl_s: float = DEFAULT_LEASE_TTL_S, goal_id: str = "",
    ) -> AcquireResult:
        """Fordert ALLE angegebenen Ressourcen atomar an -- entweder alle
        oder keine (Abschnitt 4: "Teilweise belegte Ressourcen duerfen
        nicht zu Deadlocks fuehren"). safety_ok wird vom Aufrufer (dem
        ROS-Node-Wrapper, mit eigener FreshBool-basierter
        Aktualitaetspruefung) pro Aufruf uebergeben -- der Arbiter selbst
        haelt keinen eigenen SafetyState, um denselben "vollstaendig vom
        Aufrufer befuellter Kontext"-Grundsatz wie PlanContext
        (response_plan.py) einzuhalten."""
        resources = frozenset(resources)
        if not resources:
            return AcquireResult(granted=False, reason="keine Ressourcen angefordert")
        unknown = resources - ALL_RESOURCES
        if unknown:
            return AcquireResult(granted=False, reason=f"unbekannte Ressourcen: {sorted(unknown)}")
        if not safety_ok:
            return AcquireResult(granted=False, reason="SafetyState nicht ok/veraltet -- keine neue Aktuation")

        self._expire_stale()
        now = self._now()

        conflicting = [
            lease for lease in self._leases.values()
            if lease.owner_id != owner_id and _conflicts(resources, lease.resources)
        ]

        to_preempt = []
        blocking_owners = []
        for lease in conflicting:
            if lease.is_safety_critical():
                blocking_owners.append(lease.owner_id)
                continue
            if priority < lease.priority:
                to_preempt.append(lease)
            else:
                blocking_owners.append(lease.owner_id)

        if blocking_owners:
            return AcquireResult(
                granted=False,
                reason=f"Ressourcenkonflikt mit: {sorted(set(blocking_owners))}",
                conflicting_owners=sorted(set(blocking_owners)),
            )

        # Alle verbleibenden Konflikte sind praemptierbar -- jetzt
        # tatsaechlich commiten (kein Konflikt mehr offen, atomar).
        preempted_leases = []
        for lease in to_preempt:
            lease.preempted = True
            lease.preempted_reason = f"praemptiert durch '{owner_id}' (Prioritaet {priority})"
            preempted_leases.append(lease)
            del self._leases[lease.lease_id]

        lease = Lease(
            lease_id=str(uuid.uuid4()), owner_id=owner_id, purpose=purpose,
            resources=resources, priority=priority, started_at=now,
            expires_at=now + ttl_s, goal_id=goal_id,
        )
        self._leases[lease.lease_id] = lease
        return AcquireResult(granted=True, lease=lease, preempted_leases=preempted_leases)

    def renew(self, lease_id: str, ttl_s: float = DEFAULT_LEASE_TTL_S) -> bool:
        self._expire_stale()
        lease = self._leases.get(lease_id)
        if lease is None:
            return False  # abgelaufen/unbekannt -- idempotent, kein Fehler
        lease.expires_at = self._now() + ttl_s
        return True

    def release(self, lease_id: str) -> bool:
        """Idempotent (Abschnitt 5): ein unbekannter/bereits freigegebener
        lease_id liefert einfach False, wirft nie."""
        self._expire_stale()
        if lease_id in self._leases:
            del self._leases[lease_id]
            return True
        return False

    def emergency_revoke_all(self, reason: str) -> list:
        """Bumper/Not-Stopp (Abschnitt 5): "benoetigen KEINE
        Bewegungsfreigabe, um laufende Aktoren stoppen zu duerfen" --
        widerruft ALLE Leases sofort, unabhaengig von Prioritaet/
        Praemptierbarkeit. Gibt die widerrufenen Leases zurueck, damit
        der Aufrufer (Arbiter-Node) jeden betroffenen Owner ueber einen
        CancelActuation-Aufruf informieren kann."""
        self._expire_stale()
        revoked = list(self._leases.values())
        for lease in revoked:
            lease.preempted = True
            lease.preempted_reason = reason
        self._leases.clear()
        return revoked
