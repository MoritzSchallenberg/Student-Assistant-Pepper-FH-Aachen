# Entwicklungsauftrag 04-B, AP7, Abschnitt 9: Ergebnis der (optionalen)
# Zuordnung eines aktuellen RealSense-Tracks zu einer eingewilligten,
# registrierten Identitaet + deren Rolle. track_id und person_id bleiben
# ABSICHTLICH getrennte Felder (Entwicklungsauftrag 3: track_id ist nur
# fuer die Dauer der Sichtbarkeit gueltig, person_id ist dauerhaft) --
# dieselbe Trennung wie ueberall sonst im Projekt (PersonTrack.msg,
# GetPersonContext.srv).
#
# known=false ODER consent_granted=false ODER role_verified=false
# bedeutet IMMER: diese Person wird als STUDENT behandelt (sicherer
# Default, Auftrag Abschnitt 5) -- role bleibt in diesem Fall "student",
# NIE ein erfundener hoeherer Wert.

std_msgs/Header header
uint32 track_id
string person_id
string display_name

# Einer von: "student", "employee", "admin" -- siehe roles.py::VALID_ROLES.
# IMMER "student", wenn known/consent_granted/role_verified nicht alle
# true sind.
string role

float32 recognition_confidence
bool known
bool consent_granted

# Liveness = Bewegtbild-/Tiefenpruefung, dass eine reale Person vor der
# Kamera steht (kein Foto/Bildschirm) -- siehe
# docs/FACE_IDENTITY_AND_PRIVACY.md. NIE true ohne tatsaechliche Pruefung.
bool liveness_passed

# true NUR, wenn die Rolle tatsaechlich durch eine bestaetigte,
# aktuelle Identitaetszuordnung verifiziert wurde -- false bedeutet:
# role enthaelt trotzdem einen gueltigen Wert (immer "student" in
# diesem Fall), aber er ist NICHT verifiziert.
bool role_verified

string reason
