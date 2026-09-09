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
from std_msgs.msg import Bool

from ihk_pepper_interfaces.msg import AuthorizationGrant, PersonTrackArray, SafetyState, SystemHealth
from ihk_pepper_interfaces.action import ApproachPerson, GuidePerson, FollowPerson
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease, RenewActuatorLease

from ihk_pepper_interaction.actuator_arbiter import BASE, PRIORITY_NAVIGATION

from .approach_pose import compute_approach_pose, is_track_fresh, should_replan
from .authorization_grant_cache import AuthorizationGrantCache
from .follow_person_safety import (
    FollowPersonSafetyContext,
    check_follow_person_safety,
    is_crowd_ambiguous,
)
from .zone_config import load_all_zones, point_in_any_keepout

MAX_TRACK_AGE_S = 2.0

# Entwicklungsauftrag 04-B, AP5B, Abschnitt 14: Navigation muss vor JEDER
# Fahrt eine BASE-Lease vom zentralen Aktuator-Arbiter halten -- Motion
# Guard blockiert sonst jeden von Null verschiedenen Fahrbefehl (siehe
# ihk_pepper_interaction/motion_guard.py). Eine laengere Fahrt erneuert
# die Lease periodisch, statt sich auf eine einzelne, sehr lange TTL zu
# verlassen (Auftrag: "waehrend laengerer Navigation erneuern").
OWNER_ID = "person_approach"
BASE_LEASE_TTL_S = 20.0
BASE_LEASE_RENEW_INTERVAL_S = 10.0  # deutlich unter der TTL, genug Sicherheitsmarge


def _yaw_to_quaternion(yaw_rad: float):
    """Reine 2D-Yaw->Quaternion-Konvertierung (roll=pitch=0), keine externe
    tf_transformations-Abhaengigkeit noetig fuer diesen einfachen Fall."""
    return 0.0, 0.0, math.sin(yaw_rad / 2.0), math.cos(yaw_rad / 2.0)


def _angle_diff_rad(a: float, b: float) -> float:
    """Kuerzeste Winkeldifferenz a-b, auf [-pi, pi] normiert."""
    return (a - b + math.pi) % (2 * math.pi) - math.pi


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

        # Entwicklungsauftrag 04-B, AP7, Abschnitt 19: FollowPerson-
        # Parameter exakt nach Auftrag -- enabled bleibt bis zu
        # erfolgreichen Hardwaretests Standard false (enable_follow_person
        # oben ist der bestehende, uebergeordnete Schalter).
        self.declare_parameter("follow_person_target_distance_m", 1.2)
        self.declare_parameter("follow_person_minimum_distance_m", 0.8)
        self.declare_parameter("follow_person_maximum_distance_m", 4.0)
        self.declare_parameter("follow_person_goal_update_rate_hz", 1.0)
        self.declare_parameter("follow_person_minimum_goal_shift_m", 0.25)
        self.declare_parameter("follow_person_minimum_goal_yaw_change_rad", 0.20)
        self.declare_parameter("follow_person_loss_timeout_s", 2.0)
        self.declare_parameter("follow_person_maximum_duration_s", 300.0)
        self.declare_parameter("follow_person_allow_in_crowds", False)
        self.declare_parameter("follow_person_crowd_proximity_m", 1.0)
        self.declare_parameter("follow_person_minimum_battery_percent", 20.0)

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
        self._latest_health = None
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9/19: gespeiste
        # Kopie der von command_router_node.py ausgestellten Grants --
        # kein gemeinsamer Prozessspeicher noetig (siehe
        # authorization_grant_cache.py-Moduldoku).
        self._grant_cache = AuthorizationGrantCache()

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_tracks, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)
        self.create_subscription(SystemHealth, "system_health", self._on_system_health, 10)
        self.create_subscription(AuthorizationGrant, "/authorization/grants", self._on_grant, 10)

        # Entwicklungsauftrag 2, AP10: waehrend Nav2 aktiv faehrt, muessen
        # Arm-/Kopfgesten gesperrt sein (gesture_catalog.py::play() kann
        # das bereits seit Auftrag 1 pruefen -- bridge_node.py's
        # PlayGesture-Handler abonniert dieses Topic, um es tatsaechlich
        # zu uebergeben, siehe docs/DEVELOPMENT_ORDER_02_REPORT.md AP10).
        self.nav2_moving_pub = self.create_publisher(Bool, "/nav2_moving", 10)
        self.nav2_moving_pub.publish(Bool(data=False))

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

        # Entwicklungsauftrag 04-B, AP5B, Abschnitt 14: Service-Clients
        # zum zentralen Aktuator-Arbiter, gleiches Muster wie
        # ihk_pepper_bridge/bridge_node.py (Commit 2).
        self.acquire_lease_client = self.create_client(
            AcquireActuatorLease, "/actuator_arbiter/acquire", callback_group=cb_group)
        self.renew_lease_client = self.create_client(
            RenewActuatorLease, "/actuator_arbiter/renew", callback_group=cb_group)
        self.release_lease_client = self.create_client(
            ReleaseActuatorLease, "/actuator_arbiter/release", callback_group=cb_group)

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

    def _on_system_health(self, msg: SystemHealth):
        self._latest_health = msg

    def _on_grant(self, msg: AuthorizationGrant):
        if not msg.valid:
            return
        expires_at_s = msg.expires_at.sec + msg.expires_at.nanosec / 1e9
        self._grant_cache.add(msg.grant_id, msg.person_id, msg.track_id, msg.command, expires_at_s)

    # ---- Zielpersonen-Validierung (Auftrag Abschnitt 7) ----

    def _validate_target(self, track_id: int, max_track_age_s: float = MAX_TRACK_AGE_S):
        """Gibt (track, None) bei Erfolg zurueck, sonst (None, Grund).
        max_track_age_s ist optional ueberschreibbar (Entwicklungsauftrag
        04-B, AP7: FollowPerson.Goal.max_track_loss_timeout_s) -- Default
        bleibt fuer alle bestehenden Aufrufer unveraendert."""
        entry = self._tracks.get(track_id)
        if entry is None:
            return None, "person_lost"
        track, received_at = entry
        if not is_track_fresh(time.time() - received_at, max_track_age_s):
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

    # ---- FollowPerson (Entwicklungsauftrag 04-B, AP7, Abschnitt 19/20;
    #      standardmaessig deaktiviert, siehe enable_follow_person) ----

    def _goal_callback_follow_person(self, goal_request):
        return GoalResponse.ACCEPT

    def _build_follow_safety_context(self, track_id: int, authorization_valid: bool,
                                      target_x: float, target_y: float) -> FollowPersonSafetyContext:
        """Verteidigung in der Tiefe -- Motion Guard blockiert einen
        Fahrbefehl ohnehin bei fehlender Freigabe, diese Pruefung stoppt
        FollowPerson zusaetzlich VORHER (gleiches Prinzip wie
        _safety_ok_for_approach(), um die Auftrag-Abschnitt-20-Bedingungen
        erweitert)."""
        safety = self._safety_state
        other_positions = [
            (t.position_3d.x, t.position_3d.y) for tid, (t, _) in self._tracks.items()
            if tid != track_id and t.has_3d_position
        ]
        crowd = is_crowd_ambiguous(
            target_x, target_y, other_positions,
            crowd_proximity_m=self.get_parameter("follow_person_crowd_proximity_m").value,
            allow_in_crowds=self.get_parameter("follow_person_allow_in_crowds").value,
        )
        in_keepout = point_in_any_keepout(self.zones, target_x, target_y)
        battery = self._latest_health.battery_percent if self._latest_health is not None else -1.0
        return FollowPersonSafetyContext(
            authorization_valid=authorization_valid,
            allow_motion=safety.allow_motion if safety is not None else False,
            allow_person_approach=safety.allow_person_approach if safety is not None else False,
            localization_valid=safety.localization_valid if safety is not None else False,
            obstacle_data_valid=safety.obstacle_data_valid if safety is not None else False,
            person_depth_valid=safety.person_depth_valid if safety is not None else False,
            charging_cable_connected=safety.charging_cable_connected if safety is not None else True,
            bumper_active=safety.bumper_active if safety is not None else True,
            emergency_stop=safety.emergency_stop if safety is not None else True,
            # BASE-Lease-Verlust WAEHREND der Fahrt wird bereits von
            # _drive_to_pose() selbst erkannt (periodische Erneuerung,
            # bricht bei Fehlschlag ab, siehe dort) -- dieses Feld deckt
            # nur den Vorab-Zustand ab, bevor ueberhaupt eine Lease
            # angefragt wurde.
            base_lease_valid=True,
            target_track_fresh=True,  # bereits durch _validate_target() vor dem Aufruf sichergestellt
            target_not_in_keepout=not in_keepout,
            crowd_ambiguous=crowd,
            battery_percent=battery,
            minimum_battery_percent=self.get_parameter("follow_person_minimum_battery_percent").value,
        )

    def _execute_follow(self, goal_handle):
        """Echte, autorisierte Nav2-Anbindung (Auftrag Abschnitt 19):
        1. AuthorizationGrant validieren, 2. SafetyState/weitere
        Bedingungen pruefen (wiederholt, nicht nur einmalig), 3.-7. Ziel-
        track validieren + Folgepose berechnen + fahren (ueber die
        bestehende _drive_to_pose(), die Lease-Erwerb/-Erneuerung/
        -Freigabe bereits pro Fahrsegment uebernimmt), 8. Ziel nur bei
        relevanter Personenbewegung aktualisieren (siehe monitor()
        unten), 9.-11. laufend ueberwachen/bei Abbruch Nav2 canceln
        (monitor_fn von _drive_to_pose() ruft cancel_goal_async() und
        wartet auf Bestaetigung, siehe dort).

        Bei Trackverlust wird NUR abgebrochen -- KEINE automatische
        Basisrotation, kein Kopf-Suchverhalten in diesem Commit (Auftrag
        Abschnitt 20: "hoechstens den Kopf vorsichtig suchen lassen" ist
        NICHT Teil dieser Implementierung, ehrlich offen dokumentiert)."""
        result = FollowPerson.Result()
        request = goal_handle.request
        track_id = request.track_id
        target_distance_m = (
            request.desired_follow_distance_m
            or self.get_parameter("follow_person_target_distance_m").value)

        def feedback(status, distance=0.0):
            fb = FollowPerson.Feedback()
            fb.status = status
            fb.current_distance_m = distance
            goal_handle.publish_feedback(fb)

        feedback("validating")

        # 1. AuthorizationGrant validieren -- OHNE gueltigen, passenden
        # Grant startet FollowPerson NIE (kein Umgehen der Rollen-/
        # Bestaetigungspruefung aus command_router_node.py).
        grant_ok, grant_reason = self._grant_cache.validate_and_consume(
            request.authorization_grant_id, track_id, "follow_speaker")
        if not grant_ok:
            feedback("safety_abort")
            result.success = False
            result.abort_reason = f"authorization_denied:{grant_reason}"
            goal_handle.abort()
            return result

        max_duration_s = (
            request.max_duration_s or self.get_parameter("follow_person_maximum_duration_s").value)
        loss_timeout_s = (
            request.max_track_loss_timeout_s
            or self.get_parameter("follow_person_loss_timeout_s").value)
        started_at_s = time.time()

        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                result.success = False
                result.abort_reason = "cancelled"
                goal_handle.canceled()
                return result

            if time.time() - started_at_s > max_duration_s:
                result.success = False
                result.abort_reason = "maximum_follow_duration_exceeded"
                goal_handle.abort()
                return result

            track, reason = self._validate_target(track_id, max_track_age_s=loss_timeout_s)
            if track is None:
                feedback(reason)
                result.success = False
                result.abort_reason = reason
                goal_handle.abort()
                return result

            ctx = self._build_follow_safety_context(
                track_id, authorization_valid=True,
                target_x=track.position_3d.x, target_y=track.position_3d.y)
            ok, reason = check_follow_person_safety(ctx)
            if not ok:
                feedback("safety_abort")
                result.success = False
                result.abort_reason = f"safety_abort:{reason}"
                goal_handle.abort()
                return result

            frame_id = track.frame_id or "map"
            robot_x, robot_y, tf_ok = self._get_robot_position_in_frame(frame_id, track.last_seen)
            if not tf_ok:
                result.success = False
                result.abort_reason = "keine_tf_fuer_roboterpose"
                goal_handle.abort()
                return result

            pose_result = compute_approach_pose(
                robot_x=robot_x, robot_y=robot_y,
                person_x=track.position_3d.x, person_y=track.position_3d.y,
                target_distance_m=target_distance_m,
                minimum_person_distance_m=self.get_parameter("follow_person_minimum_distance_m").value,
                maximum_approach_distance_m=self.get_parameter("follow_person_maximum_distance_m").value,
                zones=self.zones,
            )
            if not pose_result.valid:
                feedback("path_blocked")
                result.success = False
                result.abort_reason = pose_result.reason
                goal_handle.abort()
                return result

            if pose_result.already_within_distance:
                feedback("reached", 0.0)
                time.sleep(1.0 / self.get_parameter("follow_person_goal_update_rate_hz").value)
                continue

            from geometry_msgs.msg import PoseStamped
            pose = PoseStamped()
            pose.header.frame_id = frame_id
            pose.pose.position.x = pose_result.target_x
            pose.pose.position.y = pose_result.target_y
            qx, qy, qz, qw = _yaw_to_quaternion(pose_result.target_yaw_rad)
            pose.pose.orientation.x, pose.pose.orientation.y = qx, qy
            pose.pose.orientation.z, pose.pose.orientation.w = qz, qw
            feedback("moving", math.hypot(
                pose_result.target_x - robot_x, pose_result.target_y - robot_y))

            origin_person_x, origin_person_y = track.position_3d.x, track.position_3d.y
            origin_yaw_rad = pose_result.target_yaw_rad
            plan_robot_x, plan_robot_y = robot_x, robot_y

            def monitor():
                # 8./9.: nur bei relevanter Personenbewegung neu planen
                # (Positions- ODER Richtungsaenderung ueber der jeweiligen
                # Schwelle), sonst kontinuierlich Person/Sicherheit/
                # Autorisierung ueberwachen (Auftrag Abschnitt 19/20).
                fresh_track, reason = self._validate_target(track_id, max_track_age_s=loss_timeout_s)
                if fresh_track is None:
                    return False, reason
                ctx = self._build_follow_safety_context(
                    track_id, authorization_valid=True,
                    target_x=fresh_track.position_3d.x, target_y=fresh_track.position_3d.y)
                ok, reason = check_follow_person_safety(ctx)
                if not ok:
                    return False, f"safety_abort:{reason}"
                if should_replan(
                        origin_person_x, origin_person_y,
                        fresh_track.position_3d.x, fresh_track.position_3d.y,
                        self.get_parameter("follow_person_minimum_goal_shift_m").value):
                    return False, "replan_needed"
                yaw_now = math.atan2(
                    fresh_track.position_3d.y - plan_robot_y,
                    fresh_track.position_3d.x - plan_robot_x)
                yaw_delta = abs(_angle_diff_rad(yaw_now, origin_yaw_rad))
                if yaw_delta >= self.get_parameter("follow_person_minimum_goal_yaw_change_rad").value:
                    return False, "replan_needed"
                return True, ""

            drive_ok, drive_reason = self._drive_to_pose(goal_handle, pose, feedback, monitor_fn=monitor)
            if drive_ok:
                feedback("reached", 0.0)
                time.sleep(1.0 / self.get_parameter("follow_person_goal_update_rate_hz").value)
                continue
            if drive_reason == "monitor_abort:replan_needed":
                continue  # neue Pose berechnen und erneut fahren -- kein echter Abbruch
            result.success = False
            result.abort_reason = drive_reason
            goal_handle.abort()
            return result

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

        def monitor():
            """Entwicklungsauftrag 2, AP10: Ziel/Person WAEHREND der Fahrt
            ueberwachen, bei Track-Verlust oder Sicherheitsereignis SOFORT
            abbrechen -- nicht nur einmalig vor Fahrtbeginn pruefen."""
            fresh_track, reason = self._validate_target(goal_handle.request.track_id)
            if fresh_track is None:
                return False, reason
            ok, reason = self._safety_ok_for_approach()
            if not ok:
                return False, reason
            return True, ""

        return self._drive_to_pose(goal_handle, pose, feedback_cb, monitor_fn=monitor)

    # ---- Aktuator-Arbiter (Entwicklungsauftrag 04-B, AP5B, Abschnitt 14) ----

    @staticmethod
    def _goal_id_str(goal_handle) -> str:
        try:
            return str(bytes(goal_handle.goal_id.uuid))
        except Exception:
            return ""

    def _acquire_base_lease(self, purpose: str, goal_id: str, ttl_s: float = BASE_LEASE_TTL_S):
        """Gibt (granted, lease_id, reason) zurueck. Fail-closed: ein
        nicht erreichbarer/nicht antwortender Arbiter gewaehrt NIE
        stillschweigend eine Fahrfreigabe -- kein Nav2-Ziel wird gesendet,
        bevor diese Methode granted=True liefert."""
        if not self.acquire_lease_client.wait_for_service(timeout_sec=1.0):
            return False, "", "actuator_arbiter nicht erreichbar"
        req = AcquireActuatorLease.Request()
        req.owner_id = OWNER_ID
        req.resources = [BASE]
        req.purpose = purpose
        req.priority = PRIORITY_NAVIGATION
        req.ttl_s = ttl_s
        req.goal_id = goal_id
        future = self.acquire_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "", "actuator_arbiter Zeitueberschreitung"
        try:
            response = future.result()
        except Exception as e:
            return False, "", f"actuator_arbiter Fehler: {e}"
        return response.granted, response.lease_id, response.reason

    def _renew_base_lease(self, lease_id: str, ttl_s: float = BASE_LEASE_TTL_S) -> bool:
        if not lease_id:
            return False
        if not self.renew_lease_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(
                f"BASE-Lease '{lease_id}' konnte nicht erneuert werden (Arbiter nicht erreichbar).")
            return False
        req = RenewActuatorLease.Request()
        req.lease_id = lease_id
        req.ttl_s = ttl_s
        future = self.renew_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False
        try:
            return bool(future.result().success)
        except Exception:
            return False

    def _release_base_lease(self, lease_id: str):
        if not lease_id:
            return
        if not self.release_lease_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(
                f"BASE-Lease '{lease_id}' konnte nicht freigegeben werden (Arbiter nicht erreichbar).")
            return
        req = ReleaseActuatorLease.Request()
        req.lease_id = lease_id
        future = self.release_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)

    def _drive_to_pose(self, goal_handle, pose_stamped, feedback_cb, monitor_fn=None):
        """monitor_fn (optional): wird waehrend der Fahrt periodisch
        aufgerufen (Entwicklungsauftrag 2, AP10). Liefert monitor_fn()
        (False, grund) -> die laufende Nav2-Action wird aktiv abgebrochen
        (cancel_goal_async), NICHT nur auf ein Timeout gewartet. Nach
        einem Abbruch erfolgt KEINE automatische Wiederaufnahme -- der
        Aufrufer (BT ueber ApproachPerson.Result) muss neu entscheiden."""
        timeout = self.get_parameter("nav2_connect_timeout_s").value
        if not self._nav2_client.wait_for_server(timeout_sec=timeout):
            self.get_logger().error(
                "Nav2-ActionServer 'navigate_to_pose' nicht erreichbar -- "
                "Nav2 ist auf diesem System nicht installiert/gestartet."
            )
            return False, "nav2_nicht_erreichbar"

        # Entwicklungsauftrag 04-B, AP5B, Abschnitt 14: KEIN Nav2-Ziel
        # wird gesendet, bevor die BASE-Lease tatsaechlich gewaehrt wurde
        # -- Motion Guard blockiert einen Fahrbefehl ohnehin ohne gueltige
        # Lease, aber ein Nav2-Ziel ohne jede Aussicht auf Bewegungs-
        # freigabe erst gar nicht zu starten ist ehrlicher und vermeidet
        # unnoetige Nav2-interne Planungsarbeit.
        goal_id = self._goal_id_str(goal_handle)
        granted, lease_id, lease_reason = self._acquire_base_lease(
            purpose="navigate_to_pose", goal_id=goal_id)
        if not granted:
            self.get_logger().warn(
                f"Fahrt abgelehnt (Aktuator-Arbiter BASE-Lease): {lease_reason}")
            return False, f"actuator_arbiter_lease_denied:{lease_reason}"

        from nav2_msgs.action import NavigateToPose
        goal = NavigateToPose.Goal()
        goal.pose = pose_stamped

        send_future = self._nav2_client.send_goal_async(goal)
        # Bewusst blockierend via Executor-Callback -- gleiches Muster wie
        # presentation_manager_node._say_and_wait (MultiThreadedExecutor
        # + ReentrantCallbackGroup vorausgesetzt, siehe main()).
        import threading
        goal_response_done = threading.Event()
        result_done = threading.Event()
        outcome = {"success": False, "reason": "timeout"}
        goal_state = {"handle": None, "rejected": False}

        def on_result(fut):
            try:
                r = fut.result()
                outcome["success"] = (r.status == 4)  # STATUS_SUCCEEDED
                outcome["reason"] = "" if outcome["success"] else f"nav2_status_{r.status}"
            except Exception as e:
                outcome["reason"] = str(e)
            result_done.set()

        def on_goal_response(fut):
            gh = fut.result()
            goal_state["handle"] = gh
            if not gh.accepted:
                goal_state["rejected"] = True
                outcome["reason"] = "nav2_goal_rejected"
                result_done.set()
            else:
                rf = gh.get_result_async()
                rf.add_done_callback(on_result)
            goal_response_done.set()

        send_future.add_done_callback(on_goal_response)
        if not goal_response_done.wait(10.0):
            self._release_base_lease(lease_id)
            return False, "nav2_goal_response_timeout"
        if goal_state["rejected"] or goal_state["handle"] is None:
            self._release_base_lease(lease_id)
            return False, outcome["reason"] or "nav2_goal_rejected"

        gh = goal_state["handle"]
        deadline = time.time() + 60.0
        poll_interval_s = 0.5
        last_lease_renew_s = time.time()
        # AP10: nav2_moving=True nur waehrend der eigentlichen Fahrt --
        # gesture_catalog.py::play() sperrt Arm-/Kopfgesten darauf.
        self.nav2_moving_pub.publish(Bool(data=True))
        try:
            while time.time() < deadline:
                if result_done.wait(poll_interval_s):
                    return outcome["success"], outcome["reason"]
                if monitor_fn is not None:
                    ok, reason = monitor_fn()
                    if not ok:
                        self.get_logger().warn(
                            f"ApproachPerson waehrend der Fahrt abgebrochen: {reason}")
                        gh.cancel_goal_async()
                        return False, f"monitor_abort:{reason}"
                # Entwicklungsauftrag 04-B, AP5B, Abschnitt 14: Lease
                # waehrend laengerer Fahrten erneuern, statt sich auf eine
                # einzelne, sehr lange TTL zu verlassen.
                if time.time() - last_lease_renew_s >= BASE_LEASE_RENEW_INTERVAL_S:
                    if not self._renew_base_lease(lease_id):
                        self.get_logger().warn(
                            "BASE-Lease-Erneuerung fehlgeschlagen -- Fahrt wird "
                            "sicherheitshalber abgebrochen.")
                        gh.cancel_goal_async()
                        return False, "base_lease_renew_failed"
                    last_lease_renew_s = time.time()

            gh.cancel_goal_async()
            return False, "nav2_timeout"
        finally:
            self.nav2_moving_pub.publish(Bool(data=False))
            self._release_base_lease(lease_id)


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
