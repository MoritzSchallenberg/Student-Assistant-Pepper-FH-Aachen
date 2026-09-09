# Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9: kurzlebige Berechtigung
# fuer EINEN privilegierten Befehl EINER Person. Veroeffentlicht KEINEN
# geheimen Schluessel -- grant_id ist nur eine zufaellige Referenz, kein
# Kryptomaterial (Auftrag: "Keine geheimen Schluessel veroeffentlichen").
#
# Eine Berechtigung ist an person_id + track_id + command GEBUNDEN und
# darf NIE fuer eine andere Person/Track/einen anderen Befehl
# wiederverwendet werden -- siehe authorization_policy.py::
# grant_matches().

std_msgs/Header header
string grant_id
string person_id
uint32 track_id
string command
string session_id
builtin_interfaces/Time created_at
builtin_interfaces/Time expires_at
bool valid
string reason
