#!/usr/bin/env python3
"""
orient_to_sound_node: semantische Ausrichtung von Peppers Kopf auf eine
gemessene Schallrichtung (Entwicklungsauftrag 04-B, AP6, Abschnitt 7/12).
Berechnet aus einer bereits nach base_link transformierten Schallrichtung
ein sicheres, begrenztes Kopfziel und ruft SetHeadPose auf -- fuehrt
selbst KEINE eigene Gelenkbewegung/Lease-Verwaltung aus (das macht
SetHeadPose in bridge_node.py, inklusive HEAD-Lease-Erwerb/-Freigabe).

Sicherheitsvorbedingungen (Auftrag Abschnitt 12) werden VOR jedem
Ausrichtungsversuch geprueft: conversation_active=false,
mapping_active=false, nav2_moving=false, Pepper-Verbindung bestaetigt
gueltig, SafetyState frisch und ohne Not-Halt/Bumper. Bei fehlender/
veralteter Voraussetzung wird NICHT ausgerichtet -- fail-closed, exakt
wie ueberall sonst in diesem Projekt.

HeadPitch wird NIE aus der Schallrichtung berechnet -- ein
Mikrofonarray liefert nur einen horizontalen Winkel, keine Elevation
(siehe SoundDirection.msg). Der Kopf bleibt beim Ausrichten auf einer
festen, sicheren Beobachtungsposition (HEAD_PITCH_SAFE_OBSERVATION_RAD).

Geraeusche HINTER Pepper duerfen NIEMALS automatisch eine Basisdrehung
ausloesen -- dieser Node ruft ausschliesslich SetHeadPose auf, nie
irgendeine Navigations-/Basis-Action.
"""
import threading
import time

import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from std_msgs.msg import Bool, String, UInt8

from ihk_pepper_interfaces.action import OrientToSound, SetHeadPose
from ihk_pepper_interfaces.msg import SafetyState

from . import safety_topics
from .interaction_state import InteractionState
from .safety_topics import FreshBool

# Konservative, feste Beobachtungsposition -- KEINE Elevation aus der
# Schallrichtung (siehe Moduldoku). Identisch zu den in bridge_node.py
# definierten operativen Grenzen fuer den Yaw-Bereich (dort erneut
# geklemmt -- Verteidigung in der Tiefe, dieser Node vertraut sich selbst
# nicht blind).
HEAD_PITCH_SAFE_OBSERVATION_RAD = -0.1
HEAD_YAW_OPERATIONAL_MIN_RAD = -1.2
HEAD_YAW_OPERATIONAL_MAX_RAD = 1.2
ORIENT_SPEED_SCALE = 0.5  # "vorsichtig" (Auftrag Abschnitt 1: "dreht ausschliesslich seinen Kopf vorsichtig")

SAFETY_STATE_MAX_AGE_S = 2.0
SET_HEAD_POSE_TIMEOUT_S = 10.0
SET_HEAD_POSE_CANCEL_GRACE_S = 2.0


class OrientToSoundNode(Node):
    def __init__(self):
        super().__init__("orient_to_sound")

        self.declare_parameter("interaction_state_max_age_s", 3.0)
        self.declare_parameter("mapping_active_max_age_s", 2.0)
        self.declare_parameter("nav2_moving_max_age_s", 1.0)
        self.declare_parameter("connection_state_max_age_s", 5.0)

        self._interaction_state_value = InteractionState.IDLE
        self._interaction_state_received_at = None
        # Fail-closed: unbekannt/veraltet -> "aktiv"/"nicht gueltig"
        # annehmen, blockiert die Ausrichtung eher, statt sie faelschlich
        # freizugeben.
        self._mapping_active = FreshBool(True)
        self._nav2_moving = FreshBool(True)
        self._connection_state_value = "disconnected"
        self._connection_state_received_at = None
        self._safety_state = None
        self._safety_state_received_at = None

        self.create_subscription(UInt8, "/interaction_state", self._on_interaction_state, 10)
        self.create_subscription(
            Bool, safety_topics.MAPPING_ACTIVE_TOPIC, self._on_mapping_active, 10)
        self.create_subscription(
            Bool, safety_topics.NAV2_MOVING_TOPIC, self._on_nav2_moving, 10)
        self.create_subscription(
            String, safety_topics.CONNECTION_STATE_TOPIC, self._on_connection_state, 10)
        self.create_subscription(
            SafetyState, safety_topics.SAFETY_STATE_TOPIC, self._on_safety_state, 10)

        cb_group = ReentrantCallbackGroup()
        self.set_head_pose_client = ActionClient(
            self, SetHeadPose, "/pepper_bridge/set_head_pose", callback_group=cb_group)

        self.action_server = ActionServer(
            self, OrientToSound, "orient_to_sound",
            execute_callback=self._execute,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )

        self.get_logger().info("orient_to_sound gestartet.")

    # ---- Eingehende Signale ----

    def _on_interaction_state(self, msg: UInt8):
        self._interaction_state_value = msg.data
        self._interaction_state_received_at = time.monotonic()

    def _on_mapping_active(self, msg: Bool):
        self._mapping_active.update(msg.data, time.monotonic())

    def _on_nav2_moving(self, msg: Bool):
        self._nav2_moving.update(msg.data, time.monotonic())

    def _on_connection_state(self, msg: String):
        self._connection_state_value = msg.data
        self._connection_state_received_at = time.monotonic()

    def _on_safety_state(self, msg: SafetyState):
        self._safety_state = msg
        self._safety_state_received_at = time.monotonic()

    # ---- Sicherheitspruefungen ----

    def _conversation_active(self) -> bool:
        max_age = self.get_parameter("interaction_state_max_age_s").value
        if self._interaction_state_received_at is None:
            return True
        if (time.monotonic() - self._interaction_state_received_at) > max_age:
            return True
        return self._interaction_state_value != InteractionState.IDLE

    def _safety_ok_for_orientation(self):
        """Gibt (ok, reason) zurueck -- reason bleibt leer wenn ok=True."""
        now = time.monotonic()
        if self._conversation_active():
            return False, "Gespraech aktiv -- keine Wakeword-Ausrichtung waehrend laufender Interaktion"
        if self._mapping_active.effective(now, self.get_parameter("mapping_active_max_age_s").value, True):
            return False, "Mapping aktiv -- Kopf bleibt fest (RealSense-Pose beeinflusst SLAM)"
        if self._nav2_moving.effective(now, self.get_parameter("nav2_moving_max_age_s").value, True):
            return False, "Nav2 faehrt -- keine Wakeword-Kopfbewegung waehrend aktiver Fahrt"
        max_conn_age = self.get_parameter("connection_state_max_age_s").value
        if (self._connection_state_received_at is None
                or (now - self._connection_state_received_at) > max_conn_age
                or self._connection_state_value != "connected"):
            return False, "Pepper-Verbindung nicht bestaetigt gueltig"
        if (self._safety_state_received_at is None
                or (now - self._safety_state_received_at) > SAFETY_STATE_MAX_AGE_S):
            return False, "SafetyState veraltet oder fehlt"
        if self._safety_state.emergency_stop or self._safety_state.bumper_active:
            return False, "Sicherheitsereignis aktiv (Not-Halt/Bumper)"
        return True, ""

    # ---- Action ----

    def _goal_callback(self, goal_request):
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        result = OrientToSound.Result()
        request = goal_handle.request
        feedback = OrientToSound.Feedback()

        feedback.status = "validating"
        goal_handle.publish_feedback(feedback)

        measured_at_s = request.measured_at.sec + request.measured_at.nanosec / 1e9
        now_wall_s = self.get_clock().now().nanoseconds / 1e9
        age_s = now_wall_s - measured_at_s
        if request.max_measurement_age_s > 0.0 and age_s > request.max_measurement_age_s:
            result.success = False
            result.error_message = (
                f"Schallrichtungsmessung zu alt ({age_s:.2f}s > "
                f"{request.max_measurement_age_s:.2f}s)"
            )
            goal_handle.abort()
            return result

        ok, reason = self._safety_ok_for_orientation()
        if not ok:
            result.success = False
            result.error_message = reason
            goal_handle.abort()
            return result

        # Konservative operative Grenze -- Verteidigung in der Tiefe,
        # bridge_node.py::_execute_set_head_pose() klemmt ohnehin nochmal.
        target_yaw = max(HEAD_YAW_OPERATIONAL_MIN_RAD,
                          min(HEAD_YAW_OPERATIONAL_MAX_RAD, request.azimuth_rad_base_link))

        feedback.status = "orienting"
        goal_handle.publish_feedback(feedback)

        if not self.set_head_pose_client.wait_for_server(timeout_sec=2.0):
            result.success = False
            result.error_message = "SetHeadPose-Action nicht erreichbar"
            goal_handle.abort()
            return result

        head_goal = SetHeadPose.Goal()
        head_goal.head_yaw_rad = target_yaw
        head_goal.head_pitch_rad = HEAD_PITCH_SAFE_OBSERVATION_RAD
        head_goal.max_speed_scale = ORIENT_SPEED_SCALE
        head_goal.source_stamp = request.measured_at
        head_goal.max_source_age_s = request.max_measurement_age_s
        head_goal.owner_id = "orient_to_sound"

        success, final_yaw, error_message = self._send_goal_and_wait(head_goal, goal_handle)

        feedback.status = "done"
        goal_handle.publish_feedback(feedback)

        result.success = success
        result.final_head_yaw_rad = final_yaw
        result.error_message = error_message
        if success:
            goal_handle.succeed()
        else:
            goal_handle.abort()
        return result

    def _send_goal_and_wait(self, head_goal, orient_goal_handle, timeout_s: float = SET_HEAD_POSE_TIMEOUT_S):
        """Blockiert bis SetHeadPose fertig ist, bis orient_goal_handle
        selbst abgebrochen wird, oder bis timeout_s erreicht ist --
        NIEMALS unbegrenzt (gleiches Prinzip wie ueberall sonst in diesem
        Projekt seit AP5B). Gibt (success, final_head_yaw_rad,
        error_message) zurueck."""
        done_event = threading.Event()
        outcome = {"success": False, "final_yaw": head_goal.head_yaw_rad, "error": ""}
        goal_state = {"handle": None}

        def on_result(fut):
            try:
                res = fut.result().result
                outcome["success"] = res.success
                outcome["final_yaw"] = res.final_head_yaw_rad
                outcome["error"] = res.error_message
            except Exception as e:
                outcome["error"] = str(e)
            done_event.set()

        def on_goal_response(fut):
            gh = fut.result()
            goal_state["handle"] = gh
            if not gh.accepted:
                outcome["error"] = "SetHeadPose-Ziel abgelehnt"
                done_event.set()
                return
            rf = gh.get_result_async()
            rf.add_done_callback(on_result)

        send_future = self.set_head_pose_client.send_goal_async(head_goal)
        send_future.add_done_callback(on_goal_response)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if done_event.wait(0.1):
                return outcome["success"], outcome["final_yaw"], outcome["error"]
            if orient_goal_handle.is_cancel_requested and goal_state["handle"] is not None:
                goal_state["handle"].cancel_goal_async()
                done_event.wait(SET_HEAD_POSE_CANCEL_GRACE_S)
                return False, outcome["final_yaw"], "abgebrochen"

        if goal_state["handle"] is not None:
            goal_state["handle"].cancel_goal_async()
        return False, head_goal.head_yaw_rad, "Zeitueberschreitung beim Ausrichten"


def main(args=None):
    rclpy.init(args=args)
    node = OrientToSoundNode()
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
