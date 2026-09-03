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
