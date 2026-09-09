# Entwicklungsauftrag 04-B, AP6: ein erkanntes Aktivierungswort
# ("Pepper"), getrennt von der vollen Whisper-Transkription (siehe
# ihk_pepper_audio/wakeword.py, docs/RESPEAKER_CORE_V2_INTEGRATION.md).
# event_id ist eine eindeutige, ueber alle nachfolgenden Stufen
# (Kopfausrichtung, audiovisuelle Zuordnung, Behavior Tree) erhaltene ID
# -- verhindert, dass ein spaeteres, ZWEITES Wakeword-Event faelschlich
# an eine bereits laufende Ausrichtung/Zuordnung andockt.
#
# direction_valid=false bedeutet: keine verlaessliche Richtungsschaetzung
# fuer DIESES Ereignis vorhanden -- der Aufrufer darf dann KEINE
# Kopfbewegung/Personenauswahl auf Basis dieses Events versuchen (siehe
# Auftrag Abschnitt 6/12: "Ist keine verlaessliche Richtungsbestimmung
# moeglich, darf das System nicht still auf eine angeblich gerichtete
# Aufnahme zurueckfallen").

std_msgs/Header header
string event_id
string keyword
float32 keyword_confidence
float32 azimuth_rad
float32 direction_confidence
bool direction_valid
