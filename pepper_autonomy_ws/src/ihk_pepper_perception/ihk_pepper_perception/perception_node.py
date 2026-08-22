#!/usr/bin/env python3
"""
ihk_pepper_perception: erweitert die vorhandene YOLO-Pose-Erkennung
(vision_ws/pose_watch.py) zu dauerhaftem Multi-Personen-Tracking mit
temporaeren Track-IDs (Arbeitspaket 4) und Interesse-Score
(Arbeitspaket 5). Nutzt ultralytics' eingebautes ByteTrack (model.track())
fuer persistente IDs statt eines selbstgeschriebenen Trackers.

KEINE Gesichtswiedererkennung, KEINE dauerhafte biometrische Identitaet.

Kameraquelle ist per Parameter umschaltbar (RealSense bevorzugt, Pepper-
Kamera als Fallback) OHNE Codeaenderung -- siehe config/perception_params.yaml.

Getestet (2026-08-20): Modul-Import, Interest-Scoring (Unit-Tests mit
synthetischen Tracks). NICHT mit einer laufenden Kamera getestet -- weder
Pepper (nicht verbunden) noch eine externe RealSense (nicht vorhanden in
dieser Session). Siehe IMPLEMENTATION_REPORT.md.
"""
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge

from ihk_pepper_interfaces.msg import PersonTrack, PersonTrackArray

from .interest_scoring import TrackHistory, score as interest_score

# COCO-17 Keypoint-Indizes (siehe vision_ws/pose_watch.py)
L_SHOULDER, R_SHOULDER = 5, 6
L_WRIST, R_WRIST = 9, 10


class PerceptionNode(Node):
    def __init__(self):
        super().__init__("perception_node")

        self.declare_parameter("image_topic", "/camera/front/image_raw")
        self.declare_parameter("depth_topic", "")  # leer = kein Tiefenbild, has_3d_position bleibt False
        self.declare_parameter("camera_info_topic", "/camera/front/camera_info")
        self.declare_parameter("camera_frame", "CameraTop_optical_frame")
        self.declare_parameter("confidence_threshold", 0.4)
        self.declare_parameter("model_path", "yolov8n-pose.pt")
        self.declare_parameter("publish_rate_limit_s", 0.0)  # 0 = jedes Frame verarbeiten

        from ultralytics import YOLO
        self.model = YOLO(self.get_parameter("model_path").value)
        self.bridge = CvBridge()

        self.track_histories: dict[int, TrackHistory] = {}
        self.last_publish_t = 0.0

        self.tracks_pub = self.create_publisher(PersonTrackArray, "person_tracks", 10)

        image_topic = self.get_parameter("image_topic").value
        self.create_subscription(Image, image_topic, self._on_image, 5)

        depth_topic = self.get_parameter("depth_topic").value
        self._latest_depth = None
        if depth_topic:
            self.create_subscription(Image, depth_topic, self._on_depth, 5)

        self.get_logger().info(
            f"perception_node gestartet. Bildquelle: {image_topic} "
            f"(Tiefe: {depth_topic or 'keine -- nur 2D'})"
        )

    def _on_depth(self, msg: Image):
        self._latest_depth = msg

    def _on_image(self, msg: Image):
        rate_limit = self.get_parameter("publish_rate_limit_s").value
        now = time.time()
        if rate_limit and (now - self.last_publish_t) < rate_limit:
            return

        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        conf = self.get_parameter("confidence_threshold").value

        try:
            results = self.model.track(frame, conf=conf, persist=True, verbose=False)
        except Exception as e:
            self.get_logger().error(f"YOLO-Tracking fehlgeschlagen: {e}")
            return

        array_msg = PersonTrackArray()
        array_msg.header = msg.header

        seen_ids = set()
        for r in results:
            if r.keypoints is None or r.boxes is None or r.boxes.id is None:
                continue
            ids = r.boxes.id.cpu().numpy().astype(int)
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            kpts_all = r.keypoints.xy.cpu().numpy()
            img_h, img_w = frame.shape[:2]

            for i, track_id in enumerate(ids):
                seen_ids.add(int(track_id))
                bbox = xyxy[i]
                kpts = kpts_all[i]
                track_msg, history = self._build_track(
                    track_id=int(track_id), bbox=bbox, confidence=float(confs[i]),
                    keypoints=kpts, img_w=img_w, img_h=img_h, stamp=msg.header,
                )
                array_msg.tracks.append(track_msg)

        # Historien fuer nicht mehr sichtbare Tracks als "nicht aktuell
        # gesehen" markieren (fuer stale_data-Signal), statt sie sofort
        # zu loeschen -- kurze Verdeckungen sollen die Interesse-Bewertung
        # nicht sofort auf 0 zuruecksetzen.
        for tid, hist in self.track_histories.items():
            if tid not in seen_ids:
                hist.time_since_seen_s += 1.0  # grobe Naeherung, kein exaktes Delta-t

        self.tracks_pub.publish(array_msg)
        self.last_publish_t = now

    def _build_track(self, track_id, bbox, confidence, keypoints, img_w, img_h, stamp):
        history = self.track_histories.setdefault(track_id, TrackHistory())
        history.frame_count += 1
        history.time_since_seen_s = 0.0

        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        history.image_center_offset = abs(cx - img_w / 2) / (img_w / 2)

        l_wrist, r_wrist = keypoints[L_WRIST], keypoints[R_WRIST]
        l_shoulder, r_shoulder = keypoints[L_SHOULDER], keypoints[R_SHOULDER]
        wrist_up = False
        for wrist, shoulder in ((l_wrist, l_shoulder), (r_wrist, r_shoulder)):
            if wrist[0] == 0 and wrist[1] == 0:
                continue
            if wrist[1] < shoulder[1]:  # Bildkoordinaten: kleineres y = weiter oben
                wrist_up = True
        history.last_wrist_above_shoulder = wrist_up

        # 3D-Position: nur wenn Tiefenbild vorhanden UND Kamera-Intrinsics
        # bekannt waeren (letzteres in dieser Session nicht verdrahtet,
        # siehe IMPLEMENTATION_REPORT.md -- deshalb bleibt has_3d_position
        # aktuell immer False, aber die Struktur ist vorbereitet).
        has_3d = False
        distance_m = None
        if self._latest_depth is not None:
            # TODO: Pixel (cx,cy) per CameraInfo-Intrinsics entprojizieren.
            pass
        history.distance_m = distance_m
        history.has_valid_depth = has_3d

        i_score = interest_score(history)

        msg = PersonTrack()
        msg.header = stamp
        msg.track_id = track_id
        msg.confidence = confidence
        msg.bbox_x = int(x1)
        msg.bbox_y = int(y1)
        msg.bbox_width = int(x2 - x1)
        msg.bbox_height = int(y2 - y1)
        msg.image_x = float(cx)
        msg.image_y = float(cy)
        msg.has_3d_position = has_3d
        msg.frame_id = self.get_parameter("camera_frame").value
        msg.last_seen = self.get_clock().now().to_msg()
        msg.distance_m = distance_m or 0.0
        msg.has_velocity = False
        msg.body_orientation_rad = float("nan")
        msg.interest_score = i_score
        return msg, history


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
