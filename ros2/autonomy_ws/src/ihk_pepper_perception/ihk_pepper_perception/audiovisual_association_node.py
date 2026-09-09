#!/usr/bin/env python3
"""
audiovisual_association_node: ROS-Wrapper um audiovisual_association.py
(Entwicklungsauftrag 04-B, AP6, Abschnitt 13; AP6.1, Abschnitt 4/11).
Exponiert AssociatePersonWithSound als Service -- haelt selbst nur die
zuletzt empfangenen PersonTracks als Zustand.

Bestaetigter Fund (AP6.1, Abschnitt 3.5): das Zuordnungsergebnis lag
bislang NUR auf dem Behavior-Tree-Blackboard (Service-Antwort) --
audio_focus_node.py bekam es nie mit, selected_track_id blieb dort
IMMER -1. Dieser Node veroeffentlicht deshalb seit AP6.1 zusaetzlich
JEDES Zuordnungsergebnis (auch Ablehnungen, ohne track_id) auf
/audio/visual_target (AudioVisualTarget.msg) -- die einzige Quelle, aus
der audio_focus_node.py den ECHTEN bestaetigten Track uebernimmt.

Bestaetigter Fund (AP6.1, Abschnitt 11): has_3d_position=True allein
wurde bislang als ausreichend behandelt, um einen Track zu verwenden --
ohne zu pruefen, ob der Track TATSAECHLICH bereits im erwarteten
base_frame vorliegt und von der erwarteten Kamera stammt. Neue Parameter
base_frame/required_source_camera schliessen diese Luecke (Tracks in
einem anderen/unbekannten Frame oder von einer anderen Quelle werden
jetzt fail-closed verworfen, siehe audiovisual_association.py).

EHRLICHER STAND (unveraendert seit AP6): die Keepout-Zonen-Pruefung
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

from ihk_pepper_interfaces.msg import AudioVisualTarget, PersonTrackArray
from ihk_pepper_interfaces.srv import AssociatePersonWithSound

from .audiovisual_association import TrackCandidate, associate_person_to_sound


class AudiovisualAssociationNode(Node):
    def __init__(self):
        super().__init__("audiovisual_association")

        self.declare_parameter("maximum_track_age_s", 0.5)
        self.declare_parameter("minimum_track_confidence", 0.70)
        self.declare_parameter("maximum_angular_error_deg", 20.0)
        self.declare_parameter("minimum_ambiguity_margin_deg", 10.0)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 11: muss zum
        # base_frame-Parameter von perception_node.py passen -- ein Track
        # in einem anderen Frame wird fail-closed verworfen, NIE benutzt.
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("required_source_camera", "realsense")

        self._latest_tracks = None
        self._latest_tracks_received_at = None

        self.create_subscription(
            PersonTrackArray, "/perception_node/person_tracks", self._on_tracks, 10)
        self.create_service(
            AssociatePersonWithSound, "associate_person_with_sound", self._handle_associate)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4: EINZIGER Publisher
        # dieses Topics -- veroeffentlicht JEDEN Zuordnungsversuch, auch
        # Ablehnungen (siehe Moduldoku).
        self.visual_target_pub = self.create_publisher(
            AudioVisualTarget, "/audio/visual_target", 10)

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
                frame_id=track.frame_id,
                source_camera=track.source_camera,
                distance_m=track.distance_m,
            ))
        return candidates

    def _publish_visual_target(self, event_id, track_id, azimuth_rad, distance_m,
                                angular_error_deg, confidence, valid, reason):
        msg = AudioVisualTarget()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.event_id = event_id or ""
        msg.track_id = track_id
        msg.target_azimuth_rad_base = azimuth_rad
        msg.distance_m = distance_m
        msg.angular_error_deg = angular_error_deg
        msg.confidence = confidence
        msg.valid = valid
        msg.reason = reason
        self.visual_target_pub.publish(msg)

    def _handle_associate(self, request, response):
        event_id = getattr(request, "event_id", "")

        if self._latest_tracks_received_at is None:
            response.valid = False
            response.selected_track_id = -1
            response.reason = "keine_personentracks_empfangen"
            self._publish_visual_target(
                event_id, -1, 0.0, 0.0, 0.0, 0.0, False, response.reason)
            return response

        now_wall_s = self.get_clock().now().nanoseconds / 1e9
        measured_at_s = request.measured_at.sec + request.measured_at.nanosec / 1e9
        age_s = now_wall_s - measured_at_s
        if request.max_measurement_age_s > 0.0 and age_s > request.max_measurement_age_s:
            response.valid = False
            response.selected_track_id = -1
            response.reason = f"schallrichtung_zu_alt:{age_s:.2f}s"
            self._publish_visual_target(
                event_id, -1, 0.0, 0.0, 0.0, 0.0, False, response.reason)
            return response

        candidates = self._build_candidates(now_wall_s)
        result = associate_person_to_sound(
            candidates, request.sound_azimuth_rad,
            maximum_track_age_s=self.get_parameter("maximum_track_age_s").value,
            minimum_track_confidence=self.get_parameter("minimum_track_confidence").value,
            maximum_angular_error_deg=self.get_parameter("maximum_angular_error_deg").value,
            minimum_ambiguity_margin_deg=self.get_parameter("minimum_ambiguity_margin_deg").value,
            required_frame_id=self.get_parameter("base_frame").value,
            required_source_camera=self.get_parameter("required_source_camera").value,
        )
        response.valid = result.valid
        response.selected_track_id = result.selected_track_id
        response.reason = result.reason
        response.angular_error_deg = result.angular_error_deg
        response.ambiguity_margin_deg = result.ambiguity_margin_deg
        self._publish_visual_target(
            event_id, result.selected_track_id, result.target_azimuth_rad, result.distance_m,
            result.angular_error_deg, result.confidence, result.valid, result.reason,
        )
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
