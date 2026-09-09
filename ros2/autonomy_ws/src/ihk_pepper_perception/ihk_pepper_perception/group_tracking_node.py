#!/usr/bin/env python3
"""
group_tracking_node: ROS-Wrapper um group_tracking.py (Entwicklungs-
auftrag 04-B, AP7, Abschnitt 14/15). Baut TrackCandidate-Listen aus
/perception_node/person_tracks, bindet GroupTracker an die aktuell
bestaetigte Interaktionsperson (/audio/focus_state::selected_track_id,
Auftrag: "mindestens ein Bezug zur aktuellen Interaktion") und
veroeffentlicht das Ergebnis auf /perception/conversation_groups.

EHRLICHER STAND: es existiert aktuell KEINE Karten-/Costmap-Anbindung
in diesem Node -- der Ursprung fuer Peilwinkel/Sichtbarkeitspruefung ist
IMMER der aktuelle base_link-Ursprung (0,0), nicht eine geplante
Beobachtungspose (die kommt in group_observation_pose.py, AP7 Commit 6).
"""
import time

import rclpy
from rclpy.node import Node

from ihk_pepper_interfaces.msg import AudioFocusState, ConversationGroup, ConversationGroupArray, PersonTrackArray

from .group_tracking import (
    GroupTracker,
    GroupTrackingConfig,
    TrackCandidate,
    compute_group_geometry,
)


class GroupTrackingNode(Node):
    def __init__(self):
        super().__init__("group_tracking")

        self.declare_parameter("minimum_members", 2)
        self.declare_parameter("maximum_members", 6)
        self.declare_parameter("maximum_member_spacing_m", 1.8)
        self.declare_parameter("maximum_track_age_s", 0.5)
        self.declare_parameter("minimum_stable_duration_s", 1.0)
        self.declare_parameter("join_hysteresis_s", 1.0)
        self.declare_parameter("leave_hysteresis_s", 2.0)
        self.declare_parameter("camera_horizontal_fov_deg", 87.0)
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("update_interval_s", 0.5)

        config = GroupTrackingConfig(
            minimum_members=self.get_parameter("minimum_members").value,
            maximum_members=self.get_parameter("maximum_members").value,
            maximum_member_spacing_m=self.get_parameter("maximum_member_spacing_m").value,
            maximum_track_age_s=self.get_parameter("maximum_track_age_s").value,
            minimum_stable_duration_s=self.get_parameter("minimum_stable_duration_s").value,
            join_hysteresis_s=self.get_parameter("join_hysteresis_s").value,
            leave_hysteresis_s=self.get_parameter("leave_hysteresis_s").value,
        )
        self.tracker = GroupTracker(config=config)

        self._latest_tracks: PersonTrackArray = None
        self._anchor_track_id = -1

        self.group_pub = self.create_publisher(
            ConversationGroupArray, "/perception/conversation_groups", 10)

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_tracks, 10)
        self.create_subscription(AudioFocusState, "/audio/focus_state", self._on_focus_state, 10)

        self.create_timer(self.get_parameter("update_interval_s").value, self._tick)

        self.get_logger().info("group_tracking gestartet.")

    def _on_tracks(self, msg: PersonTrackArray):
        self._latest_tracks = msg

    def _on_focus_state(self, msg: AudioFocusState):
        self._anchor_track_id = msg.selected_track_id if msg.valid else -1

    def _build_candidates(self, now_wall_s: float):
        base_frame = self.get_parameter("base_frame").value
        if self._latest_tracks is None:
            return []
        candidates = []
        for track in self._latest_tracks.tracks:
            if not track.has_3d_position or track.frame_id != base_frame:
                continue
            last_seen_s = track.last_seen.sec + track.last_seen.nanosec / 1e9
            age_s = max(0.0, now_wall_s - last_seen_s)
            candidates.append(TrackCandidate(
                track_id=int(track.track_id), x_m=track.position_3d.x, y_m=track.position_3d.y,
                stable=track.stable, age_s=age_s, has_3d_position=True,
            ))
        return candidates

    def _tick(self):
        if self._anchor_track_id < 0:
            # Keine aktuelle Interaktion -- keine Gruppe zu verfolgen
            # (Auftrag: Gruppe braucht einen Bezug zur Interaktion).
            self._publish([])
            return

        now_wall_s = self.get_clock().now().nanoseconds / 1e9
        candidates = self._build_candidates(now_wall_s)
        snapshot = self.tracker.update(candidates, self._anchor_track_id)

        if not snapshot.formed:
            self._publish([])
            return

        members = [c for c in candidates if c.track_id in snapshot.member_track_ids]
        geometry = compute_group_geometry(
            members, camera_horizontal_fov_deg=self.get_parameter("camera_horizontal_fov_deg").value)

        group = ConversationGroup()
        group.group_id = snapshot.group_id
        group.member_track_ids = list(snapshot.member_track_ids)
        group.active_speaker_track_id = (
            self._anchor_track_id if self._anchor_track_id in snapshot.member_track_ids else -1)
        if geometry is not None:
            group.center_position.x = geometry.center_x_m
            group.center_position.y = geometry.center_y_m
            group.minimum_member_distance_m = geometry.minimum_member_distance_m
            group.maximum_member_distance_m = geometry.maximum_member_distance_m
            group.angular_span_rad = geometry.angular_span_rad
            group.all_members_visible = geometry.all_members_within_fov
        group.stable = snapshot.stable
        group.confidence = 1.0 if snapshot.stable else 0.5
        self._publish([group])

    def _publish(self, groups):
        msg = ConversationGroupArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.groups = groups
        self.group_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = GroupTrackingNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
