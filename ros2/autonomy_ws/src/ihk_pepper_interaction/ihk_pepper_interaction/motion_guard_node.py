#!/usr/bin/env python3
"""
motion_guard_node: letzte, hardwarenahe Sicherheitsinstanz vor /cmd_vel
(Entwicklungsauftrag 2, Abschnitt 11 "AP8"; Aktualitaetspruefung fuer
JEDEN Eingang einzeln + Latch-Fehler behoben in Entwicklungsauftrag
04-B, AP2/AP3). Duenner ROS-Wrapper um motion_guard.py, gleiches Muster
wie supervisor_node.py.

Sitzt als letztes Glied in der Fahrbefehlskette:
    Nav2 -> Velocity Smoother -> Collision Monitor -> Motion Guard -> /cmd_vel
Liest den Kandidaten-Twist von `cmd_vel_in` (Parameter, Standard
"motion_guard/cmd_vel_in" -- wird in Auftrag 2 AP7 auf den tatsaechlichen
Collision-Monitor-Ausgang remapped) und leitet ihn NUR auf /cmd_vel
weiter, wenn evaluate_motion_guard() erlaubt=True liefert. Sonst wird
mit konfigurierbarer Rate eine Nullgeschwindigkeit publiziert (Auftrag:
"unmittelbar Nullgeschwindigkeit ausgeben, weitere Bewegungsbefehle
verwerfen") -- kein einmaliges Stop-Signal, sondern ein fortlaufendes,
solange der Zustand ungueltig bleibt.

`enable_live_motion` (Parameter, Standard false) ist der "expliziter
Livebewegungsmodus" aus dem Auftrag -- nur navigation_live/
navigation_dry_run setzen ihn auf true. In offline_test/realsense_test
bleibt er false, Motion Guard laesst dann NIE etwas durch, unabhaengig
von allen anderen Bedingungen.

Entwicklungsauftrag 04-B, AP2/AP3, zwei konkrete Funde behoben:
1. gesture_in_progress abonnierte bisher "/gesture_in_progress" (kein
   Namespace) -- bridge_node.py veroeffentlicht aber innerhalb des
   Namespace "pepper_bridge", also tatsaechlich unter
   "/pepper_bridge/gesture_in_progress". Die beiden Themen trafen sich
   NIE. Behoben durch die gemeinsame safety_topics.py-Konstante statt
   eines lokal nachgetippten String-Literals.
2. `self._obstacle_data_valid = self._obstacle_data_valid or
   msg.obstacle_data_valid` in _on_safety_state() liess ein einmal
   empfangenes True dauerhaft gelatcht bleiben, selbst wenn spaeter ueber
   SafetyState oder das dedizierte Thema False empfangen wurde (ein
   `or` kann einen bereits wahren Wert nie wieder falsch machen).
   Entfernt: SafetyState beeinflusst obstacle_data_valid jetzt gar nicht
   mehr -- einzige Quelle ist das dedizierte /obstacle_data_valid-Thema,
   dessen FreshBool.update() immer ueberschreibt (=), nie nur verodert.

JEDER hier verwendete Bool-Eingang traegt jetzt einen eigenen
Ankunftszeitstempel (FreshBool, siehe safety_topics.py) -- eine fehlende
ODER veraltete Nachricht faellt individuell auf den sicheren
(blockierenden) Wert zurueck, statt sich auf ein einziges, nur fuer
Kommando-Alter gedachtes data_age_s zu verlassen.

Entwicklungsauftrag 04-B, AP5B: konsultiert zusaetzlich
"/actuator_arbiter/base_lease_valid" (vom neuen zentralen
Aktuator-Arbiter veroeffentlicht, siehe actuator_arbiter_node.py) --
Navigation/person_approach_node.py muss eine BASE-Lease HALTEN, bevor
Motion Guard ueberhaupt einen von Null verschiedenen Fahrbefehl
durchlaesst. Fehlt/veraltet die Lease, wird wie bei jedem anderen
Blockierungsgrund hier explizit Nullgeschwindigkeit publiziert (kein
Verwerfen ohne Ersatzsignal) -- ein Stopp-Befehl kommt also immer durch.
"""
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool, String

from ihk_pepper_interfaces.msg import SafetyState

from .motion_guard import MotionGuardInputs, evaluate_motion_guard
from . import safety_topics
from .safety_topics import FreshBool


class MotionGuardNode(Node):
    def __init__(self):
        super().__init__("motion_guard")

        self.declare_parameter("cmd_vel_in_topic", "motion_guard/cmd_vel_in")
        self.declare_parameter("cmd_vel_out_topic", "/cmd_vel")
        self.declare_parameter("enable_live_motion", False)
        self.declare_parameter("max_cmd_age_s", 0.5)
        self.declare_parameter("max_input_age_s", 2.0)
        self.declare_parameter("publish_rate_hz", 10.0)

        self._last_cmd = None
        self._last_cmd_wall_s = None

        # Fail-closed-Ausweichwert je Eingang direkt am FreshBool
        # dokumentiert (True = "im Zweifel blockieren" fuer Gefahren-/
        # gerade-noch-nicht-bestaetigte Signale, False = "im Zweifel
        # NICHT gueltig" fuer *_valid-Flags).
        self._safety_allow_motion = FreshBool(False)
        self._emergency_stop = FreshBool(True)
        self._realsense_diagnostics_valid = FreshBool(False)
        self._odometry_valid = FreshBool(False)
        self._localization_valid = FreshBool(False)
        self._obstacle_data_valid = FreshBool(False)
        self._head_navigation_pose_valid = FreshBool(False)
        self._bumper_active = FreshBool(True)
        self._gesture_in_progress = FreshBool(True)
        # Entwicklungsauftrag 04-B, AP5B: fail-closed wie jeder andere
        # *_valid-Eingang hier -- ohne (frische) Bestaetigung des
        # Aktuator-Arbiters gilt die BASE-Lease als NICHT gehalten.
        self._base_lease_valid = FreshBool(False)

        self.cmd_pub = self.create_publisher(Twist, self.get_parameter("cmd_vel_out_topic").value, 10)
        self.diagnostics_pub = self.create_publisher(String, "motion_guard/diagnostics", 10)

        self.create_subscription(
            Twist, self.get_parameter("cmd_vel_in_topic").value, self._on_cmd_vel_in, 10)
        self.create_subscription(
            SafetyState, safety_topics.SAFETY_STATE_TOPIC, self._on_safety_state, 10)
        self.create_subscription(Bool, safety_topics.BUMPER_TOPIC, self._on_bumper, 10)
        self.create_subscription(
            Bool, "realsense_diagnostics_valid", self._on_realsense_diagnostics_valid, 10)
        self.create_subscription(Bool, "odometry_valid", self._on_odometry_valid, 10)
        self.create_subscription(
            Bool, safety_topics.LOCALIZATION_VALID_TOPIC, self._on_localization_valid, 10)
        self.create_subscription(
            Bool, safety_topics.OBSTACLE_DATA_VALID_TOPIC, self._on_obstacle_data_valid, 10)
        self.create_subscription(
            Bool, "head_navigation_pose_valid", self._on_head_navigation_pose_valid, 10)
        self.create_subscription(
            Bool, safety_topics.GESTURE_IN_PROGRESS_TOPIC, self._on_gesture_in_progress, 10)
        self.create_subscription(
            Bool, safety_topics.BASE_LEASE_VALID_TOPIC, self._on_base_lease_valid, 10)

        rate = self.get_parameter("publish_rate_hz").value
        self.create_timer(1.0 / rate if rate > 0 else 0.1, self._tick)

        self.get_logger().info(
            "motion_guard gestartet -- enable_live_motion="
            f"{self.get_parameter('enable_live_motion').value}.")

    def _now(self) -> float:
        return time.time()

    def _on_cmd_vel_in(self, msg: Twist):
        self._last_cmd = msg
        self._last_cmd_wall_s = time.time()

    def _on_safety_state(self, msg: SafetyState):
        now = self._now()
        self._safety_allow_motion.update(msg.allow_motion, now)
        self._emergency_stop.update(msg.emergency_stop, now)
        # obstacle_data_valid wird HIER bewusst NICHT mehr aktualisiert
        # (siehe Moduldocstring, Fund 2) -- einzige Quelle bleibt das
        # dedizierte /obstacle_data_valid-Thema unten.

    def _on_bumper(self, msg: Bool):
        self._bumper_active.update(msg.data, self._now())

    def _on_realsense_diagnostics_valid(self, msg: Bool):
        self._realsense_diagnostics_valid.update(msg.data, self._now())

    def _on_odometry_valid(self, msg: Bool):
        self._odometry_valid.update(msg.data, self._now())

    def _on_localization_valid(self, msg: Bool):
        self._localization_valid.update(msg.data, self._now())

    def _on_obstacle_data_valid(self, msg: Bool):
        self._obstacle_data_valid.update(msg.data, self._now())

    def _on_head_navigation_pose_valid(self, msg: Bool):
        self._head_navigation_pose_valid.update(msg.data, self._now())

    def _on_gesture_in_progress(self, msg: Bool):
        self._gesture_in_progress.update(msg.data, self._now())

    def _on_base_lease_valid(self, msg: Bool):
        self._base_lease_valid.update(msg.data, self._now())

    def _tick(self):
        now = self._now()
        max_age = self.get_parameter("max_input_age_s").value
        cmd_age_s = None if self._last_cmd_wall_s is None else now - self._last_cmd_wall_s

        result = evaluate_motion_guard(MotionGuardInputs(
            live_motion_mode_active=self.get_parameter("enable_live_motion").value,
            safety_allow_motion=self._safety_allow_motion.effective(now, max_age, False),
            realsense_diagnostics_valid=self._realsense_diagnostics_valid.effective(now, max_age, False),
            odometry_valid=self._odometry_valid.effective(now, max_age, False),
            localization_valid=self._localization_valid.effective(now, max_age, False),
            obstacle_data_valid=self._obstacle_data_valid.effective(now, max_age, False),
            head_navigation_pose_valid=self._head_navigation_pose_valid.effective(now, max_age, False),
            bumper_active=self._bumper_active.effective(now, max_age, True),
            emergency_stop=self._emergency_stop.effective(now, max_age, True),
            gesture_in_progress=self._gesture_in_progress.effective(now, max_age, True),
            base_lease_valid=self._base_lease_valid.effective(now, max_age, False),
            cmd_age_s=cmd_age_s,
            max_cmd_age_s=self.get_parameter("max_cmd_age_s").value,
        ))

        if result.allow and self._last_cmd is not None:
            self.cmd_pub.publish(self._last_cmd)
        else:
            self.cmd_pub.publish(Twist())  # explizit Nullgeschwindigkeit

        diag = String()
        diag.data = f"allow={result.allow} reason={result.reason}"
        self.diagnostics_pub.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = MotionGuardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
