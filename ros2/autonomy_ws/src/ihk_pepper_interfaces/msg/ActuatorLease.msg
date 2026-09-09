# Eine gewaehrte oder gerade widerrufene Aktuator-Arbiter-Lease
# (Entwicklungsauftrag 04-B, AP5B). remaining_s ist bereits vom
# actuator_arbiter_node berechnet (expires_at - jetzt, monotone Uhr) --
# Abonnenten muessen selbst keine Zeitstempel-Arithmetik ueber
# Prozessgrenzen hinweg durchfuehren.
#
# Enthaelt bewusst KEINE Geheimnisse/personenbezogenen Daten -- owner_id
# ist ein Node-/Komponentenname (z.B. "run_dialogue_action_server"),
# purpose eine kurze technische Bezeichnung (z.B. "play_gesture:greet_open"),
# nie ein Nutzertext.

string lease_id
string owner_id
string purpose
string[] resources
uint8 priority
float64 remaining_s
string goal_id
bool preempted
string preempted_reason
