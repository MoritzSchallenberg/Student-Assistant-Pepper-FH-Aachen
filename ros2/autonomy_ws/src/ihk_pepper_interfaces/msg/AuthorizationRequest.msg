# Entwicklungsauftrag 04-B, AP7.1, Abschnitt 9: ereignisgebundene
# sekundaere Autorisierungsanfrage -- ERSETZT die globale
# /authorization/secondary_confirmation-Bool-Nachricht (Auftrag
# Abschnitt 3.2: eine globale Bool-Nachricht kann nicht beweisen,
# welche Person/welcher Befehl/welche Sitzung bestaetigt wurde, ob sie
# noch gueltig ist, oder ob sie bereits verwendet wurde).
#
# Veroeffentlicht von command_router_node.py, sobald ein privilegierter
# Befehl alle anderen Bedingungen erfuellt und NUR noch eine sekundaere
# Bestaetigung fehlt (z.B. am Tablet). NIEMALS automatisch bestaetigt --
# ConfirmAuthorization.srv (an request_id+nonce gebunden, einmalig
# verwendbar) ist der EINZIGE Weg, diese Anfrage zu entscheiden.

std_msgs/Header header
string request_id
string event_id
string interaction_id
string session_id
int32 track_id
string person_id
string role
string command
string requested_capability
builtin_interfaces/Time created_at
builtin_interfaces/Time expires_at
string nonce
string reason
