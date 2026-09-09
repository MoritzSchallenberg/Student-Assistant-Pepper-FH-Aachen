"""
Prioritaetsreihenfolge des deterministischen Sprachbefehls-Routers
(Entwicklungsauftrag 04-B, AP7, Abschnitt 10). NIEDRIGERER Wert =
HOEHERE Prioritaet (gleiche Konvention wie InteractionCommand.msg::priority).

WICHTIG: diese Werte sind KONZEPTUELL GETRENNT von
actuator_arbiter.py::PRIORITY_* (Aktuator-Lease-Prioritaeten, ein
anderer nummerischer Bereich/Zweck) -- absichtlich mit dem Praefix
COMMAND_PRIORITY_ benannt, um eine Verwechslung auszuschliessen.
"""
from __future__ import annotations

COMMAND_PRIORITY_EMERGENCY_STOP_BUMPER = 1
COMMAND_PRIORITY_STOP_CANCEL = 2
COMMAND_PRIORITY_CODEWORD_INTERRUPT = 3
COMMAND_PRIORITY_PRIVILEGED_MOTION = 4
COMMAND_PRIORITY_DIALOGUE_TEXT = 5

# Entwicklungsauftrag 04-B, AP7, Abschnitt 13: dieselbe VALID_COMMANDS-
# Allowlist wie codeword_config.py, hier auf ihre jeweilige Prioritaets-
# stufe abgebildet (Not-Stopp/Bumper ist kein Sprachbefehl, hat also
# keinen Eintrag hier -- das laeuft ausserhalb dieses Moduls, siehe
# safety_gate.py/motion_guard.py).
_COMMAND_PRIORITIES = {
    "stop": COMMAND_PRIORITY_STOP_CANCEL,
    "cancel": COMMAND_PRIORITY_STOP_CANCEL,
    "interrupt_and_look": COMMAND_PRIORITY_CODEWORD_INTERRUPT,
    "follow_speaker": COMMAND_PRIORITY_PRIVILEGED_MOTION,
}


def priority_for_command(command: str) -> int:
    """Fail-closed-Konvention: ein unbekannter Befehl gilt als
    normaler Dialogtext (niedrigste Prioritaet) -- NIE als
    hochprivilegiert, nur weil er nicht in der Tabelle steht."""
    return _COMMAND_PRIORITIES.get(command, COMMAND_PRIORITY_DIALOGUE_TEXT)
