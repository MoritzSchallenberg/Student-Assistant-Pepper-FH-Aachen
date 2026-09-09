# Entwicklungsauftrag 04-B, AP6: horizontale Schallrichtung, von einem
# DirectionalAudioBackend geschaetzt (siehe
# ihk_pepper_audio/directional_audio.py,
# docs/AUDIO_FOCUS_AND_BEAMFORMING.md). Absichtlich KEIN Elevations-/
# Hoehenfeld -- ein Mikrofonarray dieser Bauart liefert nur einen
# verlaesslichen HORIZONTALEN Winkel, eine erfundene Elevation waere
# unbelegt (siehe Auftrag: "Keine erfundene Hoehenrichtung eintragen").
#
# azimuth_rad ist relativ zur mechanischen Vorwaerts-Ausrichtung des
# Mikrofonarrays selbst (respeaker_link, siehe TF-Kette in
# docs/RESPEAKER_CORE_V2_INTEGRATION.md) -- 0.0 = geradeaus, positiv =
# nach links gedreht (Standard-ROS-REP-103-Konvention, Rechte-Hand-Regel
# um die Z-Achse).

std_msgs/Header header
float32 azimuth_rad
float32 confidence
bool vad_active
bool valid
string backend
string reason
