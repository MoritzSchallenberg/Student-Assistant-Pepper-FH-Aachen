"""
Zentrale, gemeinsam genutzte Topic-Namen fuer sicherheitsrelevante
Signale (Entwicklungsauftrag 04-B, AP2: "Definiere eine zentrale,
dokumentierte Topic-Liste... Vermeide leicht abweichende Namen in
mehreren Paketen.").

Bewusst als eigenstaendige, ABSICHTLICH IDENTISCHE Kopie in
ihk_pepper_bridge, ihk_pepper_interaction UND (seit AP5A, fuer den
Gestensuche-Aufrufer im Dialogserver) ihk_pepper_dialog vorhanden
(gleiches Prinzip wie embedding_backend.py/_find_flask_wrapper_path()
an anderer Stelle in diesem Projekt) -- vermeidet eine neue
Cross-Package-Abhaengigkeit nur fuer eine Handvoll String-Konstanten.
Bei einer Aenderung MUESSEN die beiden anderen Kopien mitgepflegt
werden -- test_safety_topics_consistency.py prueft, dass alle drei
Dateien dieselben Konstanten/FreshBool exportieren (verhindert genau
das stillschweigende Auseinanderdriften, das AP2 als Fund beschreibt).

Fand beim Schreiben dieser Datei einen echten, bereits bestehenden
Fehler: motion_guard_node.py abonnierte bisher "/gesture_in_progress"
(ohne Namespace), waehrend bridge_node.py "gesture_in_progress" INNERHALB
des Namespace "pepper_bridge" veroeffentlicht -- also tatsaechlich unter
"/pepper_bridge/gesture_in_progress". Die beiden Themen haben SICH NIE
GETROFFEN. Der sichere Konstruktor-Default (gesture_in_progress=True,
also "es koennte gerade eine Geste laufen") blieb dadurch fuer immer
wirksam -- das ist zwar die sichere Richtung (blockiert Bewegung eher zu
oft als zu selten), bedeutet aber, dass echte Gestenendem NIE erkannt
wurden und enable_live_motion=true praktisch dauerhaft blockiert blieb.
Siehe DEVELOPMENT_ORDER_04B_REPORT.md.
"""

# Bridge-Namespace (siehe interaction_full_safe.launch.py:
# Node(package="ihk_pepper_bridge", executable="bridge_node",
# namespace="pepper_bridge", ...)).
PEPPER_BRIDGE_NAMESPACE = "pepper_bridge"

# Bridge-relative Themennamen -- GENAU diese Strings verwendet
# bridge_node.py in create_publisher(...), siehe dort.
BUMPER_TOPIC_RELATIVE = "bumper"
BATTERY_TOPIC_RELATIVE = "battery"
CHARGING_STATE_TOPIC_RELATIVE = "charging_state"
CONNECTION_STATE_TOPIC_RELATIVE = "connection_state"
GESTURE_IN_PROGRESS_TOPIC_RELATIVE = "gesture_in_progress"

# Absolute, vom Bridge-Namespace aufgeloeste Themennamen -- GENAU diese
# Strings verwenden ALLE Abonnenten AUSSERHALB der Bridge (Supervisor,
# Motion Guard, Dialogserver, ...).
BUMPER_TOPIC = f"/{PEPPER_BRIDGE_NAMESPACE}/{BUMPER_TOPIC_RELATIVE}"
BATTERY_TOPIC = f"/{PEPPER_BRIDGE_NAMESPACE}/{BATTERY_TOPIC_RELATIVE}"
CHARGING_STATE_TOPIC = f"/{PEPPER_BRIDGE_NAMESPACE}/{CHARGING_STATE_TOPIC_RELATIVE}"
CONNECTION_STATE_TOPIC = f"/{PEPPER_BRIDGE_NAMESPACE}/{CONNECTION_STATE_TOPIC_RELATIVE}"
GESTURE_IN_PROGRESS_TOPIC = f"/{PEPPER_BRIDGE_NAMESPACE}/{GESTURE_IN_PROGRESS_TOPIC_RELATIVE}"

# Sicherheits-/Navigationssignale ausserhalb der Bridge (bereits global,
# kein Namespace-Praefix).
LOCALIZATION_VALID_TOPIC = "/localization_valid"
OBSTACLE_DATA_VALID_TOPIC = "/obstacle_data_valid"
PERSON_DEPTH_VALID_TOPIC = "/person_depth_valid"
COMPUTE_POWER_VALID_TOPIC = "/compute_power_valid"
# KEIN echter Publisher existiert fuer dieses Thema (Stand 04-B) -- die
# einzige Quelle einer "Ladekabel wirklich getrennt"-Aussage waere ein
# dediziertes Hardware-/Kontaktsignal, das Peppers isCharging()-API
# strukturell nicht liefert (siehe safety_gate.py-Kommentar). Bleibt
# bewusst auf dem sicheren Default "verbunden" stehen, bis eine
# vertrauenswuerdige Quelle das ausdruecklich bestaetigt (Auftrag 04-B,
# Abschnitt 6: "muss der Zustand 'Kabel getrennt' separat bestaetigt
# werden").
CHARGING_CABLE_CONNECTED_TOPIC = "/charging_cable_connected"
NAV2_MOVING_TOPIC = "/nav2_moving"
MAPPING_ACTIVE_TOPIC = "/mapping_active"
SAFETY_STATE_TOPIC = "/safety_state"
# Entwicklungsauftrag 04-B, AP8.2: UInt8 (interaction_state.py::
# InteractionState-Enumwert), vom Supervisor veroeffentlicht -- bereits
# seit Arbeitspaket 6 bestehendes Topic, hier erstmals als benannte
# Konstante gefuehrt (vorher an mehreren Abonnentenstellen als rohes
# String-Literal "/interaction_state" wiederholt).
INTERACTION_STATE_TOPIC = "/interaction_state"
CMD_VEL_TOPIC = "/cmd_vel"
# Entwicklungsauftrag 04-B, AP5B, Abschnitt 13/BASE-Lease-Integration:
# vom actuator_arbiter_node veroeffentlicht (Node-Name "actuator_arbiter",
# Thema "~/base_lease_valid" -> ergibt diesen absoluten Pfad ohne
# zusaetzliches Remapping).
BASE_LEASE_VALID_TOPIC = "/actuator_arbiter/base_lease_valid"


class FreshBool:
    """Ein Bool mit Ankunftszeitstempel -- Aktualitaetspruefung fuer
    JEDEN sicherheitsrelevanten Eingang EINZELN (Entwicklungsauftrag
    04-B, AP2: 'Mindestens folgende Informationen brauchen: Wert,
    Gueltigkeitsstatus, Zeitstempel, maximales zulaessiges Alter'), statt
    -- wie bisher -- eines einzigen global geteilten data_age_s, das nur
    das Alter der Personentrack-Nachrichten widerspiegelte."""

    __slots__ = ("value", "received_at")

    def __init__(self, initial_value: bool):
        self.value = initial_value
        self.received_at = None  # None = noch nie empfangen

    def update(self, value: bool, now: float) -> None:
        self.value = value
        self.received_at = now

    def is_fresh(self, now: float, max_age_s: float) -> bool:
        if self.received_at is None:
            return False
        return (now - self.received_at) <= max_age_s

    def effective(self, now: float, max_age_s: float, fail_closed_value: bool) -> bool:
        """Liefert den aktuellen Wert, WENN er frisch ist -- sonst den
        uebergebenen sicheren Ausweichwert (typischerweise False fuer
        '..._valid'-Flags, True fuer Gefahrensignale wie
        bumper_active/hardware_fault)."""
        if self.is_fresh(now, max_age_s):
            return self.value
        return fail_closed_value


class FreshValue:
    """Wie FreshBool, aber fuer einen BELIEBIGEN Wert statt nur bool
    (Entwicklungsauftrag 04-B, AP8.2) -- z.B. den aktuellen
    InteractionState-Namen (String) oder einen anderen nicht-boolschen
    Laufzeitzustand. Bewusst dieselbe Aktualitaetslogik wie FreshBool
    (byte-identisch in ALLEN drei Kopien dieser Datei, siehe
    test_safety_topics_consistency.py), keine zweite, leicht
    abweichende Implementierung."""

    __slots__ = ("value", "received_at")

    def __init__(self, initial_value):
        self.value = initial_value
        self.received_at = None  # None = noch nie empfangen

    def update(self, value, now: float) -> None:
        self.value = value
        self.received_at = now

    def is_fresh(self, now: float, max_age_s: float) -> bool:
        if self.received_at is None:
            return False
        return (now - self.received_at) <= max_age_s

    def effective(self, now: float, max_age_s: float, fail_closed_value=None):
        """Liefert den aktuellen Wert, WENN er frisch ist -- sonst den
        uebergebenen Ausweichwert (typischerweise None = 'unbekannt',
        damit ein Aufrufer das fail-closed wie einen ungueltigen Wert
        behandeln kann, siehe gesture_execution_policy.py::RuntimeContext)."""
        if self.is_fresh(now, max_age_s):
            return self.value
        return fail_closed_value
