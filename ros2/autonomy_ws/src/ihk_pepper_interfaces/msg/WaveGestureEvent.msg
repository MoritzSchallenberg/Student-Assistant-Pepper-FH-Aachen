# Zeitlich bestaetigtes Wink-/Rueckwink-Ereignis fuer EINE Track-ID+Seite
# (Entwicklungsauftrag 1, Abschnitt 5). Wird von
# ihk_pepper_perception/wave_detector.py erzeugt, sobald sich der Zustand
# aendert -- NICHT jeden Frame. Ein einzelnes Bild mit erhobener Hand
# erzeugt hoechstens ein Ereignis mit stable=false, NIE stable=true.

std_msgs/Header header

uint32 track_id
string gesture_name       # z.B. "wave_right", "wave_left" -- passend zum Gestenkatalog
float32 confidence        # 0..1, nur bei stable=true aussagekraeftig
bool stable                # true nur im Zustand WAVE_CONFIRMED
float32 observed_duration_s
builtin_interfaces/Time last_seen
string state               # "arm_raised" | "wave_candidate" | "wave_confirmed", fuer Diagnose
