"""
Python-Spiegel von InteractionLifecycleState.msg (Entwicklungsauftrag
04-B, AP7, Abschnitt 9/23) -- gleiches Muster wie interaction_state.py's
InteractionState fuer DialogueState.msg. Dies ist der SITZUNGS-Zustand
(eine konkrete Person/Gruppe von "Pepper" bis Rueckkehr), NICHT der
grobe Supervisor-Zustand (InteractionState) -- beide bestehen
nebeneinander, unterschiedliche Granularitaet.

Nur die Enum-Werte + die Namenskonvertierung sind Teil dieses Commits
(Auftrag: "define ... contracts") -- die eigentliche
InteractionSession/Uebergangslogik folgt in einem spaeteren Commit
(siehe docs/INTERACTION_LIFECYCLE.md fuer den aktuellen Stand).

Entwicklungsauftrag 04-B, AP7.1, Abschnitt 16 ("Fehlerbehandlung"): das
Topic /interaction/lifecycle_state wird seit AP7.1 Commit 8/10
tatsaechlich veroeffentlicht -- allerdings direkt aus dem Behavior Tree
(neuer C++-Knoten PublishInteractionLifecycleState, siehe
ihk_pepper_behavior_tree/src/bt_nodes.cpp), NICHT ueber dieses
Python-Modul. Bisher WIRD NUR der state_name="ERROR"-Fall bei einem
fehlgeschlagenen ReturnToOriginViaBT ausgeloest (EndInteractionSubtree/
FollowCommandSubtree in pepper_main.xml) -- eine vollstaendige
Zustandsuebergangs-Nachbildung ALLER Enum-Werte ist weiterhin NICHT Teil
dieses Standes."""
from __future__ import annotations

from enum import IntEnum


class InteractionLifecycleState(IntEnum):
    IDLE = 0
    WAKEWORD_RECEIVED = 1
    TARGET_CONFIRMING = 2
    GREETING = 3
    APPROACHING = 4
    GROUP_POSITIONING = 5
    CONVERSATION = 6
    INTERRUPTING = 7
    FOLLOW_AUTHORIZATION = 8
    FOLLOWING = 9
    PERSON_LOST = 10
    GROUP_LOST = 11
    ENDING = 12
    RETURNING_TO_ORIGIN = 13
    SAFE_STOP = 14
    ERROR = 15


def state_name(state: InteractionLifecycleState) -> str:
    return state.name
