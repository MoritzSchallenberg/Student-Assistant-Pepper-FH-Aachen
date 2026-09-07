#!/usr/bin/env python3
"""
ihk_pepper_interaction: Supervisor (Arbeitspaket 38) + Interaktions-
Zustandsmaschine (Arbeitspaket 6).

Zentrale Instanz fuer SafetyState -- NUR hier wird allow_motion gesetzt,
nicht vom LLM/Dialogmanager direkt (Auftrag Abschnitt 35/3.4).

Standardmaessig `motion_capable:=false` (Auftrag Abschnitt 3.2) --
MUSS explizit per Launch-Parameter freigeschaltet werden:
    ros2 launch ihk_pepper_bringup full_system.launch.py motion_capable:=true

Getestet (2026-08-20): SafetyGate/InteractionStateMachine per Unit-Tests
(siehe ihk_pepper_tests). Node-Integration mit echten Bumper-/
Lokalisierungsdaten NICHT getestet (kein Pepper verbunden, keine Nav2-
Lokalisierung in dieser Session aufgesetzt) -- SafetyInputs fallen daher
in dieser Session auf sichere Defaults zurueck (siehe _build_safety_inputs).

Entwicklungsauftrag 04-B, AP2/AP3 -- drei konkrete Funde behoben:
1. /pepper_bridge/battery (Float32) wurde nie abonniert -- battery_percent
   blieb dauerhaft auf dem Konstruktor-Default 100.0 stehen, unabhaengig
   vom echten Akkustand. Jetzt echt abonniert; ein Bridge-Sentinelwert
   < 0 (bridge_node.py: "unbekannt") ODER ein veraltetes/nie empfangenes
   Signal wird als battery_percent=0.0 gewertet (garantiert
   low_battery_threshold, also fail-closed), NIE als 100.0.
2. compute_power_valid startete mit True (unsicherer Default, siehe
   Auftrag Abschnitt 7 explizit) -- jetzt False bis ein echtes Signal
   etwas anderes bestaetigt.
3. hardware_fault war fest auf False verdrahtet, ganz ohne reale Quelle.
   Jetzt aus /pepper_bridge/connection_state hergeleitet (ein bereits
   bestehendes, bisher komplett ungenutztes Bridge-Topic) --
   hardware_fault=True, ausser der frischeste Wert lautet exakt
   "connected".
JEDER hier verwendete Bool-/abgeleitete Eingang traegt jetzt einen
eigenen Ankunftszeitstempel (FreshBool, siehe safety_topics.py) --
fehlende oder veraltete Werte fallen individuell auf den sicheren Wert
zurueck, statt sich auf einen einzigen, nur fuer Personentrack-Alter
gedachten data_age_s zu verlassen (der bleibt fuer genau diesen Zweck
weiterhin bestehen, siehe _build_safety_inputs()).

/pepper_bridge/charging_state (= "laedt gerade", von Peppers
isCharging()-API) wird bewusst NICHT als charging_cable_connected
verwendet -- "laedt nicht" bedeutet nicht "Kabel ist getrennt" (Auftrag
Abschnitt 6, explizit). charging_cable_connected bleibt daher auf dem
sicheren Default True stehen, bis eine tatsaechlich vertrauenswuerdige
Quelle "Kabel getrennt" bestaetigt -- charging_state wird trotzdem
separat mitgefuehrt (_is_charging), fuer spaetere Diagnose/Akku-
Gesundheitsbewertung, aber strukturell getrennt von der
Sicherheitsentscheidung.
"""
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String, UInt8

from ihk_pepper_interfaces.msg import PersonTrackArray, SafetyState, DialogueState
from ihk_pepper_interfaces.srv import SetMotionPermission, SetSystemMode, SetInteractionState

from .safety_gate import SafetyGate, SafetyInputs
from .interaction_state import InteractionStateMachine, InteractionState
from . import safety_topics
from .safety_topics import FreshBool


class SupervisorNode(Node):
    def __init__(self):
        super().__init__("supervisor")

        self.declare_parameter("motion_capable", False)
        self.declare_parameter("low_battery_threshold", 15.0)
        self.declare_parameter("max_data_age_s", 2.0)
        self.declare_parameter("max_input_age_s", 2.0)
        self.declare_parameter("attract_interest_threshold", 0.5)
        self.declare_parameter("engage_interest_threshold", 0.7)

        motion_capable = self.get_parameter("motion_capable").value
        if motion_capable:
            self.get_logger().warn(
                "motion_capable=true -- Bewegungsfreigaben sind grundsaetzlich MOEGLICH. "
                "Sicherstellen dass die Umgebung sicher ist!"
            )
        else:
            self.get_logger().info("motion_capable=false (Standard) -- Bewegung bleibt gesperrt.")

        self.safety_gate = SafetyGate(motion_capable=motion_capable)
        self.state_machine = InteractionStateMachine(
            attract_interest_threshold=self.get_parameter("attract_interest_threshold").value,
            engage_interest_threshold=self.get_parameter("engage_interest_threshold").value,
        )

        self._last_tracks_t = None

        # Fail-closed-Ausweichwert je Eingang direkt am FreshBool
        # dokumentiert (True = "im Zweifel blockieren" fuer
        # Gefahrensignale, False = "im Zweifel NICHT gueltig" fuer
        # *_valid-Flags). Siehe Klassendocstring fuer die drei konkret
        # behobenen Funde (battery/compute_power_valid/hardware_fault).
        self._battery_valid = FreshBool(False)
        self._battery_percent_raw = 0.0
        self._compute_power_valid = FreshBool(False)
        self._localization_valid = FreshBool(False)
        self._obstacle_data_valid = FreshBool(False)
        self._person_depth_valid = FreshBool(False)
        self._bumper_active = FreshBool(True)
        self._bridge_connected = FreshBool(False)  # -> hardware_fault
        # Rein informativ, siehe Klassendocstring -- fliesst NICHT in
        # charging_cable_connected ein.
        self._is_charging = FreshBool(False)
        # charging_cable_connected: KEIN echter Publisher existiert
        # (siehe safety_topics.py), bleibt daher dauerhaft auf dem
        # sicheren Konstruktor-Default stehen ("angeschlossen bis
        # Gegenteil bekannt", siehe safety_gate.py). Trotzdem als
        # FreshBool gefuehrt, damit ein spaeteres echtes Signal ohne
        # weitere Codeaenderung andocken kann.
        self._charging_cable_connected = FreshBool(True)

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_person_tracks, 10)
        self.create_subscription(DialogueState, "/dialogue_state", self._on_dialogue_state, 10)
        self.create_subscription(Bool, safety_topics.BUMPER_TOPIC, self._on_bumper, 10)
        self.create_subscription(Float32, safety_topics.BATTERY_TOPIC, self._on_battery, 10)
        self.create_subscription(
            Bool, safety_topics.CHARGING_STATE_TOPIC, self._on_charging_state, 10)
        self.create_subscription(
            String, safety_topics.CONNECTION_STATE_TOPIC, self._on_connection_state, 10)
        self.create_subscription(
            Bool, safety_topics.COMPUTE_POWER_VALID_TOPIC, self._on_compute_power_valid, 10)
        self.create_subscription(
            Bool, safety_topics.LOCALIZATION_VALID_TOPIC, self._on_localization_valid, 10)
        self.create_subscription(
            Bool, safety_topics.OBSTACLE_DATA_VALID_TOPIC, self._on_obstacle_data_valid, 10)
        self.create_subscription(
            Bool, safety_topics.PERSON_DEPTH_VALID_TOPIC, self._on_person_depth_valid, 10)
        self.create_subscription(
            Bool, safety_topics.CHARGING_CABLE_CONNECTED_TOPIC,
            self._on_charging_cable_connected, 10)

        self.safety_pub = self.create_publisher(SafetyState, "safety_state", 10)
        self.create_timer(0.5, self._publish_safety_state)

        # Kein eigener InteractionState.msg-Typ definiert (siehe
        # docs/IMPLEMENTATION_REPORT.md) -- daher hier bewusst std_msgs/UInt8
        # (Zahlencode, wie InteractionState-IntEnum) + std_msgs/String
        # (Klartext-Name) statt eines neuen Interface-Typs. Fuer die
        # Tablet-UI (apps/web/tablet_ui.py) ausreichend, dokumentierte
        # reversible Annahme.
        self.interaction_state_pub = self.create_publisher(UInt8, "interaction_state", 10)
        self.interaction_state_name_pub = self.create_publisher(String, "interaction_state_name", 10)
        self.create_timer(0.5, self._publish_interaction_state)

        self.motion_permission_srv = self.create_service(
            SetMotionPermission, "set_motion_permission", self._handle_set_motion_permission
        )
        self.system_mode_srv = self.create_service(
            SetSystemMode, "set_system_mode", self._handle_set_system_mode
        )
        self.interaction_state_srv = self.create_service(
            SetInteractionState, "set_interaction_state", self._handle_set_interaction_state
        )

        self._current_mode = "auto"

        self.get_logger().info("supervisor gestartet.")

    def _now(self) -> float:
        return time.time()

    def _on_person_tracks(self, msg: PersonTrackArray):
        self._last_tracks_t = time.time()
        max_interest = max((t.interest_score for t in msg.tracks), default=0.0)
        self.state_machine.on_person_tracks(max_interest)

    def _on_dialogue_state(self, msg: DialogueState):
        if msg.state in (DialogueState.SPEAKING, DialogueState.LISTENING,
                          DialogueState.WAITING_FOR_FOLLOWUP, DialogueState.RETRIEVING,
                          DialogueState.THINKING, DialogueState.TRANSCRIBING):
            self.state_machine.on_dialogue_speaking_or_active()

    def _on_bumper(self, msg: Bool):
        self._bumper_active.update(msg.data, self._now())
        if msg.data:
            self.state_machine.trigger_safety_event()

    def _on_battery(self, msg: Float32):
        # bridge_node.py meldet -1.0 als expliziten "unbekannt"-Sentinel
        # (siehe pepper_client.get_battery()) -- NIE als echten
        # Prozentwert interpretieren.
        now = self._now()
        valid = msg.data >= 0.0
        self._battery_valid.update(valid, now)
        if valid:
            self._battery_percent_raw = float(msg.data)

    def _on_charging_state(self, msg: Bool):
        # Rein informativ (siehe Klassendocstring) -- beeinflusst
        # charging_cable_connected bewusst NICHT.
        self._is_charging.update(msg.data, self._now())

    def _on_connection_state(self, msg: String):
        self._bridge_connected.update(msg.data == "connected", self._now())

    def _on_compute_power_valid(self, msg: Bool):
        self._compute_power_valid.update(msg.data, self._now())

    def _on_localization_valid(self, msg: Bool):
        self._localization_valid.update(msg.data, self._now())

    def _on_obstacle_data_valid(self, msg: Bool):
        self._obstacle_data_valid.update(msg.data, self._now())

    def _on_person_depth_valid(self, msg: Bool):
        self._person_depth_valid.update(msg.data, self._now())

    def _on_charging_cable_connected(self, msg: Bool):
        self._charging_cable_connected.update(msg.data, self._now())

    def _build_safety_inputs(self) -> SafetyInputs:
        now = self._now()
        max_age = self.get_parameter("max_input_age_s").value
        data_age = (now - self._last_tracks_t) if self._last_tracks_t else 999.0

        battery_valid = self._battery_valid.effective(now, max_age, False)
        battery_percent = self._battery_percent_raw if battery_valid else 0.0

        return SafetyInputs(
            bumper_active=self._bumper_active.effective(now, max_age, True),
            # hardware_fault jetzt aus der echten Bridge-Verbindung
            # hergeleitet (siehe Klassendocstring, Fund 3) statt fest
            # False -- nie empfangen/veraltet/nicht "connected" -> Fehler.
            hardware_fault=not self._bridge_connected.effective(now, max_age, False),
            localization_valid=self._localization_valid.effective(now, max_age, False),
            battery_percent=battery_percent,
            low_battery_threshold=self.get_parameter("low_battery_threshold").value,
            user_stop_requested=self.state_machine.state == InteractionState.SAFE_STOP,
            obstacle_data_valid=self._obstacle_data_valid.effective(now, max_age, False),
            person_depth_valid=self._person_depth_valid.effective(now, max_age, False),
            charging_cable_connected=self._charging_cable_connected.effective(now, max_age, True),
            data_age_s=data_age,
            max_data_age_s=self.get_parameter("max_data_age_s").value,
            compute_power_valid=self._compute_power_valid.effective(now, max_age, False),
        )

    def _publish_safety_state(self):
        inputs = self._build_safety_inputs()
        result = self.safety_gate.evaluate(inputs)

        msg = SafetyState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.allow_motion = result["allow_motion"]
        msg.allow_person_approach = result["allow_person_approach"]
        msg.localization_valid = result["localization_valid"]
        msg.obstacle_data_valid = result["obstacle_data_valid"]
        msg.person_depth_valid = result["person_depth_valid"]
        msg.charging_cable_connected = result["charging_cable_connected"]
        msg.bumper_active = result["bumper_active"]
        msg.emergency_stop = result["emergency_stop"]
        msg.reason = result["reason"]
        msg.compute_power_valid = result["compute_power_valid"]
        self.safety_pub.publish(msg)

    def _publish_interaction_state(self):
        self.interaction_state_pub.publish(UInt8(data=int(self.state_machine.state)))
        self.interaction_state_name_pub.publish(String(data=self.state_machine.state.name))

    def _handle_set_motion_permission(self, request, response):
        self.safety_gate.request_motion_permission(
            request.allow_motion, request.allow_person_approach
        )
        response.success = True
        response.message = (
            "Angefragt -- wirksam nur wenn motion_capable=true UND keine "
            "Sicherheitsbedingung greift, siehe /safety_state"
        )
        return response

    def _handle_set_system_mode(self, request, response):
        valid_modes = ("auto", "manual", "maintenance", "off")
        if request.mode not in valid_modes:
            response.success = False
            response.message = f"Ungueltiger Modus, erlaubt: {valid_modes}"
            return response
        self._current_mode = request.mode
        response.success = True
        response.message = "OK"
        return response

    def _handle_set_interaction_state(self, request, response):
        """Fuer den SetInteractionState-BT-Knoten (Entwicklungsauftrag 1,
        Abschnitt 6). Der Supervisor bleibt die einzige Quelle der
        Wahrheit -- request_external_state() lehnt Wechsel in/aus
        ERROR/SAFE_STOP ab, siehe interaction_state.py."""
        accepted = self.state_machine.request_external_state(request.state_name)
        response.success = accepted
        response.message = "OK" if accepted else (
            f"Zustandswechsel zu '{request.state_name}' abgelehnt (unbekannter Name, "
            f"Sicherheitszustand betroffen, oder aktuell in ERROR/SAFE_STOP)"
        )
        return response


def main(args=None):
    rclpy.init(args=args)
    node = SupervisorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
