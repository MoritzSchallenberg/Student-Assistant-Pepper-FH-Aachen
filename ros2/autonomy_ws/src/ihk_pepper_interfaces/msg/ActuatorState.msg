# Gesamtzustand des Aktuator-Arbiters (Entwicklungsauftrag 04-B, AP5B),
# veroeffentlicht auf /actuator_arbiter/state nach jeder Zustandsaenderung
# UND periodisch (damit Restlaufzeiten sichtbar bleiben, auch ohne neue
# Anfrage). Enthaelt bewusst keine Geheimnisse/personenbezogenen Daten.

std_msgs/Header header
ActuatorLease[] active_leases
ActuatorResourceState[] resources
bool safety_ok
string last_abort_reason
bool last_abort_confirmed
