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
"""
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, UInt8, String

from ihk_pepper_interfaces.msg import PersonTrackArray, SafetyState, DialogueState
from ihk_pepper_interfaces.srv import SetMotionPermission, SetSystemMode

from .safety_gate import SafetyGate, SafetyInputs
from .interaction_state import InteractionStateMachine, InteractionState


class SupervisorNode(Node):
    def __init__(self):
        super().__init__("supervisor")

        self.declare_parameter("motion_capable", False)
        self.declare_parameter("low_battery_threshold", 15.0)
        self.declare_parameter("max_data_age_s", 2.0)
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

        self._battery_percent = 100.0
        self._last_health_t = None
        self._last_tracks_t = None

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_person_tracks, 10)
        self.create_subscription(DialogueState, "/dialogue_state", self._on_dialogue_state, 10)
        self.create_subscription(Bool, "/pepper_bridge/bumper", self._on_bumper, 10)

        self.safety_pub = self.create_publisher(SafetyState, "safety_state", 10)
        self.create_timer(0.5, self._publish_safety_state)

        # Kein eigener InteractionState.msg-Typ definiert (siehe
        # IMPLEMENTATION_REPORT.md) -- daher hier bewusst std_msgs/UInt8
        # (Zahlencode, wie InteractionState-IntEnum) + std_msgs/String
        # (Klartext-Name) statt eines neuen Interface-Typs. Fuer die
        # Tablet-UI (flask_wrapper/tablet_ui.py) ausreichend, dokumentierte
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

        self._bumper_active = False
        self._current_mode = "auto"

        self.get_logger().info("supervisor gestartet.")

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
        self._bumper_active = msg.data
        if msg.data:
            self.state_machine.trigger_safety_event()

    def _build_safety_inputs(self) -> SafetyInputs:
        now = time.time()
        data_age = (now - self._last_tracks_t) if self._last_tracks_t else 999.0
        return SafetyInputs(
            bumper_active=self._bumper_active,
            hardware_fault=False,  # kein Health-Aggregator in dieser Session verdrahtet
            localization_valid=False,  # keine Nav2-Lokalisierung in dieser Session aufgesetzt -- sicherer Default
            battery_percent=self._battery_percent,
            low_battery_threshold=self.get_parameter("low_battery_threshold").value,
            user_stop_requested=self.state_machine.state == InteractionState.SAFE_STOP,
            obstacle_data_valid=False,  # dito -- kein Laser-Filter-Node in dieser Session live verbunden
            person_depth_valid=False,   # dito -- keine 3D-Personenposition in dieser Session verdrahtet
            charging_cable_connected=True,  # sicherer Default, siehe SafetyInputs-Doku
            data_age_s=data_age,
            max_data_age_s=self.get_parameter("max_data_age_s").value,
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
