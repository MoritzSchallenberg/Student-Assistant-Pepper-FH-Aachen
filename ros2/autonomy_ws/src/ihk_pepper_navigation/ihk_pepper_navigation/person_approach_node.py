#!/usr/bin/env python3
"""
ihk_pepper_navigation: Personen anfahren/begleiten (Arbeitspaket 7).

WICHTIGER EHRLICHER HINWEIS (siehe docs/IMPLEMENTATION_REPORT.md): Nav2 ist auf
diesem System NICHT installiert (kein sudo-Zugriff in dieser Session, nur
`nav2_msgs` als transitive Abhaengigkeit vorhanden) und `perception_node`
liefert aktuell KEINE 3D-Personenposition (`has_3d_position` immer False,
siehe ihk_pepper_perception). Dieser Node kann daher in dieser Session
NICHT tatsaechlich fahren -- das ist so beabsichtigt (Auftrag 3.2: keine
Bewegung ohne aktuelle Tiefen-/Hindernis-/Lokalisierungsdaten) und wird
hier auch strukturell erzwungen:

    JEDE Bewegungsfreigabe laeuft ausschliesslich ueber
    SafetyState.allow_person_approach (vom Supervisor gesetzt). Dieser
    Node fragt NIE eigene Sicherheitsbedingungen ab und kann sie nicht
    umgehen -- das ist Absicht (Auftrag Abschnitt 35: "niemals vom LLM
    oder Dialogsystem allein setzbar").

Was HIER vorbereitet ist: die vollstaendige Action-Server-Struktur mit
Zielpersonen-Auswahl/-Validierung, Zonen-Pruefung (zone_config.py) und
Nav2-ActionClient-Anbindung (nav2_msgs/action/NavigateToPose) inkl.
sauberem Fallback wenn Nav2 nicht erreichbar ist. Sobald Nav2 installiert
UND perception_node echte 3D-Positionen liefert UND motion_capable=true
gesetzt wird, sollte dieser Code ohne strukturelle Aenderungen funktionieren
-- das ist aber NICHT getestet.

Getestet (2026-08-20): Zielpersonen-Validierung (Confidence/Alter/3D-
Position/Keepout) und der Sicherheits-Abbruchpfad (safety_state.
allow_person_approach == False -> sofortiger, korrekter Abbruch) per
Unit-/Live-Node-Test. Der eigentliche Fahr-Pfad (Nav2-ActionClient-Aufruf)
ist NICHT getestet (Nav2 nicht installiert).

Entwicklungsauftrag 2, AP9 (siehe docs/DEVELOPMENT_ORDER_02_REPORT.md):
_drive_to_person() nutzte bisher die Personenposition SELBST als Nav2-
Ziel -- bestaetigter, dokumentierter Mangel aus Auftrag 1. Behoben durch
approach_pose.compute_approach_pose() (reine Geometrie, unit-getestet in
ihk_pepper_tests/test/test_approach_pose.py, unabhaengig von Nav2/RTAB-
Map-Verfuegbarkeit). Fehlende/veraltete TF fuer die Roboterpose fuehrt
IMMER zu einem Abbruch, NIE zu einer geschaetzten Position -- gleiches
Prinzip wie ihk_pepper_perception/perception_node.py::_transform_to_base_frame.
"""
import math
import os
import time

import rclpy
import tf2_ros
from rclpy.node import Node
from rclpy.action import ActionServer, ActionClient, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_interfaces.msg import PersonTrackArray, SafetyState
from ihk_pepper_interfaces.action import ApproachPerson, GuidePerson, FollowPerson

from .approach_pose import compute_approach_pose, is_track_fresh
from .zone_config import load_all_zones, point_in_any_keepout

MAX_TRACK_AGE_S = 2.0


def _yaw_to_quaternion(yaw_rad: float):
    """Reine 2D-Yaw->Quaternion-Konvertierung (roll=pitch=0), keine externe
    tf_transformations-Abhaengigkeit noetig fuer diesen einfachen Fall."""
    return 0.0, 0.0, math.sin(yaw_rad / 2.0), math.cos(yaw_rad / 2.0)


def _default_zones_dir():
    try:
        return os.path.join(get_package_share_directory("ihk_pepper_navigation"), "keepout_zones")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keepout_zones"
        )


class PersonApproachNode(Node):
    def __init__(self):
        super().__init__("person_approach")

        self.declare_parameter("zones_dir", _default_zones_dir())
        self.declare_parameter("min_confidence", 0.5)
        self.declare_parameter("target_distance_default_m", 1.0)
        self.declare_parameter("nav2_action_name", "navigate_to_pose")
        self.declare_parameter("nav2_connect_timeout_s", 2.0)
        self.declare_parameter("enable_follow_person", False)  # Abschnitt 3.2: experimentell, aus per Default

        # Entwicklungsauftrag 2, AP9: Annaeherungszielpose-Parameter.
        self.declare_parameter("minimum_person_distance_m", 0.5)
        self.declare_parameter("maximum_approach_distance_m", 8.0)
        self.declare_parameter("robot_base_frame", "base_link")
        self.declare_parameter("tf_lookup_timeout_s", 0.5)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        zones, errors = load_all_zones(self.get_parameter("zones_dir").value)
        for e in errors:
            self.get_logger().error(f"Zone ungueltig, uebersprungen: {e}")
        self.zones = zones
        self.get_logger().info(f"Keepout-/Speed-Zonen geladen: {list(self.zones.keys())}")

        self._tracks = {}  # track_id -> (PersonTrack, empfangszeit)
        self._safety_state = None

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_tracks, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)

        cb_group = ReentrantCallbackGroup()

        # nav2_msgs ist auf diesem System vorhanden (Message-Definitionen),
        # der Import wird daher NICHT defensiv behandelt -- ein fehlender
        # Nav2-Actionserver zur Laufzeit wird stattdessen sauber ueber
        # wait_for_server()-Timeouts abgefangen (siehe _drive_to_pose).
        from nav2_msgs.action import NavigateToPose
        self._nav2_client = ActionClient(
            self, NavigateToPose, self.get_parameter("nav2_action_name").value,
            callback_group=cb_group,
        )

        self.approach_server = ActionServer(
            self, ApproachPerson, "approach_person",
            execute_callback=self._execute_approach,
            goal_callback=self._goal_callback_approach,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )
        self.guide_server = ActionServer(
            self, GuidePerson, "guide_person",
            execute_callback=self._execute_guide,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )
        if self.get_parameter("enable_follow_person").value:
            self.get_logger().warn(
                "enable_follow_person=true -- FollowPerson ist EXPERIMENTELL "
                "und in dieser Session nicht getestet."
            )
            self.follow_server = ActionServer(
                self, FollowPerson, "follow_person",
                execute_callback=self._execute_follow,
                goal_callback=self._goal_callback_follow_person,
                cancel_callback=self._cancel_callback,
                callback_group=cb_group,
            )
        else:
            self.follow_server = None
            self.get_logger().info("FollowPerson-Action deaktiviert (enable_follow_person=false, Standard).")

        self.get_logger().info("person_approach gestartet.")

    # ---- Eingehende Daten ----

    def _on_tracks(self, msg: PersonTrackArray):
        now = time.time()
        for t in msg.tracks:
            self._tracks[t.track_id] = (t, now)

    def _on_safety_state(self, msg: SafetyState):
        self._safety_state = msg

    # ---- Zielpersonen-Validierung (Auftrag Abschnitt 7) ----

    def _validate_target(self, track_id: int):
        """Gibt (track, None) bei Erfolg zurueck, sonst (None, Grund)."""
        entry = self._tracks.get(track_id)
        if entry is None:
            return None, "person_lost"
        track, received_at = entry
        if not is_track_fresh(time.time() - received_at, MAX_TRACK_AGE_S):
            return None, "person_lost"
        if track.confidence < self.get_parameter("min_confidence").value:
            return None, "confidence_zu_niedrig"
        if not track.has_3d_position:
            return None, "keine_3d_position"
        if track.frame_id == "map" and point_in_any_keepout(
                self.zones, track.position_3d.x, track.position_3d.y):
            return None, "person_in_keepout_zone"
        return track, None

    def _safety_ok_for_approach(self):
        if self._safety_state is None:
            return False, "kein_safety_state_empfangen"
        if not self._safety_state.allow_person_approach:
            return False, self._safety_state.reason or "allow_person_approach_false"
        return True, ""

    # ---- ApproachPerson ----

    def _goal_callback_approach(self, goal_request):
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute_approach(self, goal_handle):
        result = ApproachPerson.Result()

        def feedback(status, distance=0.0):
            fb = ApproachPerson.Feedback()
            fb.status = status
            fb.distance_remaining_m = distance
            goal_handle.publish_feedback(fb)

        feedback("person_detected")
        track, reason = self._validate_target(goal_handle.request.track_id)
        if track is None:
            feedback(reason)
            result.success = False
            result.abort_reason = reason
            goal_handle.abort()
            return result

        feedback("validating")
        ok, reason = self._safety_ok_for_approach()
        if not ok:
            feedback("safety_abort")
            self.get_logger().warn(f"ApproachPerson abgebrochen (Sicherheit): {reason}")
            result.success = False
            result.abort_reason = f"safety_abort:{reason}"
            goal_handle.abort()
            return result

        feedback("planning")
        target_distance = goal_handle.request.target_distance_m or self.get_parameter(
            "target_distance_default_m").value
        ok, reason = self._drive_to_person(goal_handle, track, target_distance, feedback)
        if not ok:
            result.success = False
            result.abort_reason = reason
            goal_handle.abort()
            return result

        feedback("reached", 0.0)
        feedback("done", 0.0)
        result.success = True
        result.abort_reason = ""
        goal_handle.succeed()
        return result

    # ---- GuidePerson ----

    def _execute_guide(self, goal_handle):
        result = GuidePerson.Result()

        def feedback(status, distance=0.0, following=False):
            fb = GuidePerson.Feedback()
            fb.status = status
            fb.distance_remaining_m = distance
            fb.person_following = following
            goal_handle.publish_feedback(fb)

        feedback("validating")
        ok, reason = self._safety_ok_for_approach()
        if not ok:
            feedback("safety_abort")
            self.get_logger().warn(f"GuidePerson abgebrochen (Sicherheit): {reason}")
            result.success = False
            result.abort_reason = f"safety_abort:{reason}"
            goal_handle.abort()
            return result

        feedback("planning")
        ok, reason = self._drive_to_pose(goal_handle, goal_handle.request.destination,
                                          lambda s, d: feedback(s, d, True))
        if not ok:
            result.success = False
            result.abort_reason = reason
            goal_handle.abort()
            return result

        feedback("done", 0.0, True)
        result.success = True
        result.abort_reason = ""
        goal_handle.succeed()
        return result

    # ---- FollowPerson (experimentell, siehe enable_follow_person) ----

    def _goal_callback_follow_person(self, goal_request):
        self.get_logger().warn(
            "FollowPerson-Ziel angenommen -- EXPERIMENTELL, nicht getestet, "
            "siehe docs/IMPLEMENTATION_REPORT.md."
        )
        return GoalResponse.ACCEPT

    def _execute_follow(self, goal_handle):
        """Kein dedizierter Nav2-'Follow'-Server in ROS2 Jazzy vorausgesetzt
        -- eigener periodischer Ziel-Update-Loop als Fallback (Auftrag
        Abschnitt 7). Bricht bei jedem Sicherheitsproblem sofort ab."""
        result = FollowPerson.Result()
        track_id = goal_handle.request.track_id
        min_distance = goal_handle.request.min_distance_m or 1.0

        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                result.success = False
                result.abort_reason = "cancelled"
                goal_handle.canceled()
                return result

            ok, reason = self._safety_ok_for_approach()
            if not ok:
                fb = FollowPerson.Feedback()
                fb.status = "safety_abort"
                goal_handle.publish_feedback(fb)
                result.success = False
                result.abort_reason = f"safety_abort:{reason}"
                goal_handle.abort()
                return result

            track, reason = self._validate_target(track_id)
            fb = FollowPerson.Feedback()
            if track is None:
                fb.status = reason
                goal_handle.publish_feedback(fb)
                result.success = False
                result.abort_reason = reason
                goal_handle.abort()
                return result

            fb.status = "following"
            fb.current_distance_m = track.distance_m
            goal_handle.publish_feedback(fb)
            time.sleep(0.5)

        result.success = False
        result.abort_reason = "rclpy_shutdown"
        return result

    # ---- Nav2-Anbindung (siehe Moduldoku: strukturell vorbereitet, nicht getestet) ----

    def _get_robot_position_in_frame(self, frame_id, stamp):
        """Liefert (x, y, ok). Fehlende/veraltete TF fuehrt IMMER zu
        ok=False, NIE zu einer geschaetzten Position (Entwicklungsauftrag 2,
        AP9 -- gleiches Prinzip wie perception_node.py::_transform_to_base_frame).
        Ist die Person bereits im Basis-Frame des Roboters selbst
        angegeben (aktueller Stand ohne Lokalisierung, siehe AP1-Bericht),
        ist keine TF-Lookup noetig -- die Roboterpose ist per Definition
        der Ursprung dieses Frames."""
        robot_base_frame = self.get_parameter("robot_base_frame").value
        if frame_id == robot_base_frame:
            return 0.0, 0.0, True
        try:
            timeout = rclpy.duration.Duration(
                seconds=self.get_parameter("tf_lookup_timeout_s").value)
            transform = self.tf_buffer.lookup_transform(
                frame_id, robot_base_frame, stamp, timeout)
            t = transform.transform.translation
            return t.x, t.y, True
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException) as e:
            self.get_logger().warn(
                f"Keine TF {frame_id}->{robot_base_frame} fuer Roboterpose: {e}")
            return 0.0, 0.0, False

    def _drive_to_person(self, goal_handle, track, target_distance_m, feedback_cb):
        """Berechnet eine Gespraechs-Zielpose target_distance_m VOR der
        Person (approach_pose.compute_approach_pose) und delegiert an
        _drive_to_pose. NIEMALS die Personenposition selbst als Ziel --
        behebt den in Auftrag 1 dokumentierten Mangel (siehe
        docs/DEVELOPMENT_ORDER_02_REPORT.md, AP9)."""
        from geometry_msgs.msg import PoseStamped

        frame_id = track.frame_id or "map"
        robot_x, robot_y, tf_ok = self._get_robot_position_in_frame(
            frame_id, track.last_seen)
        if not tf_ok:
            return False, "keine_tf_fuer_roboterpose"

        result = compute_approach_pose(
            robot_x=robot_x, robot_y=robot_y,
            person_x=track.position_3d.x, person_y=track.position_3d.y,
            target_distance_m=target_distance_m,
            minimum_person_distance_m=self.get_parameter("minimum_person_distance_m").value,
            maximum_approach_distance_m=self.get_parameter("maximum_approach_distance_m").value,
            zones=self.zones,
        )
        if not result.valid:
            self.get_logger().warn(f"Annaeherungszielpose abgelehnt: {result.reason}")
            return False, result.reason

        if result.already_within_distance:
            feedback_cb("reached", 0.0)
            return True, ""

        pose = PoseStamped()
        pose.header.frame_id = frame_id
        pose.pose.position.x = result.target_x
        pose.pose.position.y = result.target_y
        pose.pose.position.z = 0.0
        qx, qy, qz, qw = _yaw_to_quaternion(result.target_yaw_rad)
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        distance_remaining = math.hypot(
            result.target_x - robot_x, result.target_y - robot_y)
        feedback_cb("moving", distance_remaining)
        return self._drive_to_pose(goal_handle, pose, feedback_cb)

    def _drive_to_pose(self, goal_handle, pose_stamped, feedback_cb):
        timeout = self.get_parameter("nav2_connect_timeout_s").value
        if not self._nav2_client.wait_for_server(timeout_sec=timeout):
            self.get_logger().error(
                "Nav2-ActionServer 'navigate_to_pose' nicht erreichbar -- "
                "Nav2 ist auf diesem System nicht installiert/gestartet."
            )
            return False, "nav2_nicht_erreichbar"

        from nav2_msgs.action import NavigateToPose
        goal = NavigateToPose.Goal()
        goal.pose = pose_stamped

        send_future = self._nav2_client.send_goal_async(goal)
        # Bewusst blockierend via Executor-Callback -- gleiches Muster wie
        # presentation_manager_node._say_and_wait (MultiThreadedExecutor
        # + ReentrantCallbackGroup vorausgesetzt, siehe main()).
        import threading
        done = threading.Event()
        outcome = {"success": False, "reason": "timeout"}

        def on_result(fut):
            try:
                r = fut.result()
                outcome["success"] = (r.status == 4)  # STATUS_SUCCEEDED
                outcome["reason"] = "" if outcome["success"] else f"nav2_status_{r.status}"
            except Exception as e:
                outcome["reason"] = str(e)
            done.set()

        def on_goal_response(fut):
            gh = fut.result()
            if not gh.accepted:
                outcome["reason"] = "nav2_goal_rejected"
                done.set()
                return
            rf = gh.get_result_async()
            rf.add_done_callback(on_result)

        send_future.add_done_callback(on_goal_response)
        if not done.wait(60.0):
            return False, "nav2_timeout"
        return outcome["success"], outcome["reason"]


def main(args=None):
    rclpy.init(args=args)
    node = PersonApproachNode()
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
