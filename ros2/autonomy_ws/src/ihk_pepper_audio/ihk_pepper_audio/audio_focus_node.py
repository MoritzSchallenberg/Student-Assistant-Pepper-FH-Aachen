#!/usr/bin/env python3
"""
audio_focus_node: duenner ROS-Wrapper um audio_focus.py
(Entwicklungsauftrag 04-B, AP6, Abschnitt 10; AP6.1, Abschnitt 5).
Treibt die AudioFocusStateMachine ueber die Signale, die auf Topics
verfuegbar sind, und veroeffentlicht den aktuellen Zustand periodisch
auf /audio/focus_state.

Bestaetigter Fund (AP6.1, Abschnitt 3.5/3.6, behoben in diesem Commit):
bislang wurde der Uebergang von ORIENTING_TO_SOUND zu CONVERSATION_FOCUS
NUR ueber /interaction_state==CONVERSATION_READY vereinfacht ausgeloest
(on_person_confirmed(-1, ...) -- IMMER Sentinel -1, NIE der echte
bestaetigte Track). Dieser Node abonniert jetzt stattdessen das ECHTE
Ergebnis von audiovisual_association_node.py (/audio/visual_target,
AudioVisualTarget.msg) UND waehrend eines bestaetigten Fokus die
laufenden RealSense-Personentracks (/perception_node/person_tracks) --
NUR Updates fuer denselben bestaetigten track_id werden uebernommen
(audio_focus.py::on_target_track_update() weist jeden anderen Track
bereits strukturell ab, siehe dort). Ein lauterer/anderer Sprecher kann
dadurch NIE selbst zum neuen Fokus werden.

Die Personenposition liegt in PersonTrack.position_3d/AudioVisualTarget
im base_frame vor -- fuer das Beamforming-Steering wird sie hier auf
das Mikrofonarray-Frame (respeaker_link) transformiert (ECHTE
Punkt-Transformation mit Translation UND Rotation, siehe
transform_person_position_to_azimuth() unten -- im Unterschied zu
sound_ray_transform.py's reiner Vektor-Transformation fuer
Schallrichtungen, weil eine Personenposition eine echte Position ist,
keine reine Richtung). Fehlende/veraltete TF fuehrt IMMER zu einer
verworfenen Aktualisierung (kein erfundener Winkel), NIE zu einem
Absturz.

/audio/focus_state's target_azimuth_rad ist seit diesem Commit
IMMER im respeaker_link-Frame (vorher: zuletzt bekannter Wakeword-Wert,
noch im base_frame) -- audio_node.py::_on_focus_state() gibt diesen Wert
direkt an das aktive SteerableDirectionalAudioBackend weiter.

Entwicklungsauftrag 04-B, AP7, Abschnitt 17: innerhalb einer bestaetigten,
stabilen Gesprächsgruppe (/perception/conversation_groups) steuert
_on_person_tracks() nicht mehr zwingend auf die urspruenglich bestaetigte
Person -- GROUP_WIDE (kleine Winkelspanne) zielt auf das Gruppenzentrum,
ACTIVE_SPEAKER (grosse Winkelspanne) waehlt per ActiveSpeakerSelector
(group_speaker_selection.py) unter den bestaetigten Gruppenmitgliedern.
Die SITZUNGSIDENTITAET (selected_track_id, an audio_focus.py uebergeben)
bleibt dabei IMMER die urspruenglich bestaetigte Person -- nur der
WINKEL darf innerhalb der Gruppe wandern, nie die Identitaet selbst.
Der Kopf bewegt sich dabei NIE (Kopforientierung ist ausschliesslich an
Wakeword-Ereignisse gebunden, siehe orient_to_sound_node.py -- ein
Sprecherwechsel innerhalb der Gruppe beeinflusst nur das elektronische
Beamforming-Ziel)."""
import math

import rclpy
import rclpy.duration
import tf2_geometry_msgs  # noqa: F401 -- registriert do_transform_point fuer PointStamped
import tf2_ros
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from std_msgs.msg import Bool, UInt8

from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import (
    AudioFocusState,
    AudioVisualTarget,
    ConversationGroupArray,
    PersonTrackArray,
    SoundDirection,
    WakewordEvent,
)

from .audio_focus import AudioFocusMode, AudioFocusStateMachine
from .group_speaker_selection import ActiveSpeakerSelector, GroupMemberBearing

FOCUS_PUBLISH_INTERVAL_S = 0.2


def transform_person_position_to_azimuth(x_m, y_m, z_m, source_frame, target_frame, stamp, tf_lookup_fn):
    """Reine Punkt-Transformation (Translation UND Rotation) -- gibt
    None bei leerem Frame/fehlender-veralteter TF/nicht-endlichem
    Ergebnis zurueck (fail-closed, NIE ein erfundener Winkel). tf_lookup_fn
    hat dieselbe Signatur wie sound_ray_transform.py::transform_direction
    (tf_lookup_fn(target_frame, source_frame, stamp) -> TransformStamped),
    injizierbar fuer Tests ohne echten TF-Baum."""
    if not source_frame or not target_frame:
        return None
    try:
        transform = tf_lookup_fn(target_frame, source_frame, stamp)
    except Exception:
        return None
    if transform is None:
        return None
    ps = PointStamped()
    ps.header.frame_id = source_frame
    ps.header.stamp = stamp
    ps.point.x, ps.point.y, ps.point.z = float(x_m), float(y_m), float(z_m)
    try:
        transformed = tf2_geometry_msgs.do_transform_point(ps, transform)
    except Exception:
        return None
    x, y = transformed.point.x, transformed.point.y
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return math.atan2(y, x)


class AudioFocusNode(Node):
    def __init__(self):
        super().__init__("audio_focus")

        self.declare_parameter("target_loss_timeout_s", 2.0)
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("respeaker_frame_id", "respeaker_link")
        self.declare_parameter("tf_timeout_s", 0.2)
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 17: GROUP_WIDE, solange
        # die Gruppen-Winkelspanne darunter bleibt, sonst ACTIVE_SPEAKER.
        self.declare_parameter("group_wide_mode_max_span_rad", math.radians(40.0))
        self.declare_parameter("active_speaker_maximum_angular_error_deg", 20.0)
        self.declare_parameter("active_speaker_minimum_ambiguity_margin_deg", 10.0)
        self.declare_parameter("active_speaker_required_confirming_frames", 3)

        self._machine = AudioFocusStateMachine(
            target_loss_timeout_s=self.get_parameter("target_loss_timeout_s").value)
        self._active_speaker_selector = ActiveSpeakerSelector(
            maximum_angular_error_rad=math.radians(
                self.get_parameter("active_speaker_maximum_angular_error_deg").value),
            minimum_ambiguity_margin_rad=math.radians(
                self.get_parameter("active_speaker_minimum_ambiguity_margin_deg").value),
            required_confirming_frames=self.get_parameter(
                "active_speaker_required_confirming_frames").value,
        )
        self._latest_groups: ConversationGroupArray = None
        self._latest_doa: SoundDirection = None

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.focus_pub = self.create_publisher(AudioFocusState, "/audio/focus_state", 10)
        self.create_subscription(WakewordEvent, "/audio/wakeword_event", self._on_wakeword_event, 10)
        self.create_subscription(Bool, "/pepper_bridge/speaking", self._on_speaking, 10)
        self.create_subscription(UInt8, "/interaction_state", self._on_interaction_state, 10)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4/5: das ECHTE
        # Zuordnungsergebnis -- ersetzt den bisherigen, vereinfachten
        # Uebergang ueber /interaction_state==CONVERSATION_READY.
        self.create_subscription(
            AudioVisualTarget, "/audio/visual_target", self._on_visual_target, 10)
        # Nur waehrend eines bestaetigten Fokus relevant (siehe
        # _on_person_tracks) -- selected_track_id==-1 verwirft jedes Update.
        self.create_subscription(
            PersonTrackArray, "/perception_node/person_tracks", self._on_person_tracks, 10)
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 17: fuer
        # ACTIVE_SPEAKER-Vergleich (kanonisch, bereits nach base_link
        # transformiert, siehe sound_direction_transform_node.py).
        self.create_subscription(SoundDirection, "/audio/sound_direction", self._on_sound_direction, 10)
        self.create_subscription(
            ConversationGroupArray, "/perception/conversation_groups", self._on_groups, 10)

        self.create_timer(FOCUS_PUBLISH_INTERVAL_S, self._tick_and_publish)

        self.get_logger().info("audio_focus gestartet.")

    def _tf_lookup_fn(self, target_frame, source_frame, stamp):
        timeout = rclpy.duration.Duration(seconds=self.get_parameter("tf_timeout_s").value)
        return self.tf_buffer.lookup_transform(target_frame, source_frame, stamp, timeout)

    def _on_wakeword_event(self, msg: WakewordEvent):
        if msg.direction_valid:
            self._machine.on_wakeword_detected(msg.azimuth_rad)
            self._machine.on_orientation_started()

    def _on_speaking(self, msg: Bool):
        self._machine.on_pepper_speaking_changed(msg.data)

    def _on_visual_target(self, msg: AudioVisualTarget):
        """Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4/5: EINZIGE Quelle
        fuer den Uebergang VISUAL_CONFIRMATION -> CONVERSATION_FOCUS.
        on_visual_confirmation_started()/on_person_confirmed()/
        on_person_not_confirmed() sind bereits strukturell No-Ops
        ausserhalb des passenden Zustands (siehe audio_focus.py), ein
        verspaetetes/doppeltes AudioVisualTarget kann also nichts
        kaputt machen. Zusaetzliche Absicherung: ein AudioVisualTarget
        ausserhalb des erwarteten Ablauffensters (z.B. weit nach einem
        laengst beendeten Gespraech) wird ignoriert, statt eine neue
        Bestaetigung ausserhalb des vorgesehenen Ablaufs auszuloesen."""
        if self._machine.mode not in (AudioFocusMode.ORIENTING_TO_SOUND, AudioFocusMode.VISUAL_CONFIRMATION):
            return
        self._machine.on_visual_confirmation_started()
        if not msg.valid:
            self._machine.on_person_not_confirmed(msg.reason)
            return
        base_frame = self.get_parameter("base_frame").value
        respeaker_frame = self.get_parameter("respeaker_frame_id").value
        x_base = msg.distance_m * math.cos(msg.target_azimuth_rad_base)
        y_base = msg.distance_m * math.sin(msg.target_azimuth_rad_base)
        azimuth_respeaker = transform_person_position_to_azimuth(
            x_base, y_base, 0.0, base_frame, respeaker_frame, msg.header.stamp, self._tf_lookup_fn)
        if azimuth_respeaker is None:
            self.get_logger().warn(
                f"Keine TF {base_frame}->{respeaker_frame} fuer bestaetigte Person "
                f"(track_id={msg.track_id}) -- Fokus NICHT gesetzt."
            )
            self._machine.on_person_not_confirmed("keine_tf_fuer_respeaker_frame")
            return
        self._machine.on_person_confirmed(msg.track_id, azimuth_respeaker)

    def _on_sound_direction(self, msg: SoundDirection):
        self._latest_doa = msg

    def _on_groups(self, msg: ConversationGroupArray):
        self._latest_groups = msg

    def _stable_group_for(self, track_id: int):
        """None, wenn keine BESTAETIGTE (stable=True), aktuell verfolgte
        Gruppe track_id enthaelt -- eine gerade erst entstehende Gruppe
        loest noch keinen Moduswechsel aus (Auftrag Abschnitt 14: "ueber
        mehrere Frames stabil")."""
        if self._latest_groups is None:
            return None
        for group in self._latest_groups.groups:
            if group.stable and track_id in group.member_track_ids:
                return group
        return None

    def _on_person_tracks(self, msg: PersonTrackArray):
        """Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5 + AP7, Abschnitt
        17: haelt das Fokus-Ziel waehrend des Gespraechs aktuell -- NUR
        fuer denselben bestaetigten Track wird
        audio_focus.py::on_target_track_update() aufgerufen (verwirft
        jeden anderen track_id bereits selbst) -- ABER der dabei
        uebergebene WINKEL darf innerhalb einer bestaetigten Gruppe auf
        ein ANDERES Mitglied zeigen (GROUP_WIDE: Gruppenzentrum,
        ACTIVE_SPEAKER: bestaetigter aktiver Sprecher) -- die
        Sitzungsidentitaet (selected_track_id) bleibt dabei IMMER die
        urspruenglich bestaetigte Person, NIE ein Fremdtrack."""
        selected_id = self._machine.snapshot().selected_track_id
        if selected_id == -1:
            return
        base_frame = self.get_parameter("base_frame").value
        respeaker_frame = self.get_parameter("respeaker_frame_id").value

        tracks_by_id = {int(t.track_id): t for t in msg.tracks
                        if t.has_3d_position and t.frame_id == base_frame}
        if selected_id not in tracks_by_id:
            return
        selected_track = tracks_by_id[selected_id]

        group = self._stable_group_for(selected_id)
        target_x, target_y, target_stamp = (
            selected_track.position_3d.x, selected_track.position_3d.y, selected_track.last_seen)

        if group is not None:
            max_span = self.get_parameter("group_wide_mode_max_span_rad").value
            if group.angular_span_rad <= max_span:
                # GROUP_WIDE: Kopf/Beamforming bleibt auf das Gruppenzentrum
                # ausgerichtet -- kein staendiges Umschalten pro Sprecher.
                target_x, target_y = group.center_position.x, group.center_position.y
            else:
                # ACTIVE_SPEAKER: nur unter bestaetigten Gruppenmitgliedern
                # vergleichen -- eine fremde Richtung ausserhalb der
                # Gruppe kann strukturell nie gewinnen.
                members = [
                    GroupMemberBearing(track_id=tid, bearing_rad=math.atan2(t.position_3d.y, t.position_3d.x))
                    for tid, t in tracks_by_id.items() if tid in group.member_track_ids
                ]
                doa = self._latest_doa
                result = self._active_speaker_selector.observe(
                    vad_active=bool(doa.vad_active) if doa is not None else False,
                    doa_azimuth_rad=doa.azimuth_rad if doa is not None else 0.0,
                    doa_valid=bool(doa.valid) if doa is not None else False,
                    members=members,
                )
                speaker_id = result.selected_track_id
                if speaker_id in tracks_by_id:
                    speaker_track = tracks_by_id[speaker_id]
                    target_x, target_y = speaker_track.position_3d.x, speaker_track.position_3d.y
                    target_stamp = speaker_track.last_seen
                # Kein bestaetigter Sprecher (-1) oder dessen Track gerade
                # nicht sichtbar: sicherer Rueckfall auf die urspruenglich
                # bestaetigte Person -- NIE stillschweigend auf den
                # lautesten Kandidaten wechseln.

        azimuth_respeaker = transform_person_position_to_azimuth(
            target_x, target_y, 0.0, base_frame, respeaker_frame, target_stamp, self._tf_lookup_fn)
        if azimuth_respeaker is not None:
            self._machine.on_target_track_update(selected_id, azimuth_respeaker)

    def _on_interaction_state(self, msg: UInt8):
        if msg.data == InteractionState.IDLE:
            self._machine.on_conversation_ended()

    def _tick_and_publish(self):
        self._machine.tick()
        snapshot = self._machine.snapshot()
        msg = AudioFocusState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.mode = snapshot.mode.value
        msg.selected_track_id = snapshot.selected_track_id
        msg.target_azimuth_rad = snapshot.target_azimuth_rad
        msg.valid = snapshot.valid
        msg.backend = ""
        msg.reason = snapshot.reason
        self.focus_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = AudioFocusNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
