#!/usr/bin/env python3
"""
Transformiert die vom ReSpeaker-Mikrofonarray gemessene Schallrichtung
(RAW, frame_id=respeaker_link, von audio_node.py auf
/audio/sound_direction_raw + /audio/wakeword_event_raw publiziert) in
Peppers Basis-Frame (KANONISCH, frame_id=base_frame) -- Entwicklungs-
auftrag 04-B, AP6.1, Abschnitt 3.1/4/12: bestaetigter Fund, der
Rohwinkel wurde bislang UNVERAENDERT als bereits-in-base_link-Winkel
weitergereicht (keine Transformation existierte).

EINZIGER Publisher der kanonischen Topics /audio/sound_direction und
/audio/wakeword_event -- audio_node.py publiziert seit diesem Commit
NUR noch die RAW-Varianten. Das Behavior Tree (WaitForFreshWakeword)
und audio_focus_node.py duerfen NUR die kanonischen Topics abonnieren,
NIE die RAW-Topics direkt.

Fail-closed (valid=False/direction_valid=False, NIE ein erfundener
Winkel) bei: leerem/unbekanntem Frame, fehlender/veralteter/
zukuenftiger TF, invalider Quaternion, nicht-endlichem Transformations-
ergebnis, zu altem Original-Messzeitpunkt (max_measurement_age_s) --
siehe sound_ray_transform.py fuer die eigentliche, ROS-arme Pruefkette.

Nutzt tf2_geometry_msgs.do_transform_vector3 -- eine reine ROTATIONS-
Transformation ohne Translation, weil eine Richtung KEINE Position ist
(do_transform_point waere hier falsch, siehe perception_node.py fuer
den Punkt-Fall bei echten Personenpositionen).

Voraussetzung: robot_state_publisher + respeaker_static_tf.launch.py
muessen die Kette base_frame -> ... -> respeaker_link tatsaechlich
publizieren (siehe pepper_robot_state.launch.py, AP6.1 Commit 2) --
ohne das bleibt jede Probe fail-closed ungueltig, kein stiller
Fallback auf eine erfundene Identitaets-Transformation.

NICHT live gegen echte Hardware getestet -- kein ReSpeaker Core v2.0
in dieser Session angeschlossen, siehe
docs/DEVELOPMENT_ORDER_04_B_REPORT.md, AP6.1-Abschnitt.

Entwicklungsauftrag 04-B, AP7, Abschnitt 9/12: transformiert seit
diesem Auftrag zusaetzlich die Schallrichtung von Codewort-Ereignissen
(/interaction/command_raw -> /interaction/command, gleiches Prinzip
wie WakewordEvent) -- audio_node.py erkennt Codewoerter wie "Eisenbahn"
auf JEDEM transkribierten Satz, dieser Node transformiert nur deren
Richtung, command_router_node.py trifft die Rollen-/
Autorisierungsentscheidung."""
import rclpy
import rclpy.duration
import tf2_ros
from rclpy.node import Node

from ihk_pepper_interfaces.msg import InteractionCommand, SoundDirection, WakewordEvent

from .sound_ray_transform import is_measurement_too_old, transform_direction


def _stamp_to_ns(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


class SoundDirectionTransformNode(Node):
    def __init__(self):
        super().__init__("sound_direction_transform_node")

        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("tf_timeout_s", 0.2)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.1: 0/negativ
        # deaktiviert die Altersgrenze NICHT heimlich -- siehe
        # sound_ray_transform.py::is_measurement_too_old-Docstring.
        # Sicherer Default deutlich ueber der Aeusserungsfenster-Marge
        # (audio_node.py::direction_window_margin_s), damit eine normale
        # Verarbeitungslatenz NICHT faelschlich als "zu alt" abgelehnt wird.
        self.declare_parameter("max_measurement_age_s", 2.0)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.sound_direction_pub = self.create_publisher(
            SoundDirection, "/audio/sound_direction", 10)
        self.wakeword_event_pub = self.create_publisher(
            WakewordEvent, "/audio/wakeword_event", 10)

        # Entwicklungsauftrag 04-B, AP7, Abschnitt 9/12: gleiches Prinzip
        # fuer Codewort-Ereignisse (command_router_node.py trifft darauf
        # die eigentliche Rollen-/Autorisierungsentscheidung, NICHT
        # dieser Node).
        self.interaction_command_pub = self.create_publisher(
            InteractionCommand, "/interaction/command", 10)

        self.create_subscription(
            SoundDirection, "/audio/sound_direction_raw", self._on_sound_direction_raw, 10)
        self.create_subscription(
            WakewordEvent, "/audio/wakeword_event_raw", self._on_wakeword_event_raw, 10)
        self.create_subscription(
            InteractionCommand, "/interaction/command_raw", self._on_interaction_command_raw, 10)

    def _tf_lookup_fn(self, target_frame, source_frame, stamp):
        timeout = rclpy.duration.Duration(
            seconds=self.get_parameter("tf_timeout_s").value)
        return self.tf_buffer.lookup_transform(target_frame, source_frame, stamp, timeout)

    def _too_old(self, stamp) -> bool:
        now_ns = self.get_clock().now().nanoseconds
        max_age_s = self.get_parameter("max_measurement_age_s").value
        return is_measurement_too_old(_stamp_to_ns(stamp), now_ns, max_age_s)

    def _on_sound_direction_raw(self, msg: SoundDirection):
        base_frame = self.get_parameter("base_frame").value
        out = SoundDirection()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = base_frame
        out.vad_active = msg.vad_active
        out.backend = msg.backend
        out.azimuth_rad = 0.0
        out.confidence = 0.0

        if not msg.valid:
            out.valid = False
            out.reason = msg.reason or "quelle_bereits_ungueltig"
            self.sound_direction_pub.publish(out)
            return

        if self._too_old(msg.header.stamp):
            out.valid = False
            out.reason = "messung_zu_alt"
            self.sound_direction_pub.publish(out)
            return

        result = transform_direction(
            azimuth_rad=msg.azimuth_rad,
            confidence=msg.confidence,
            source_frame=msg.header.frame_id,
            target_frame=base_frame,
            stamp=msg.header.stamp,
            tf_lookup_fn=self._tf_lookup_fn,
        )
        out.valid = result.valid
        out.azimuth_rad = result.azimuth_rad
        out.confidence = result.confidence
        out.reason = result.reason
        if not result.valid:
            self.get_logger().warn(
                f"Schallrichtung nicht transformierbar "
                f"({msg.header.frame_id!r}->{base_frame!r}): {result.reason}")
        self.sound_direction_pub.publish(out)

    def _on_wakeword_event_raw(self, msg: WakewordEvent):
        base_frame = self.get_parameter("base_frame").value
        out = WakewordEvent()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = base_frame
        out.event_id = msg.event_id
        out.keyword = msg.keyword
        out.keyword_confidence = msg.keyword_confidence
        out.azimuth_rad = 0.0
        out.direction_confidence = 0.0

        if not msg.direction_valid:
            out.direction_valid = False
            self.wakeword_event_pub.publish(out)
            return

        if self._too_old(msg.header.stamp):
            out.direction_valid = False
            self.get_logger().warn(
                f"WakewordEvent {msg.event_id}: Original-Messzeitpunkt zu alt, "
                f"Richtung wird NICHT transformiert.")
            self.wakeword_event_pub.publish(out)
            return

        result = transform_direction(
            azimuth_rad=msg.azimuth_rad,
            confidence=msg.direction_confidence,
            source_frame=msg.header.frame_id,
            target_frame=base_frame,
            stamp=msg.header.stamp,
            tf_lookup_fn=self._tf_lookup_fn,
        )
        out.direction_valid = result.valid
        out.azimuth_rad = result.azimuth_rad
        out.direction_confidence = result.confidence
        if not result.valid:
            self.get_logger().warn(
                f"WakewordEvent {msg.event_id}: Richtung nicht transformierbar "
                f"({msg.header.frame_id!r}->{base_frame!r}): {result.reason}")
        self.wakeword_event_pub.publish(out)


    def _on_interaction_command_raw(self, msg: InteractionCommand):
        """Transformiert NUR die Schallrichtung (direction_azimuth_rad_base/
        direction_valid) -- alle anderen Felder (event_id/command/
        raw_transcript/...) werden unveraendert durchgereicht.
        authorization_status/priority bleiben bewusst UNVERAENDERT
        (Platzhalter "pending"/0 aus audio_node.py) -- die eigentliche
        Entscheidung trifft command_router_node.py, nicht dieser Node."""
        base_frame = self.get_parameter("base_frame").value
        out = InteractionCommand()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = base_frame
        out.event_id = msg.event_id
        out.command = msg.command
        out.raw_transcript = msg.raw_transcript
        out.track_id = msg.track_id
        out.person_id = msg.person_id
        out.role = msg.role
        out.confidence = msg.confidence
        out.authorization_status = msg.authorization_status
        out.priority = msg.priority
        out.direction_azimuth_rad_base = 0.0
        out.direction_valid = False

        if not msg.direction_valid:
            out.reason = msg.reason or "quelle_bereits_ungueltig"
            self.interaction_command_pub.publish(out)
            return

        if self._too_old(msg.header.stamp):
            out.reason = "messung_zu_alt"
            self.interaction_command_pub.publish(out)
            return

        result = transform_direction(
            azimuth_rad=msg.direction_azimuth_rad_base,
            confidence=msg.confidence,
            source_frame=msg.header.frame_id,
            target_frame=base_frame,
            stamp=msg.header.stamp,
            tf_lookup_fn=self._tf_lookup_fn,
        )
        out.direction_valid = result.valid
        out.direction_azimuth_rad_base = result.azimuth_rad
        out.reason = result.reason
        if not result.valid:
            self.get_logger().warn(
                f"InteractionCommand {msg.event_id}: Richtung nicht transformierbar "
                f"({msg.header.frame_id!r}->{base_frame!r}): {result.reason}")
        self.interaction_command_pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = SoundDirectionTransformNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
