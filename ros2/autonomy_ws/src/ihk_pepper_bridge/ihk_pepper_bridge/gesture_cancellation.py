"""
Strukturierte Gesten-Abbruchgruende (Entwicklungsauftrag 04-B, AP8-R1.4).

Bestaetigter Fund (siehe docs/DEVELOPMENT_ORDER_04_B_REPORT.md, AP8-R1
Abschnitt 3.5): `cancel_event` transportierte bisher NUR den Zustand
"abbrechen" (ein einfacher threading.Event) -- ROS-Cancel, Codewort,
Timeout, Lease-Widerruf, Praemption, Not-Stopp, Bumper, Nav2-/Mapping-/
Interaktionskonflikt, Pepper-Verbindungsverlust, Transportfehler und
Node-Shutdown waren dadurch NICHT unterscheidbar -- `on_cancel=restore`
konnte deshalb nicht fuer jeden Abbruchgrund korrekt entscheiden.

CancelSignal ersetzt den blossen threading.Event als Traeger EINES
strukturierten, einmal gesetzten Grundes -- bleibt aber absichtlich
duck-type-kompatibel zu einem threading.Event (is_set()/wait()), damit
bestehende Aufrufer (motion_transport.py, gesture_catalog.py), die nur
is_set() lesen, unveraendert funktionieren.
"""
from __future__ import annotations

import threading
import time
from typing import Optional


class GestureCancelReason:
    """Keine echte Enum-Klasse (gleiches Muster wie motion_transport.py::
    TransportStatus) -- einfache String-Konstanten, leichter ueber
    ROS2-Ergebnisfelder/Logs zu transportieren."""

    NORMAL_USER_CANCEL = "normal_user_cancel"
    CODEWORD_INTERRUPT = "codeword_interrupt"
    TIMEOUT = "timeout"
    LEASE_REVOKED = "lease_revoked"
    PREEMPTED = "preempted"
    SAFETY_INVALID = "safety_invalid"
    EMERGENCY_STOP = "emergency_stop"
    BUMPER_ACTIVE = "bumper_active"
    NAVIGATION_STARTED = "navigation_started"
    MAPPING_STARTED = "mapping_started"
    INTERACTION_INVALID = "interaction_invalid"
    PEPPER_UNREACHABLE = "pepper_unreachable"
    TRANSPORT_FAILED = "transport_failed"
    NODE_SHUTDOWN = "node_shutdown"


ALL_CANCEL_REASONS = frozenset({
    GestureCancelReason.NORMAL_USER_CANCEL,
    GestureCancelReason.CODEWORD_INTERRUPT,
    GestureCancelReason.TIMEOUT,
    GestureCancelReason.LEASE_REVOKED,
    GestureCancelReason.PREEMPTED,
    GestureCancelReason.SAFETY_INVALID,
    GestureCancelReason.EMERGENCY_STOP,
    GestureCancelReason.BUMPER_ACTIVE,
    GestureCancelReason.NAVIGATION_STARTED,
    GestureCancelReason.MAPPING_STARTED,
    GestureCancelReason.INTERACTION_INVALID,
    GestureCancelReason.PEPPER_UNREACHABLE,
    GestureCancelReason.TRANSPORT_FAILED,
    GestureCancelReason.NODE_SHUTDOWN,
})

# Entwicklungsauftrag 04-B, AP8-R1.5 (Restore-/Breathing-Matrix,
# Abschnitt 8): NUR ein normaler Nutzerabbruch kann UEBERHAUPT eine
# Restore-Trajektorie ausloesen (zusaetzlich noch an on_cancel=="restore"
# UND einen frischen sicheren Zustand gebunden, siehe restore_allowed()).
# Jeder andere Grund verbietet Restore UNBEDINGT.
_RESTORE_POSSIBLE_REASONS = frozenset({GestureCancelReason.NORMAL_USER_CANCEL})

# Gruende, die auch bei nachtraeglich wiederhergestellter Sicherheit NIE
# eine automatische Breathing-Reaktivierung erlauben (Abschnitt 8: fuer
# alle hier NICHT genannten Gruende -- normaler Abschluss, normaler
# Nutzerabbruch, Codewort -- bleibt eine frische Sicherheitspruefung
# zum Reaktivierungszeitpunkt maßgeblich, siehe breathing_may_reactivate()).
_BREATHING_NEVER_REACTIVATES_REASONS = frozenset({
    GestureCancelReason.TIMEOUT,
    GestureCancelReason.LEASE_REVOKED,
    GestureCancelReason.PREEMPTED,
    GestureCancelReason.SAFETY_INVALID,
    GestureCancelReason.EMERGENCY_STOP,
    GestureCancelReason.BUMPER_ACTIVE,
    GestureCancelReason.NAVIGATION_STARTED,
    GestureCancelReason.MAPPING_STARTED,
    GestureCancelReason.INTERACTION_INVALID,
    GestureCancelReason.PEPPER_UNREACHABLE,
    GestureCancelReason.TRANSPORT_FAILED,
    GestureCancelReason.NODE_SHUTDOWN,
})


class CancelSignal:
    """Kombiniert ein threading.Event mit einem EINMAL gesetzten,
    strukturierten Abbruchgrund. Idempotent per Konstruktion: die ERSTE
    set()-Anfrage legt den Grund endgueltig fest, jede weitere (auch mit
    einem anderen reason) aendert ihn NICHT mehr -- das erfuellt sowohl
    "der erste sicherheitsrelevante Cancel-Grund gewinnt" als auch "ein
    spaeterer normaler Cancel darf einen bereits gesetzten Not-Stopp-Grund
    nicht ueberschreiben" (Auftrag AP8-R1.4), ohne eine gesonderte
    Prioritaetstabelle zwischen den Gruenden selbst zu brauchen.

    Bleibt absichtlich duck-type-kompatibel zu einem blossen
    threading.Event (is_set()/wait()) -- Code, der nur is_set() liest
    (motion_transport.py, gesture_catalog.py-Poll-Schleifen), funktioniert
    unveraendert."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self.reason: Optional[str] = None

    def set(self, reason: str = GestureCancelReason.NORMAL_USER_CANCEL) -> None:
        with self._lock:
            if not self._event.is_set():
                self.reason = reason
                self._event.set()
            # sonst: bereits gesetzt -- Grund bleibt bei der ERSTEN Anfrage
            # (siehe Klassendoku), auch eine doppelte Anfrage mit
            # DEMSELBEN Grund bleibt dadurch trivial idempotent.

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._event.wait(timeout)


def restore_allowed(reason: Optional[str], gesture_on_cancel: str, safety_ok_now: bool) -> bool:
    """Restore-Spalte der Matrix aus Auftrag AP8-R1.5, Abschnitt 8.
    reason=None bedeutet HIER "kein Abbruch (normale Beendigung)" --
    diese Funktion wird nur fuer den ABBRUCHFALL aufgerufen, der normale
    Abschluss folgt weiterhin gesture.restore_after (siehe
    gesture_catalog.py::_play_v2, unveraendert)."""
    if reason not in _RESTORE_POSSIBLE_REASONS:
        return False
    if gesture_on_cancel != "restore":
        return False
    return bool(safety_ok_now)


def breathing_may_reactivate(reason: Optional[str], safety_ok_now: bool) -> bool:
    """Breathing-Spalte der Matrix aus Auftrag AP8-R1.5, Abschnitt 8.
    reason=None: normale erfolgreiche Beendigung -- Breathing darf
    reaktiviert werden, wenn Safety JETZT (zum Reaktivierungszeitpunkt)
    weiterhin gueltig ist. NORMAL_USER_CANCEL/CODEWORD_INTERRUPT: gleiche
    Bedingung (frische Sicherheitspruefung entscheidet). Jeder andere
    Grund (Timeout, Lease-Widerruf/Praemption, Not-Stopp/Bumper,
    ungueltiger SafetyState, Nav2-/Mapping-/Interaktionskonflikt,
    Pepper-Verbindungsverlust, Transportfehler, Node-Shutdown): NIE,
    unabhaengig vom aktuellen Sicherheitszustand -- setBreathing(True, ...)
    kann selbst neue Gelenkbewegung ausloesen und darf nach einem dieser
    Ereignisse nicht bedingungslos im finally reaktiviert werden."""
    if reason in _BREATHING_NEVER_REACTIVATES_REASONS:
        return False
    return bool(safety_ok_now)


class ExecutionPhase:
    """Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.1 ('Ein
    Ausfuehrungsdatensatz pro Ziel'). Keine echte Enum-Klasse (gleiches
    Muster wie GestureCancelReason/TransportStatus) -- einfache
    String-Konstanten."""

    PREPARING = "preparing"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    CANCEL_PENDING = "cancel_pending"
    QUARANTINED = "quarantined"
    TERMINAL = "terminal"
    CLEANED = "cleaned"


class ActiveGestureExecution:
    """Ein Ausfuehrungsdatensatz pro aktivem PlayGesture-Ziel
    (Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.1) -- ersetzt/fasst die
    zuvor verstreuten losen Strukturen (_active_gesture_cancel_events/
    _revoked_lease_ids/_quarantined_lease_ids in bridge_node.py)
    zusammen. ALLE Feldaenderungen laufen unter
    PepperBridgeNode._active_execution_lock (siehe dort) -- diese Klasse
    selbst erzwingt keine Nebenlaeufigkeitssicherheit, sie ist reiner
    Datentraeger."""

    def __init__(self, lease_id: str, goal_id: str, owner_id: str,
                 resources, gesture_name: str, cancel_signal: "CancelSignal"):
        self.lease_id = lease_id
        self.goal_id = goal_id
        self.owner_id = owner_id
        self.resources = frozenset(resources)
        self.gesture_name = gesture_name
        self.cancel_signal = cancel_signal
        self.phase = ExecutionPhase.PREPARING
        self.prep_started_monotonic_s: float = time.monotonic()
        self.transport_started_monotonic_s: Optional[float] = None
        self.last_renewed_monotonic_s: float = time.monotonic()
        self.transport_terminal = False
        self.quarantined = False
        self.cleanup_completed = False

    def overlaps_resources(self, other_resources) -> bool:
        return bool(self.resources & frozenset(other_resources))

    def is_settled(self) -> bool:
        """True, sobald diese Ausfuehrung KEINE Ressourcen mehr blockiert
        (Cleanup abgeschlossen) -- fuer die lokale Konfliktpruefung
        (Abschnitt 3.3) genutzt: nur NICHT abgeschlossene Datensaetze
        blockieren ein neues, ueberlappendes Ziel."""
        return self.cleanup_completed
