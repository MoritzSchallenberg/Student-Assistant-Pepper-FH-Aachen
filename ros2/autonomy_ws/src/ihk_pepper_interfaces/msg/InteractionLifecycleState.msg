# Entwicklungsauftrag 04-B, AP7, Abschnitt 9/23: Zustand des
# vollstaendigen PersonInteractionLifecycleSubtree (Python-Spiegel in
# ihk_pepper_interaction/interaction_lifecycle_state.py -- gleiches
# Muster wie DialogueState.msg/dialog_manager_node.py's
# InteractionState). Diese Zustandsmaschine ist der SITZUNGS-Zustand
# (eine konkrete Person/Gruppe), NICHT der grobe Supervisor-Zustand
# (InteractionState.msg/interaction_state.py) -- beide bleiben
# nebeneinander bestehen, unterschiedliche Granularitaet.

uint8 IDLE = 0
uint8 WAKEWORD_RECEIVED = 1
uint8 TARGET_CONFIRMING = 2
uint8 GREETING = 3
uint8 APPROACHING = 4
uint8 GROUP_POSITIONING = 5
uint8 CONVERSATION = 6
uint8 INTERRUPTING = 7
uint8 FOLLOW_AUTHORIZATION = 8
uint8 FOLLOWING = 9
uint8 PERSON_LOST = 10
uint8 GROUP_LOST = 11
uint8 ENDING = 12
uint8 RETURNING_TO_ORIGIN = 13
uint8 SAFE_STOP = 14
uint8 ERROR = 15

std_msgs/Header header
uint8 state
string state_name
string session_id
string reason
