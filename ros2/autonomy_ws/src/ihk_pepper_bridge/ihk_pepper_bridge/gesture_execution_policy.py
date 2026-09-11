"""
Autoritative Gesten-Ausführungsrichtlinie (Entwicklungsauftrag 04-B,
AP8.1). Reine, ROS-freie Logik -- MUSS an der Pepper-Bridge selbst
durchgesetzt werden, weil sie die letzte vertrauenswürdige Grenze vor
qicli/NAOqi ist (siehe bridge_node.py-Moduldoku). Filter in
gesture_memory_node/run_dialogue_action_server/Behavior Tree bleiben
zusätzliche, aber NICHT die letzte Sicherheitsschicht -- ein direkter
Aufruf von `/pepper_bridge/play_gesture` (oder ein fest im Baum
eingetragener Gestenname) MUSS an genau dieser Stelle abgelehnt werden
koennen, unabhaengig davon, was ein Aufrufer vorher schon gefiltert hat.

Zwei Aufrufzeitpunkte sind vorgesehen (siehe bridge_node.py::
_execute_gesture): einmal VOR dem Lease-Erwerb (verhindert, dass eine
von vornherein unzulaessige Anfrage ueberhaupt eine Ressource belegt),
und ein zweites Mal UNMITTELBAR vor Transportstart (Laufzeitzustaende
koennen sich zwischen beiden Aufrufen geaendert haben, siehe
fresh_state.py/AP8.2). Eine Ablehnung darf an keiner Stelle einen
Hintergrund-Thread starten, eine Lease erwerben oder SSH/qicli
beruehren -- das wird durch die Aufrufreihenfolge in bridge_node.py
sichergestellt, nicht durch dieses Modul selbst (das nur entscheidet,
nie selbst etwas ausfuehrt).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Optional

from .gesture_catalog import MAX_SPEED_SCALE_V1, MAX_SPEED_SCALE_V2, MIN_SPEED_SCALE_V1, \
    MIN_SPEED_SCALE_V2, VALID_TESTED_STATUS

# ---- Ausführungsprofile (Auftrag Abschnitt 5) ----

PROFILE_OFFLINE_MOCK = "offline_mock"
PROFILE_OFFLINE_PREVIEW = "offline_preview"
PROFILE_SUPERVISED_HARDWARE_TEST = "supervised_hardware_test"
PROFILE_PRODUCTION = "production"

VALID_EXECUTION_PROFILES = (
    PROFILE_OFFLINE_MOCK, PROFILE_OFFLINE_PREVIEW,
    PROFILE_SUPERVISED_HARDWARE_TEST, PROFILE_PRODUCTION,
)

# Nur diese beiden Profile duerfen ueberhaupt SSH/qicli/eine Lease
# beruehren -- offline_mock/offline_preview bleiben STRUKTURELL ohne
# Hardwarezugriff (siehe bridge_node.py, das fuer diese Profile
# dry_run=True erzwingt, unabhaengig vom uebergebenen dry_run-Parameter).
HARDWARE_CAPABLE_PROFILES = frozenset(
    {PROFILE_SUPERVISED_HARDWARE_TEST, PROFILE_PRODUCTION})

# Rang je tested_status (Index in der bereits bestehenden,
# vertrauenswuerdigen Reihenfolge aus gesture_catalog.py -- KEIN neuer
# Wertebereich, dieselbe Quelle wie die Schema-Validierung beim Laden).
_STATUS_RANK = {status: i for i, status in enumerate(VALID_TESTED_STATUS)}

# Minimal erforderlicher tested_status je Profil (Auftrag Abschnitt 5:
# "offline_mock/offline_preview duerfen draft laden", "supervised_
# hardware_test darf nur ein mindestens dry_run_validated Ziel
# ausfuehren", "production darf ausschliesslich live_validated
# ausfuehren"). Serverseitig fest verdrahtet -- KEIN Parameter/Launch-
# Argument/Action-Feld kann diese Tabelle absenken (siehe
# authorize(), das execution_profile nur gegen VALID_EXECUTION_PROFILES
# und diese Tabelle abgleicht, niemals gegen einen vom Aufrufer
# mitgelieferten Schwellwert).
_MINIMUM_TESTED_STATUS_BY_PROFILE = {
    PROFILE_OFFLINE_MOCK: "draft",
    PROFILE_OFFLINE_PREVIEW: "draft",
    PROFILE_SUPERVISED_HARDWARE_TEST: "dry_run_validated",
    PROFILE_PRODUCTION: "live_validated",
}


@dataclass(frozen=True)
class RuntimeContext:
    """Momentaufnahme sicherheitsrelevanter Laufzeitzustaende --
    VOLLSTAENDIG vom Aufrufer befuellt (dieses Modul haelt selbst
    keinen Zustand, siehe PlanContext/ActuatorArbiter.acquire() fuer
    dasselbe Prinzip an anderer Stelle im Projekt). None bedeutet
    IMMER "unbekannt/nicht geliefert" -- wird fail-closed wie ein
    ungueltiger Wert behandelt, NIE wie "kein Problem" (Auftrag
    Abschnitt 6: "SafetyState fehlt/veraltet -> jede Hardwaregeste
    sperren" usw.). Siehe fresh_state.py fuer die Aktualitaetspruefung,
    die diese Werte aus rohen Topic-Ankuenften erzeugt."""

    safety_ok: Optional[bool] = None
    nav2_moving: Optional[bool] = None
    mapping_active: Optional[bool] = None
    current_interaction_state: Optional[str] = None
    pepper_reachable: Optional[bool] = None
    # True, wenn die fuer dieses Ziel gehaltene Lease seit der letzten
    # Pruefung widerrufen/praemptiert wurde (siehe AP8.3) -- nur beim
    # zweiten Aufruf (unmittelbar vor Transportstart) ueberhaupt
    # relevant, beim ersten (vor Lease-Erwerb) immer False.
    lease_revoked: bool = False


@dataclass(frozen=True)
class GestureDecision:
    allowed: bool
    reason_code: str
    reason: str
    effective_tested_status: str
    effective_speed_scale: float
    expected_duration_s: float
    resources: FrozenSet[str] = field(default_factory=frozenset)


def _effective_speed_scale(gesture, requested_speed_scale: Optional[float]) -> float:
    """Identische Aufloesung wie GestureCatalog.play()/KinematicCompiler.compile():
    <=0 oder None nutzt gesture.speed_scale_default (Auftrag Abschnitt 6:
    'nur dann Katalogdefault, wenn im Interface ausdruecklich dokumentiert
    und getestet' -- das ist hier UND in gesture_catalog.py/
    kinematic_compiler.py der Fall, siehe test_gesture_execution_policy.py).
    Anschliessend auf denselben Bereich wie die tatsaechliche Ausfuehrung
    geklemmt (v1: MIN/MAX_SPEED_SCALE_V1, v2: MIN/MAX_SPEED_SCALE_V2) --
    KEINE stille Klemmung eines sicherheitsrelevant UNGUELTIGEN Werts
    (NaN/inf werden VOR dieser Funktion abgefangen, siehe authorize())."""
    base = requested_speed_scale if requested_speed_scale and requested_speed_scale > 0 \
        else gesture.speed_scale_default
    if gesture.schema_version == 1:
        return max(MIN_SPEED_SCALE_V1, min(MAX_SPEED_SCALE_V1, base))
    return max(MIN_SPEED_SCALE_V2, min(MAX_SPEED_SCALE_V2, base))


class GestureExecutionPolicy:
    """Zustandslos -- jeder Aufruf ist unabhaengig, kein Aufrufer darf
    sich auf eine vorherige Entscheidung verlassen (siehe Klassendoku:
    zwei separate Aufrufzeitpunkte)."""

    def authorize(
        self, gesture, runtime_context: RuntimeContext, execution_profile: str,
        requested_speed_scale: Optional[float] = None,
    ) -> GestureDecision:
        from ihk_pepper_interaction.resource_derivation import resources_for_gesture

        if execution_profile not in VALID_EXECUTION_PROFILES:
            return GestureDecision(
                False, "unbekanntes_profil",
                f"execution_profile '{execution_profile}' ist keinem der Profile "
                f"{VALID_EXECUTION_PROFILES} zugeordnet.",
                gesture.tested_status, 1.0, 0.0,
            )

        # NaN/inf im angeforderten speed_scale werden NIE stillschweigend
        # geklemmt -- ein ungueltiger numerischer Wert ist ein
        # sicherheitsrelevanter Fehler, keine Kalibrierungsfrage.
        if requested_speed_scale is not None and (
                requested_speed_scale != requested_speed_scale  # NaN
                or requested_speed_scale in (float("inf"), float("-inf"))):
            return GestureDecision(
                False, "speed_scale_ungueltig",
                f"requested_speed_scale={requested_speed_scale!r} ist NaN/inf.",
                gesture.tested_status, 1.0, 0.0,
            )

        effective_speed_scale = _effective_speed_scale(gesture, requested_speed_scale)
        expected_duration_s = gesture.duration_s() / effective_speed_scale
        resources = resources_for_gesture(gesture)

        # ---- tested_status: das eigentliche Kernstueck von AP8.1 ----
        # system_only/ein fest im Baum eingetragener Gestenname/ein
        # direkter Action-Aufruf aendern NICHTS an dieser Pruefung -- es
        # gibt keinen Parameter, der sie umgeht (Auftrag Abschnitt 5).
        minimum_status = _MINIMUM_TESTED_STATUS_BY_PROFILE[execution_profile]
        if _STATUS_RANK[gesture.tested_status] < _STATUS_RANK[minimum_status]:
            return GestureDecision(
                False, "tested_status_unzureichend",
                f"Geste '{gesture.name}' hat tested_status='{gesture.tested_status}', "
                f"Profil '{execution_profile}' verlangt mindestens '{minimum_status}'.",
                gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
            )

        # ---- max_duration_s: gilt in JEDEM Profil (kinematische
        # Sicherheitsgrenze, keine hardwarespezifische Freigabe). ----
        if gesture.max_duration_s is not None and expected_duration_s > gesture.max_duration_s:
            return GestureDecision(
                False, "max_duration_ueberschritten",
                f"Geste '{gesture.name}': effektive Dauer {expected_duration_s:.2f}s "
                f"ueberschreitet max_duration_s={gesture.max_duration_s}s bei "
                f"speed_scale={effective_speed_scale:.2f}.",
                gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
            )

        # ---- Laufzeitkontext: NUR fuer Profile relevant, die ueberhaupt
        # Hardware beruehren duerfen (Auftrag Abschnitt 5: offline_mock/
        # offline_preview "beruehren aber nie Hardware" -- Freshness ist
        # dort bedeutungslos, da nichts ausgefuehrt wird). ----
        if execution_profile in HARDWARE_CAPABLE_PROFILES:
            if runtime_context.safety_ok is not True:
                return GestureDecision(
                    False, "safety_state_ungueltig_oder_unbekannt",
                    "SafetyState fehlt, ist veraltet oder ungueltig -- jede Hardwaregeste "
                    "bleibt fail-closed gesperrt.",
                    gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
                )
            if runtime_context.pepper_reachable is not True:
                return GestureDecision(
                    False, "pepper_nicht_erreichbar",
                    "Pepper ist nicht erreichbar oder der Erreichbarkeitsstatus ist unbekannt.",
                    gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
                )
            # nav2_moving: unbekannt (None) wird wie "in Bewegung"
            # behandelt (Auftrag Abschnitt 6: "nav2_moving fehlt/veraltet
            # -> als Bewegung behandeln; stationaere Gesten sperren").
            nav2_moving_effective = runtime_context.nav2_moving is not False
            if nav2_moving_effective and (gesture.requires_stationary or gesture.schema_version == 2):
                return GestureDecision(
                    False, "nav2_moving_unklar_oder_aktiv",
                    f"Geste '{gesture.name}' braucht Stillstand, aber nav2_moving ist "
                    f"{runtime_context.nav2_moving!r} (unbekannt zaehlt als 'bewegt sich').",
                    gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
                )
            mapping_active_effective = runtime_context.mapping_active is not False
            if mapping_active_effective and gesture.affects_head():
                return GestureDecision(
                    False, "mapping_unklar_oder_aktiv",
                    f"Geste '{gesture.name}' bewegt Kopfgelenke, aber mapping_active ist "
                    f"{runtime_context.mapping_active!r} (unbekannt zaehlt als 'aktiv').",
                    gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
                )
            if gesture.allowed_interaction_states:
                state = runtime_context.current_interaction_state
                if state is None or state not in gesture.allowed_interaction_states:
                    return GestureDecision(
                        False, "interaktionszustand_unzulaessig",
                        f"Geste '{gesture.name}' im Zustand '{state}' nicht erlaubt "
                        f"(erlaubt: {gesture.allowed_interaction_states}).",
                        gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
                    )
            if runtime_context.lease_revoked:
                return GestureDecision(
                    False, "lease_widerrufen",
                    "Die fuer dieses Ziel gehaltene Aktuator-Lease wurde seit der letzten "
                    "Pruefung widerrufen/praemptiert.",
                    gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
                )

        return GestureDecision(
            True, "erlaubt", "Alle Bedingungen erfuellt.",
            gesture.tested_status, effective_speed_scale, expected_duration_s, resources,
        )
