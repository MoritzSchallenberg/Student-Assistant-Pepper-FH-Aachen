# Entwicklungsauftrag 04-B, AP6: Zustand der gespraechsbezogenen
# Audiofokussierung (siehe ihk_pepper_audio/audio_focus.py,
# docs/AUDIO_FOCUS_AND_BEAMFORMING.md).
#
# selected_track_id == -1 bedeutet "keine Person ausgewaehlt" (gleiche
# Sentinel-Konvention wie kNoSelectedTrackId im Behavior Tree,
# bt_nodes.hpp) -- bewusst int32 statt uint32 (anders als
# PersonTrack.msg::track_id), weil "kein Ziel" hier ein regulaerer,
# haeufiger Zustand ist, keine Ausnahme.
#
# mode ist einer der Zustandsnamen aus Auftrag Abschnitt 10:
# IDLE_WIDE | WAKEWORD_DETECTED | ORIENTING_TO_SOUND |
# VISUAL_CONFIRMATION | CONVERSATION_FOCUS | PEPPER_SPEAKING |
# RETURNING_TO_IDLE | AUDIO_DEGRADED

std_msgs/Header header
string mode
int32 selected_track_id
float32 target_azimuth_rad
bool valid
string backend
string reason
