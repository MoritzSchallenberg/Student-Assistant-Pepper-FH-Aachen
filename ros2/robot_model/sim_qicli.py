#!/usr/bin/env python3
"""
Simulierte Pepper-Steuerung: gleiche Methodennamen wie
apps/web/pepper/qicli.py, aber ohne SSH/echten Roboter -- bewegt
stattdessen das lokale URDF-Modell in RViz (per /joint_states) und
speichert jede Aktion strukturiert als JSON in eine Session-Datei, damit
Bewegungsfolgen spaeter wiederverwendet/ausgewertet ("trainiert") werden
koennen.

WICHTIG: Braucht robot_state_publisher + rviz2 OHNE
joint_state_publisher_gui (die wuerde um /joint_states konkurrieren).
Nutze dafuer display_scripted.launch.py statt display.launch.py:

    ros2 launch pepper_description display_scripted.launch.py

Dann in einem zweiten Terminal:

    python3 sim_qicli.py

... oder als Modul importieren:

    from sim_qicli import SimQicli
    sim = SimQicli(log_path="sessions/session1.json")
    sim.set_angle("LShoulderRoll", 1.3, 1.0)
    sim.wave(side="R")
    sim.close()
"""
import json
import time
import os

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

# Alle Pepper-Gelenke mit neutralen Ausgangswinkeln (rad), grob an die
# beobachteten Ruhewerte des echten Roboters angelehnt.
DEFAULT_ANGLES = {
    "HeadYaw": 0.0, "HeadPitch": 0.0,
    "LShoulderPitch": 1.57, "LShoulderRoll": 0.1, "LElbowYaw": -1.4,
    "LElbowRoll": -0.2, "LWristYaw": 0.0, "LHand": 0.5,
    "RShoulderPitch": 1.57, "RShoulderRoll": -0.1, "RElbowYaw": 1.4,
    "RElbowRoll": 0.2, "RWristYaw": 0.0, "RHand": 0.5,
    "HipRoll": 0.0, "HipPitch": 0.0, "KneePitch": 0.0,
    "WheelFL": 0.0, "WheelFR": 0.0, "WheelB": 0.0,
}

ARM_POSE_JOINTS = ["LShoulderPitch", "RShoulderPitch", "LShoulderRoll",
                   "RShoulderRoll", "LElbowRoll", "RElbowRoll"]


class SimQicli(Node):
    def __init__(self, log_path="pepper_sim_session.json"):
        if not rclpy.ok():
            rclpy.init(args=None)
        super().__init__("sim_qicli")
        self.pub = self.create_publisher(JointState, "/joint_states", 10)
        self.angles = dict(DEFAULT_ANGLES)
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        self.log = []
        self._publish()
        print(f"SimQicli bereit. Log-Datei: {self.log_path}")

    def _publish(self):
        # Reiner Publisher, kein Abonnement auf diesem Node noetig ->
        # spin_once mit vollem Timeout waere hier nur unnoetige Wartezeit.
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(self.angles.keys())
        msg.position = list(self.angles.values())
        self.pub.publish(msg)

    def _log_entry(self, action, **kwargs):
        entry = {"timestamp": time.time(), "action": action, **kwargs}
        self.log.append(entry)
        with open(self.log_path, "w") as f:
            json.dump(self.log, f, indent=2)

    # ---- Gleiche API wie pepper/qicli.py ----

    def get_angle(self, joint):
        return self.angles.get(joint)

    def get_angles(self, joints):
        return {j: self.angles.get(j) for j in joints}

    def set_angle(self, joint, angle, duration=1.0, steps=20):
        """Bewegt ein Gelenk sanft (interpoliert in `steps` Schritten) zum Zielwinkel."""
        start = self.angles.get(joint, 0.0)
        steps = max(1, steps)
        for i in range(1, steps + 1):
            self.angles[joint] = start + (angle - start) * (i / steps)
            self._publish()
            time.sleep(duration / steps)
        self._log_entry("set_angle", joint=joint, angle=angle, duration=duration)
        return True

    def snapshot_joints(self, joints):
        return self.get_angles(joints)

    def restore_joints(self, snapshot, duration=1.5):
        for joint, angle in snapshot.items():
            if angle is not None:
                self.set_angle(joint, angle, duration)
        self._log_entry("restore_joints", snapshot=snapshot, duration=duration)

    def raise_arms_sideways(self, angle=1.3, duration=2.5):
        snapshot = self.snapshot_joints(ARM_POSE_JOINTS)
        self.set_angle("LShoulderPitch", 0.0, duration)
        self.set_angle("RShoulderPitch", 0.0, duration)
        self.set_angle("LElbowRoll", 0.0, duration)
        self.set_angle("RElbowRoll", 0.0, duration)
        self.set_angle("LShoulderRoll", angle, duration)
        self.set_angle("RShoulderRoll", -angle, duration)
        self._log_entry("raise_arms_sideways", angle=angle, duration=duration)
        return snapshot

    def lower_arms(self, snapshot, duration=1.5):
        self.restore_joints(snapshot, duration)
        self._log_entry("lower_arms", duration=duration)

    def play_synchronized_trajectory(self, joint_names, angle_lists, time_lists, steps_per_segment=10):
        """Spielt eine VOLLSTAENDIG synchronisierte Mehrgelenk-Trajektorie
        ab (Entwicklungsauftrag 04-B, AP8.7): ALLE Gelenke bewegen sich
        GEMEINSAM entlang derselben Zeitachse -- bei einem echten
        TrajectoryPlan aus kinematic_compiler.py ist time_lists fuer JEDES
        Gelenk identisch (siehe dortige Moduldoku, fill_missing_joint_holds).
        Im Unterschied zur sequenziellen Annaeherung in gesturectl.py::
        cmd_preview (dort je ein set_angle()-Aufruf NACH dem anderen,
        AUSDRUECKLICH NICHT repraesentativ fuer echtes Timing dokumentiert)
        interpoliert diese Methode JEDEN Zeitschritt aller Gelenke
        GLEICHZEITIG und publiziert sie in EINER gemeinsamen
        /joint_states-Nachricht je Zwischenschritt. Bleibt weiterhin reines
        /joint_states-Publishing -- KEINE echte ALMotion-Ansteuerung, KEIN
        Kollisions-/Kontaktnachweis (siehe trajectory_safety.py in
        ihk_pepper_bridge, DisabledCollisionBackend)."""
        if not joint_names or not time_lists or not time_lists[0]:
            return
        shared_times = time_lists[0]
        current = {j: self.angles.get(j, 0.0) for j in joint_names}
        prev_t = 0.0
        for idx, t in enumerate(shared_times):
            segment_duration = max(t - prev_t, 0.0)
            segment_start = dict(current)
            segment_end = {j: angle_lists[k][idx] for k, j in enumerate(joint_names)}
            steps = max(1, int(steps_per_segment * max(segment_duration, 0.05)))
            for step in range(1, steps + 1):
                frac = step / steps
                for j in joint_names:
                    self.angles[j] = segment_start[j] + (segment_end[j] - segment_start[j]) * frac
                self._publish()
                if segment_duration > 0:
                    time.sleep(segment_duration / steps)
            current = dict(segment_end)
            prev_t = t
        self._log_entry(
            "play_synchronized_trajectory", joint_names=joint_names, time_lists=shared_times)

    def wave(self, side="R", repeats=3):
        sp, er, ey = f"{side}ShoulderPitch", f"{side}ElbowRoll", f"{side}ElbowYaw"
        snapshot = self.snapshot_joints([sp, er, ey])
        sign = 1 if side == "R" else -1
        self.set_angle(sp, -1.0, 1.0)
        self.set_angle(er, 0.9 * sign, 1.0)
        for _ in range(repeats):
            self.set_angle(ey, 0.6, 0.4)
            self.set_angle(ey, 1.6, 0.4)
        self.restore_joints(snapshot, 1.0)
        self._log_entry("wave", side=side, repeats=repeats)

    def close(self):
        self.destroy_node()


if __name__ == "__main__":
    sim = SimQicli(log_path="sessions/demo_session.json")
    sim.wave(side="R", repeats=3)
    snap = sim.raise_arms_sideways()
    time.sleep(1)
    sim.lower_arms(snap)
    sim.close()
    print("Demo fertig. Log gespeichert unter sessions/demo_session.json")
