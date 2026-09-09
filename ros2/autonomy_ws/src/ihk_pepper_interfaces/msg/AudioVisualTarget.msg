# Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4/11: EIN Ergebnis von
# audiovisual_association_node.py, veroeffentlicht fuer JEDEN
# Zuordnungsversuch -- auch eine Ablehnung (valid=false, KEIN
# track_id, mit Begruendung in reason). Bestaetigter Fund (AP6): das
# Zuordnungsergebnis lag bislang NUR auf dem Behavior-Tree-Blackboard,
# audio_focus_node.py bekam es nie mit (selected_track_id blieb dort
# immer -1). Dieses Topic ist die einzige Quelle, aus der
# audio_focus_node.py den ECHTEN bestaetigten Track uebernimmt.
#
# target_azimuth_rad_base ist der Peilwinkel des AUSGEWAEHLTEN Tracks
# relativ zu base_link (siehe audiovisual_association.py::bearing_deg),
# NICHT die urspruengliche Schallrichtung selbst -- bei einer Ablehnung
# (valid=false) bleibt er 0.0 (kein erfundener Winkel).

std_msgs/Header header
string event_id
# -1 bedeutet "keine Auswahl" -- gleiche Sentinel-Konvention wie
# AssociationResult.selected_track_id/kNoSelectedTrackId (Behavior Tree).
int32 track_id
float32 target_azimuth_rad_base
float32 distance_m
float32 angular_error_deg
float32 confidence
bool valid
string reason
