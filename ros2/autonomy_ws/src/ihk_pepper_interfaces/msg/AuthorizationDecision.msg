# Entwicklungsauftrag 04-B, AP7.1, Abschnitt 9: Ergebnis EINER
# ConfirmAuthorization.srv-Entscheidung -- veroeffentlicht von
# command_router_node.py, damit z.B. eine Tablet-UI den Ausgang einer
# eigenen Anfrage (oder deren Ablauf ohne Reaktion) sehen kann. Rein
# informativ, kein Aufrufer darf hieraus selbst eine Autorisierung
# ableiten (siehe AuthorizationGrant.msg fuer die tatsaechliche
# Bewegungsfreigabe).

std_msgs/Header header
string request_id
bool confirmed
string reason
builtin_interfaces/Time decided_at
