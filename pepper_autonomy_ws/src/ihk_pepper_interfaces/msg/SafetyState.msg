# Zentrale Sicherheitsfreigabe. Wird ausschliesslich vom Supervisor
# (ihk_pepper_interaction/supervisor_node) gesetzt -- niemals vom LLM
# oder direkt aus dem Dialogsystem.

std_msgs/Header header
bool allow_motion
bool allow_person_approach
bool localization_valid
bool obstacle_data_valid
bool person_depth_valid
bool charging_cable_connected
bool bumper_active
bool emergency_stop
string reason
