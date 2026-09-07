#!/usr/bin/env python3
"""
Einfache Skelett-Nachahmung: liest Peppers Frontkamera, erkennt eine Person
per YOLOv8-Pose und laesst Pepper die Armhoehe (Schulterwinkel) live
nachmachen. Erste einfache Version: nur ShoulderPitch (Arm rauf/runter),
kein Roll/Ellbogen/keine Rotation.

Mapping ist "gleichseitig" (Person rechts -> Pepper rechts), kein
Spiegel-Mapping.

Bricht nach --duration Sekunden automatisch ab und faehrt die Arme zurueck
in die Ausgangsposition.
"""
import os
import sys
import time
import math
import argparse
import threading


def _find_flask_wrapper_path() -> str:
    """PEPPER_FLASK_WRAPPER_PATH hat Vorrang, sonst wird 'apps/web' vom
    eigenen Verzeichnis aus nach oben gesucht -- kein absoluter
    Entwicklerpfad im Laufzeitcode (Entwicklungsauftrag 04-B, AP0)."""
    env_value = os.environ.get("PEPPER_FLASK_WRAPPER_PATH")
    if env_value:
        return env_value
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidate = os.path.join(current, "apps", "web")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "web")


sys.path.insert(0, _find_flask_wrapper_path())

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from ultralytics import YOLO

from pepper.qicli import qicli
import config.config as _cfg

# COCO-17 Indizes
L_SHOULDER, L_ELBOW = 5, 7
R_SHOULDER, R_ELBOW = 6, 8

PITCH_DOWN = 1.6   # Arm haengt locker runter
PITCH_UP = -1.5    # Arm zeigt (fast) nach oben
PITCH_MIN, PITCH_MAX = -1.5, 1.6


def angle_to_pitch(shoulder, elbow):
    """Berechnet aus 2D-Keypoints (shoulder->elbow) einen NAOqi-ShoulderPitch-Wert."""
    dx = elbow[0] - shoulder[0]
    dy = elbow[1] - shoulder[1]
    if dx == 0 and dy == 0:
        return None
    angle_from_down = math.atan2(dx, dy)  # 0 = Arm haengt runter, +-pi = Arm zeigt hoch
    frac = abs(angle_from_down) / math.pi  # 0..1
    pitch = PITCH_DOWN + frac * (PITCH_UP - PITCH_DOWN)
    return max(PITCH_MIN, min(PITCH_MAX, pitch))


class MimicNode(Node):
    def __init__(self, duration_s: float, conf: float):
        super().__init__("mimic_arms")
        self.bridge = CvBridge()
        self.model = YOLO("yolov8n-pose.pt")
        self.duration_s = duration_s
        self.conf = conf
        self.start_time = time.time()
        self.last_l = None
        self.last_r = None
        self.busy = False
        self.done = False

        self.ssh = qicli(_cfg.QI_HOST, _cfg.QI_USER, _cfg.QI_PW)
        self.ssh.connect()
        # Sicherstellen dass Arme steif/ansprechbar sind
        self._call("qicli call ALMotion.setStiffnesses LArm 1.0")
        self._call("qicli call ALMotion.setStiffnesses RArm 1.0")
        self.orig_l = self._call("qicli call ALMotion.getAngles LShoulderPitch 1").strip("[]")
        self.orig_r = self._call("qicli call ALMotion.getAngles RShoulderPitch 1").strip("[]")
        self.get_logger().info(f"Ausgangsposition gemerkt: L={self.orig_l} R={self.orig_r}")

        self.sub = self.create_subscription(
            Image, "/camera/front/image_raw", self.on_image, 5
        )
        self.get_logger().info(f"Nachahmung laeuft fuer {duration_s:.0f}s ... (Strg+C zum Abbrechen)")

    def _call(self, cmd):
        out, err = self.ssh.exec_command(f"timeout 8 {cmd}")
        if err:
            self.get_logger().warn(f"{cmd} -> ERR {err}")
        return out

    def on_image(self, msg: Image):
        elapsed = time.time() - self.start_time
        if elapsed > self.duration_s:
            self.finish()
            return
        if self.busy:
            return  # vorherigen SSH-Call erst fertig machen

        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        results = self.model.predict(frame, conf=self.conf, verbose=False)

        kpts = None
        for r in results:
            if r.keypoints is not None and len(r.keypoints.xy) > 0:
                kpts = r.keypoints.xy.cpu().numpy()[0]
                break
        if kpts is None:
            return

        l_pitch = angle_to_pitch(kpts[L_SHOULDER], kpts[L_ELBOW])
        r_pitch = angle_to_pitch(kpts[R_SHOULDER], kpts[R_ELBOW])

        threading.Thread(target=self.send_pose, args=(l_pitch, r_pitch, elapsed), daemon=True).start()

    def send_pose(self, l_pitch, r_pitch, elapsed):
        self.busy = True
        try:
            if l_pitch is not None and (self.last_l is None or abs(l_pitch - self.last_l) > 0.1):
                self._call(f"qicli call ALMotion.angleInterpolation LShoulderPitch {l_pitch:.3f} 0.8 1")
                self.last_l = l_pitch
            if r_pitch is not None and (self.last_r is None or abs(r_pitch - self.last_r) > 0.1):
                self._call(f"qicli call ALMotion.angleInterpolation RShoulderPitch {r_pitch:.3f} 0.8 1")
                self.last_r = r_pitch
            self.get_logger().info(
                f"[{elapsed:5.1f}s] L={l_pitch and round(l_pitch,2)} R={r_pitch and round(r_pitch,2)}"
            )
        finally:
            self.busy = False

    def finish(self):
        if self.done:
            return
        self.done = True
        self.get_logger().info("Fertig, fahre Arme zurueck...")
        self._call(f"qicli call ALMotion.angleInterpolation LShoulderPitch {self.orig_l} 1.0 1")
        self._call(f"qicli call ALMotion.angleInterpolation RShoulderPitch {self.orig_r} 1.0 1")
        self.ssh.close()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--conf", type=float, default=0.4)
    args = parser.parse_args()

    rclpy.init()
    node = MimicNode(duration_s=args.duration, conf=args.conf)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.finish()


if __name__ == "__main__":
    main()
