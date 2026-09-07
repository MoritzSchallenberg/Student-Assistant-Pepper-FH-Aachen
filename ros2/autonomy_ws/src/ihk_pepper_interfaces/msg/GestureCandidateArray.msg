# Veroeffentlicht vom gesture_memory_node nach jeder SearchGestures-
# Anfrage (Introspektion/Test/Debugging) -- dieselbe Ergebnisliste wie
# in der Service-Antwort, zusaetzlich auf einem Topic sichtbar.

std_msgs/Header header
GestureCandidate[] candidates
