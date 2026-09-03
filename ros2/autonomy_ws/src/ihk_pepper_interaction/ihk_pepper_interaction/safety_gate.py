"""
Zentrale Sicherheitsfreigabe (Arbeitspaket 35/38) -- reine Logik.

WICHTIG: `allow_motion` kann durch SetMotionPermission NUR auf True
gesetzt werden, wenn der Node mit dem Launch-Parameter
`motion_capable:=true` gestartet wurde. Das ist der eigentliche
"Kill-Switch": ohne dieses Flag bleibt Fahren/Personenannaeherung IMMER
deaktiviert, unabhaengig davon, welcher Service-Aufruf reinkommt --
verhindert, dass ein Software-Fehler (oder das LLM, siehe Auftrag 3.4)
versehentlich Bewegung freischaltet.
"""
from dataclasses import dataclass


@dataclass
class SafetyInputs:
    bumper_active: bool = False
    hardware_fault: bool = False
    localization_valid: bool = True
    battery_percent: float = 100.0
    low_battery_threshold: float = 15.0
    user_stop_requested: bool = False
    obstacle_data_valid: bool = True
    person_depth_valid: bool = True
    charging_cable_connected: bool = True  # sicherer Default: "angeschlossen" bis Gegenteil bekannt
    data_age_s: float = 0.0
    max_data_age_s: float = 2.0
    # Entwicklungsauftrag 1, Abschnitt 10: Rechen-NUC-Eingang. Sicherer
    # Default True (wie charging_cable_connected) -- blockiert erst, wenn
    # ein echtes/Mock-Signal explizit False meldet.
    compute_power_valid: bool = True


class SafetyGate:
    def __init__(self, motion_capable: bool = False):
        self.motion_capable = motion_capable
        self._motion_requested = False
        self._approach_requested = False

    def request_motion_permission(self, allow_motion: bool, allow_person_approach: bool):
        """Wird vom SetMotionPermission-Service aufgerufen. Setzt nur die
        ANFRAGE -- ob sie tatsaechlich wirksam wird, entscheidet evaluate()
        anhand von motion_capable + den aktuellen SafetyInputs."""
        self._motion_requested = allow_motion
        self._approach_requested = allow_person_approach

    def evaluate(self, inputs: SafetyInputs):
        """Gibt (SafetyState-Felder als dict, reason) zurueck.
        Prioritaetsreihenfolge exakt wie Auftrag Abschnitt 38:
        1. Not-Stopp/Bumper 2. Hardwarefehler 3. Lokalisierungsverlust
        4. niedriger Akku 5. Nutzer-Stopp -- jedes davon blockiert
        Bewegung hart, unabhaengig von motion_capable."""
        reasons = []

        if inputs.bumper_active:
            reasons.append("bumper_active")
        if inputs.hardware_fault:
            reasons.append("hardware_fault")
        if not inputs.localization_valid:
            reasons.append("localization_invalid")
        if inputs.battery_percent < inputs.low_battery_threshold:
            reasons.append("low_battery")
        if inputs.user_stop_requested:
            reasons.append("user_stop")
        if not inputs.obstacle_data_valid:
            reasons.append("obstacle_data_invalid")
        if not inputs.person_depth_valid:
            reasons.append("person_depth_invalid")
        if inputs.charging_cable_connected:
            reasons.append("charging_cable_connected")
        if inputs.data_age_s > inputs.max_data_age_s:
            reasons.append("stale_sensor_data")
        if not inputs.compute_power_valid:
            reasons.append("compute_power_invalid")
        if not self.motion_capable:
            reasons.append("motion_capable_flag_not_set")

        hard_block = bool(reasons)
        allow_motion = self._motion_requested and not hard_block
        allow_person_approach = self._approach_requested and allow_motion

        return {
            "allow_motion": allow_motion,
            "allow_person_approach": allow_person_approach,
            "localization_valid": inputs.localization_valid,
            "obstacle_data_valid": inputs.obstacle_data_valid,
            "person_depth_valid": inputs.person_depth_valid,
            "charging_cable_connected": inputs.charging_cable_connected,
            "bumper_active": inputs.bumper_active,
            "compute_power_valid": inputs.compute_power_valid,
            "emergency_stop": inputs.bumper_active or inputs.hardware_fault,
            "reason": ",".join(reasons) if reasons else "ok",
        }
