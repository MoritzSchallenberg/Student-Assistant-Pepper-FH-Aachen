#!/usr/bin/env python3
"""
audiovisual_association_node: ROS-Wrapper um audiovisual_association.py
(Entwicklungsauftrag 04-B, AP6, Abschnitt 13). Exponiert
AssociatePersonWithSound als Service -- haelt selbst nur die zuletzt
empfangenen PersonTracks als Zustand.

EHRLICHER STAND: die Keepout-Zonen-Pruefung
(TrackCandidate.in_keepout_zone) ist im reinen Funktionsvertrag
vorbereitet, hier aber NICHT verdrahtet -- das braeuchte eine
map-Frame-Transformation der Tracks (Keepout-Zonen sind in `map`
definiert, PersonTrack.position_3d liegt je nach source_camera in einem
anderen Frame), die dieser Node noch nicht durchfuehrt. Alle Tracks
gelten daher aktuell als NICHT in einer Keepout-Zone -- eine
dokumentierte Vereinfachung, kein verschwiegener Bug (siehe
docs/AUDIO_VISUAL_PERSON_ASSOCIATION.md).
"""
import time

import rclpy
from rclpy.node import Node

from ihk_pepper_interfaces.msg import PersonTrackArray
from ihk_pepper_interfaces.srv import AssociatePersonWithSound

from .audiovisual_association import TrackCandidate, associate_person_to_sound


class AudiovisualAssociationNode(Node):
    def __init__(self):
        super().__init__("audiovisual_association")

        self.declare_parameter("maximum_track_age_s", 0.5)
        self.declare_parameter("minimum_track_confidence", 0.70)
        self.declare_parameter("maximum_angular_error_deg", 20.0)
        self.declare_parameter("minimum_ambiguity_margin_deg", 10.0)

        self._latest_tracks = None
        self._latest_tracks_received_at = None

        self.create_subscription(
            PersonTrackArray, "/perception_node/person_tracks", self._on_tracks, 10)
        self.create_service(
            AssociatePersonWithSound, "associate_person_with_sound", self._handle_associate)

        self.get_logger().info("audiovisual_association gestartet.")

    def _on_tracks(self, msg: PersonTrackArray):
        self._latest_tracks = msg
        self._latest_tracks_received_at = time.monotonic()

    def _build_candidates(self, now_wall_s: float):
        if self._latest_tracks is None:
            return []
        candidates = []
        for track in self._latest_tracks.tracks:
            last_seen_s = track.last_seen.sec + track.last_seen.nanosec / 1e9
            age_s = max(0.0, now_wall_s - last_seen_s)
            candidates.append(TrackCandidate(
                track_id=int(track.track_id),
                confidence=track.confidence,
                has_3d_position=track.has_3d_position,
                position_x_m=track.position_3d.x,
                position_y_m=track.position_3d.y,
                stable=track.stable,
                age_s=age_s,
                in_keepout_zone=False,  # siehe Moduldoku -- nicht verdrahtet
            ))
        return candidates

    def _handle_associate(self, request, response):
        if self._latest_tracks_received_at is None:
            response.valid = False
            response.selected_track_id = -1
            response.reason = "keine_personentracks_empfangen"
            return response

        now_wall_s = self.get_clock().now().nanoseconds / 1e9
        measured_at_s = request.measured_at.sec + request.measured_at.nanosec / 1e9
        age_s = now_wall_s - measured_at_s
        if request.max_measurement_age_s > 0.0 and age_s > request.max_measurement_age_s:
            response.valid = False
            response.selected_track_id = -1
            response.reason = f"schallrichtung_zu_alt:{age_s:.2f}s"
            return response

        candidates = self._build_candidates(now_wall_s)
        result = associate_person_to_sound(
            candidates, request.sound_azimuth_rad,
            maximum_track_age_s=self.get_parameter("maximum_track_age_s").value,
            minimum_track_confidence=self.get_parameter("minimum_track_confidence").value,
            maximum_angular_error_deg=self.get_parameter("maximum_angular_error_deg").value,
            minimum_ambiguity_margin_deg=self.get_parameter("minimum_ambiguity_margin_deg").value,
        )
        response.valid = result.valid
        response.selected_track_id = result.selected_track_id
        response.reason = result.reason
        response.angular_error_deg = result.angular_error_deg
        response.ambiguity_margin_deg = result.ambiguity_margin_deg
        return response


def main(args=None):
    rclpy.init(args=args)
    node = AudiovisualAssociationNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
