#!/usr/bin/env python3
"""
audio_focus_node: duenner ROS-Wrapper um audio_focus.py
(Entwicklungsauftrag 04-B, AP6, Abschnitt 10). Treibt die
AudioFocusStateMachine ueber die Signale, die bereits auf Topics
verfuegbar sind, und veroeffentlicht den aktuellen Zustand periodisch
auf /audio/focus_state.

EHRLICHER STAND: siehe audio_focus.py-Moduldoku -- die BT-internen
Zwischenschritte (OrientToSound-Erfolg, FindPersonNearSoundRay-
Bestaetigung) sind noch nicht als eigene Topics sichtbar, daher bleibt
der Uebergang von WAKEWORD_DETECTED zu CONVERSATION_FOCUS in diesem
Node aktuell vereinfacht: sobald /interaction_state auf
CONVERSATION_READY wechselt, wird das als "Person bestaetigt"
interpretiert (ohne die konkrete track_id/Richtung aus
FindPersonNearSoundRay zu kennen -- selected_track_id bleibt in diesem
Fall -1, target_azimuth_rad der zuletzt bekannte Wakeword-Wert).
"""
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, UInt8

from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import AudioFocusState, WakewordEvent

from .audio_focus import AudioFocusStateMachine

FOCUS_PUBLISH_INTERVAL_S = 0.2


class AudioFocusNode(Node):
    def __init__(self):
        super().__init__("audio_focus")

        self.declare_parameter("target_loss_timeout_s", 2.0)

        self._machine = AudioFocusStateMachine(
            target_loss_timeout_s=self.get_parameter("target_loss_timeout_s").value)

        self.focus_pub = self.create_publisher(AudioFocusState, "/audio/focus_state", 10)
        self.create_subscription(WakewordEvent, "/audio/wakeword_event", self._on_wakeword_event, 10)
        self.create_subscription(Bool, "/pepper_bridge/speaking", self._on_speaking, 10)
        self.create_subscription(UInt8, "/interaction_state", self._on_interaction_state, 10)

        self.create_timer(FOCUS_PUBLISH_INTERVAL_S, self._tick_and_publish)

        self.get_logger().info("audio_focus gestartet.")

    def _on_wakeword_event(self, msg: WakewordEvent):
        if msg.direction_valid:
            self._machine.on_wakeword_detected(msg.azimuth_rad)
            self._machine.on_orientation_started()

    def _on_speaking(self, msg: Bool):
        self._machine.on_pepper_speaking_changed(msg.data)

    def _on_interaction_state(self, msg: UInt8):
        if msg.data == InteractionState.CONVERSATION_READY:
            # Siehe Moduldoku: vereinfachter Uebergang, solange die
            # BT-internen Zwischenschritte nicht als eigene Topics
            # sichtbar sind.
            if self._machine.mode.value in ("WAKEWORD_DETECTED", "ORIENTING_TO_SOUND"):
                self._machine.on_visual_confirmation_started()
                self._machine.on_person_confirmed(-1, self._machine.snapshot().target_azimuth_rad)
        elif msg.data == InteractionState.IDLE:
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
