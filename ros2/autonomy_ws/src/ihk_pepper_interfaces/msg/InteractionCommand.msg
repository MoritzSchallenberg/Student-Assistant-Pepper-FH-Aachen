# Entwicklungsauftrag 04-B, AP7, Abschnitt 9/10: Ergebnis des
# deterministischen Sprachbefehls-Routers (command_router_node.py) --
# LAEUFT VOR jedem LLM-Aufruf, siehe dortige Moduldoku.
#
# raw_transcript ist ABSICHTLICH nur fluechtig gemeint (Auftrag Abschnitt
# 10: "Originaltranskript nur fluechtig") -- kein Konsument dieses
# Topics darf es dauerhaft speichern/loggen, siehe
# docs/PRIVILEGED_VOICE_COMMANDS.md. Wird NICHT in die Identity-/
# Vektordatenbank oder an das LLM weitergereicht.

std_msgs/Header header
string event_id

# Normalisierter, aus einer Allowlist stammender Befehlsname, z.B.
# "stop", "cancel", "interrupt_and_look", "follow_speaker",
# "dialogue_text" (kein Steuerbefehl -- normaler Gespraechstext, geht
# ans LLM weiter). NIE ein vom LLM erfundener Wert -- ausschliesslich
# aus codewords.yaml/der fest kodierten Stop-/Cancel-Liste abgeleitet.
string command

# NUR fluechtig gedacht, siehe Moduldoku oben.
string raw_transcript

# Schallrichtung des Befehls in base_link (rad, REP-103) -- 0.0 UND
# direction_valid=false bei fehlender/ungueltiger Richtung, NIE
# erfunden.
float32 direction_azimuth_rad_base
bool direction_valid

# -1 = keine zugeordnete Track-ID (Sentinel-Konvention wie ueberall
# sonst im Projekt).
int32 track_id

# Leer = keine bestaetigte Identitaet (Person bleibt implizit STUDENT).
string person_id

# Einer von: "student", "employee", "admin" -- siehe roles.py.
string role

float32 confidence

# Einer von: "not_required", "granted", "denied", "pending" -- siehe
# authorization_policy.py. "not_required" fuer Befehle, die keine
# Rolle brauchen (z.B. "stop", "eisenbahn"/interrupt_and_look).
string authorization_status

uint8 priority
string reason
