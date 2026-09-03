#!/usr/bin/env python3
"""
Abonniert Peppers Frontkamera (/camera/front/image_raw), laesst pro Bild
YOLOv8-Pose (Skeleton-Keypoints) drueberlaufen und protokolliert, wie sich
erkannte Personen ueber die Zeit bewegen (Positionsaenderung von Schultern/
Handgelenken/Huefte zwischen Frames).

Laeuft fuer eine feste Dauer und gibt am Ende eine Zusammenfassung aus.
"""
import sys
import time
import argparse

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

from ultralytics import YOLO

# COCO-17 Keypoint-Reihenfolge, wie sie YOLOv8-pose liefert
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


class PoseWatcher(Node):
    def __init__(self, duration_s: float, conf: float):
        super().__init__("pose_watcher")
        self.bridge = CvBridge()
        self.model = YOLO("yolov8n-pose.pt")  # laedt beim ersten Mal automatisch
        self.duration_s = duration_s
        self.conf = conf
        self.start_time = time.time()
        self.frame_count = 0
        self.detections_over_time = []  # Liste von (t, [person_keypoints])
        self.sub = self.create_subscription(
            Image, "/camera/front/image_raw", self.on_image, 5
        )
        self.get_logger().info(
            f"Beobachte /camera/front/image_raw fuer {duration_s:.0f}s ..."
        )

    def on_image(self, msg: Image):
        elapsed = time.time() - self.start_time
        if elapsed > self.duration_s:
            self.finish()
            return

        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        self.frame_count += 1

        results = self.model.predict(frame, conf=self.conf, verbose=False)
        people = []
        for r in results:
            if r.keypoints is None:
                continue
            for person_kpts in r.keypoints.xy.cpu().numpy():
                # person_kpts: (17, 2) Array aus (x, y) Pixelkoordinaten
                people.append(person_kpts.tolist())

        self.detections_over_time.append((elapsed, people))
        self.get_logger().info(
            f"[{elapsed:5.1f}s] Frame {self.frame_count}: {len(people)} Person(en) erkannt"
        )

    def finish(self):
        self.print_summary()
        rclpy.shutdown()

    def print_summary(self):
        print("\n" + "=" * 60)
        print("ZUSAMMENFASSUNG")
        print("=" * 60)
        frames_with_people = [d for d in self.detections_over_time if d[1]]
        print(f"Frames gesamt: {len(self.detections_over_time)}")
        print(f"Frames mit mind. 1 Person: {len(frames_with_people)}")

        if len(frames_with_people) < 2:
            print("Zu wenige Detektionen fuer eine Bewegungsanalyse.")
            return

        # Bewegung der ersten erkannten Person ueber die Zeit verfolgen
        # (einfache Heuristik: nimm jeweils Person 0 im Frame)
        prev_t, prev_kpts = frames_with_people[0]
        total_displacement = {name: 0.0 for name in KEYPOINT_NAMES}
        samples = 0

        for t, people in frames_with_people[1:]:
            kpts = people[0]
            for i, name in enumerate(KEYPOINT_NAMES):
                x0, y0 = prev_kpts[0][i]
                x1, y1 = kpts[i]
                if (x0, y0) == (0.0, 0.0) or (x1, y1) == (0.0, 0.0):
                    continue  # Keypoint nicht erkannt
                dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
                total_displacement[name] += dist
            prev_kpts = [kpts]
            samples += 1

        print(f"\nBewegung pro Koerperpunkt (Summe Pixel-Verschiebung ueber {samples} Frame-Uebergaenge):")
        ranked = sorted(total_displacement.items(), key=lambda kv: -kv[1])
        for name, dist in ranked:
            if dist > 0:
                bar = "#" * int(dist / 5)
                print(f"  {name:16s} {dist:7.1f}px  {bar}")

        most_active = ranked[0][0]
        print(f"\n-> Am meisten bewegt hat sich: {most_active}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=30.0, help="Beobachtungsdauer in Sekunden")
    parser.add_argument("--conf", type=float, default=0.4, help="Mindest-Konfidenz fuer Detektion")
    args = parser.parse_args()

    rclpy.init()
    node = PoseWatcher(duration_s=args.duration, conf=args.conf)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.print_summary()


if __name__ == "__main__":
    main()
