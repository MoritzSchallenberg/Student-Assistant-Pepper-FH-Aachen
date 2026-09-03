# Eine erkannte Person mit temporaerer Track-ID.
# KEINE Gesichtswiedererkennung, KEINE dauerhafte biometrische Identitaet --
# track_id gilt nur fuer die Dauer der Sichtbarkeit dieser Person.

std_msgs/Header header

uint32 track_id
float32 confidence

# 2D Bounding Box im Kamerabild (Pixel)
int32 bbox_x
int32 bbox_y
int32 bbox_width
int32 bbox_height

# 2D Bildposition (Pixel, Zentrum der Bounding Box)
float32 image_x
float32 image_y

# 3D Position, falls Tiefendaten verfuegbar
bool has_3d_position
geometry_msgs/Point position_3d
string frame_id

builtin_interfaces/Time last_seen

float32 distance_m

# Geschaetzte Bewegungsrichtung/Geschwindigkeit (m/s), falls ueber mehrere Frames berechenbar
bool has_velocity
geometry_msgs/Vector3 velocity

# Grobe Koerperausrichtung relativ zu Pepper (rad). NaN wenn unbekannt.
float32 body_orientation_rad

# 0.0 (kein Interesse) bis 1.0 (hohes Interesse), siehe ihk_pepper_perception/interest_scoring.py
float32 interest_score

# Erweiterung Entwicklungsauftrag 1, Abschnitt 4: Stabilitaet ueber
# mehrere Frames, unabhaengig vom interest_score (der bewertet
# Interesse, nicht Track-Guete). Von SelectStablePerson im Behavior Tree
# genutzt, um vorschnelle Zielauswahl auf einem gerade erst erschienenen
# Track zu vermeiden.
bool stable
float32 stable_for_s

# Konfidenz der Tiefenschaetzung selbst (Streuung im Entprojektions-
# Pixelpatch, 0..1), NICHT zu verwechseln mit "confidence" oben
# (Erkennungs-/Tracking-Konfidenz von YOLO/ByteTrack). 0.0 wenn
# has_3d_position=False.
float32 depth_confidence

# Woher diese Positions-/Tiefeninformation stammt, z.B. "realsense",
# "pepper_camera_2d_only" -- siehe docs/ARCHITECTURE_REALSense_BT.md.
string source_camera
