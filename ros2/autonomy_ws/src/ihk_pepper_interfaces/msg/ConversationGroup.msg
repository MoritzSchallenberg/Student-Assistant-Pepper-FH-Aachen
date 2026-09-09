# Entwicklungsauftrag 04-B, AP7, Abschnitt 9/14: eine erkannte, ueber
# mehrere Frames stabile Gesprächsgruppe (group_tracking.py). group_id
# ist FLUECHTIG (Auftrag Abschnitt 14: "keine dauerhafte Identitaet") --
# NIEMALS als Schluessel in einer dauerhaften Datenbank verwenden.

std_msgs/Header header
string group_id
uint32[] member_track_ids

# -1 = kein bestaetigter aktiver Sprecher (Sentinel-Konvention).
int32 active_speaker_track_id

geometry_msgs/Point center_position
float32 minimum_member_distance_m
float32 maximum_member_distance_m

# Winkelspanne (rad) der Gruppe aus Sicht des aktuellen Beobachtungspunkts
# -- siehe group_tracking.py::compute_group_observation_pose().
float32 angular_span_rad

bool stable
float32 confidence
bool all_members_visible
