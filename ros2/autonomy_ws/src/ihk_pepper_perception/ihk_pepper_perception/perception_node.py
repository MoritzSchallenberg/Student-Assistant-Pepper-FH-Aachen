#!/usr/bin/env python3
"""
ihk_pepper_perception: erweitert die vorhandene YOLO-Pose-Erkennung
(vision/pose_watch.py) zu dauerhaftem Multi-Personen-Tracking mit
temporaeren Track-IDs, Interesse-Score, synchronisierter 3D-Position und
zeitlich robuster Wink-Erkennung (Entwicklungsauftrag 1, Abschnitte 4+5).
Nutzt ultralytics' eingebautes ByteTrack (model.track()) fuer persistente
IDs statt eines selbstgeschriebenen Trackers.

KEINE Gesichtswiedererkennung, KEINE dauerhafte biometrische Identitaet.

Zwei Betriebsmodi, rein ueber Parameter (kein Codeunterschied):
- depth_topic gesetzt: synchronisierte Farbe+Tiefe+CameraInfo
  (message_filters.ApproximateTimeSynchronizer) -- liefert echte
  3D-Positionen ueber deprojection.py + TF nach base_frame. So laeuft
  das mit RealSense (siehe ihk_pepper_navigation/launch/realsense_bringup.launch.py).
- depth_topic leer: reiner 2D-Fallback wie bisher (Pepper-Kopfkamera),
  has_3d_position bleibt IMMER False.

Fehlende/veraltete Tiefe oder TF fuehrt IMMER zu has_3d_position=False,
NIE zu einer geschaetzten Fantasieposition (Entwicklungsauftrag 1,
Abschnitt 4, harte Anforderung).

Getestet (2026-09-03): deprojection.py und wave_detector.py als reine
Module vollstaendig per Unit-Test abgedeckt (siehe ihk_pepper_tests).
Der Node selbst (message_filters-Sync, TF-Lookup, YOLO-Tracking) ist
NICHT mit einer laufenden Kamera getestet -- weder Pepper noch eine
externe RealSense waren in dieser Session verfuegbar. Siehe
docs/DEVELOPMENT_ORDER_01_REPORT.md.
"""
import time

import message_filters
import rclpy
import tf2_geometry_msgs  # noqa: F401 -- registriert do_transform_point fuer PointStamped
import tf2_ros
from cv_bridge import CvBridge
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String

from ihk_pepper_interfaces.msg import PersonTrack, PersonTrackArray, WaveGestureEvent

from .deprojection import CameraIntrinsics, deproject_pixel, estimate_patch_depth
from .interest_scoring import TrackHistory, score as interest_score
from .wave_detector import PoseObservation, WaveDetector

# COCO-17 Keypoint-Indizes (siehe vision/pose_watch.py)
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 5, 6, 7, 8, 9, 10


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
        self.declare_parameter("source_camera_name", "pepper_camera_2d_only")

        # Synchronisierte 3D-Verarbeitung (Abschnitt 4)
        self.declare_parameter("sync_slop_s", 0.05)
        self.declare_parameter("depth_scale_to_m", 1.0)  # z.B. 0.001 bei 16UC1-Millimeter-Tiefe
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("tf_timeout_s", 0.1)
        self.declare_parameter("track_timeout_s", 5.0)
        self.declare_parameter("min_stable_frames", 5)
        self.declare_parameter("min_stable_duration_s", 1.0)

        # Wink-Erkennung (Abschnitt 5)
        self.declare_parameter("enable_wave_detection", True)
        self.declare_parameter("wave_min_keypoint_confidence", 0.3)

        from ultralytics import YOLO
        self.model = YOLO(self.get_parameter("model_path").value)
        self.bridge = CvBridge()

        self.track_histories: dict[int, TrackHistory] = {}
        self._wave_last_state: dict[tuple, str] = {}  # (track_id, side) -> letzter WaveState-Wert
        self.last_publish_t = 0.0

        from .wave_detector import WaveDetectorConfig
        self.wave_detector = WaveDetector(WaveDetectorConfig(
            min_keypoint_confidence=self.get_parameter("wave_min_keypoint_confidence").value,
        ))

        self.tracks_pub = self.create_publisher(PersonTrackArray, "person_tracks", 10)
        self.wave_pub = self.create_publisher(WaveGestureEvent, "wave_gesture_events", 10)
        self.diagnostics_pub = self.create_publisher(String, "perception_node/diagnostics", 10)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self._last_color_stamp_s = None
        self._last_depth_stamp_s = None
        self._last_tf_lookup_ok = False

        depth_topic = self.get_parameter("depth_topic").value
        image_topic = self.get_parameter("image_topic").value
        if depth_topic:
            camera_info_topic = self.get_parameter("camera_info_topic").value
            color_sub = message_filters.Subscriber(self, Image, image_topic)
            depth_sub = message_filters.Subscriber(self, Image, depth_topic)
            info_sub = message_filters.Subscriber(self, CameraInfo, camera_info_topic)
            self._sync = message_filters.ApproximateTimeSynchronizer(
                [color_sub, depth_sub, info_sub], queue_size=5,
                slop=self.get_parameter("sync_slop_s").value,
            )
            self._sync.registerCallback(self._on_synced)
            self._sync_subs = (color_sub, depth_sub, info_sub)  # Referenzen halten (sonst GC)
            self.get_logger().info(
                f"perception_node gestartet (synchronisiert). Farbe: {image_topic}, "
                f"Tiefe: {depth_topic}, CameraInfo: {camera_info_topic}"
            )
        else:
            self.create_subscription(Image, image_topic, self._on_image_only, 5)
            self.get_logger().info(
                f"perception_node gestartet (2D-Fallback, kein depth_topic). Bildquelle: {image_topic}"
            )

        self.create_timer(1.0, self._publish_diagnostics)

    # ---- Zwei Eingangspfade, gemeinsame Verarbeitung in _process_frame ----

    def _on_image_only(self, msg: Image):
        rate_limit = self.get_parameter("publish_rate_limit_s").value
        now = time.time()
        if rate_limit and (now - self.last_publish_t) < rate_limit:
            return
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        self._last_color_stamp_s = _stamp_to_s(msg.header.stamp)
        self._process_frame(
            frame_bgr=frame, header=msg.header, depth_image=None, intrinsics=None,
            source_camera=self.get_parameter("source_camera_name").value or "pepper_camera_2d_only",
        )
        self.last_publish_t = now

    def _on_synced(self, color_msg: Image, depth_msg: Image, info_msg: CameraInfo):
        rate_limit = self.get_parameter("publish_rate_limit_s").value
        now = time.time()
        if rate_limit and (now - self.last_publish_t) < rate_limit:
            return

        frame = self.bridge.imgmsg_to_cv2(color_msg, desired_encoding="bgr8")
        depth_image = self.bridge.imgmsg_to_cv2(depth_msg, desired_encoding="passthrough")
        intrinsics = CameraIntrinsics.from_camera_info_k(info_msg.k)

        self._last_color_stamp_s = _stamp_to_s(color_msg.header.stamp)
        self._last_depth_stamp_s = _stamp_to_s(depth_msg.header.stamp)

        self._process_frame(
            frame_bgr=frame, header=color_msg.header, depth_image=depth_image, intrinsics=intrinsics,
            depth_frame_id=depth_msg.header.frame_id,
            source_camera=self.get_parameter("source_camera_name").value or "realsense",
        )
        self.last_publish_t = now

    def _process_frame(self, frame_bgr, header, depth_image, intrinsics,
                        source_camera, depth_frame_id=None):
        conf = self.get_parameter("confidence_threshold").value
        try:
            results = self.model.track(frame_bgr, conf=conf, persist=True, verbose=False)
        except Exception as e:
            self.get_logger().error(f"YOLO-Tracking fehlgeschlagen: {e}")
            return

        frame_time_s = _stamp_to_s(header.stamp) or time.time()
        array_msg = PersonTrackArray()
        array_msg.header = header

        seen_ids = set()
        for r in results:
            if r.keypoints is None or r.boxes is None or r.boxes.id is None:
                continue
            ids = r.boxes.id.cpu().numpy().astype(int)
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            kpts_all = r.keypoints.xy.cpu().numpy()
            kpts_conf_all = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else None
            img_h, img_w = frame_bgr.shape[:2]

            for i, track_id in enumerate(ids):
                tid = int(track_id)
                seen_ids.add(tid)
                bbox = xyxy[i]
                kpts = kpts_all[i]
                kpts_conf = kpts_conf_all[i] if kpts_conf_all is not None else None
                track_msg = self._build_track(
                    track_id=tid, bbox=bbox, confidence=float(confs[i]),
                    keypoints=kpts, keypoints_conf=kpts_conf, img_w=img_w, img_h=img_h,
                    header=header, frame_time_s=frame_time_s,
                    depth_image=depth_image, intrinsics=intrinsics,
                    depth_frame_id=depth_frame_id, source_camera=source_camera,
                )
                array_msg.tracks.append(track_msg)

        # Nicht mehr gesehene Tracks: echte Zeitdifferenz statt der
        # frueheren "+= 1.0 pro Frame"-Naeherung, und nach track_timeout_s
        # tatsaechlich loeschen (inkl. Wave-Detector-Zustand -- Track-
        # ID-Kontinuitaet, siehe wave_detector.py).
        timeout_s = self.get_parameter("track_timeout_s").value
        stale_ids = []
        for tid, hist in self.track_histories.items():
            if tid in seen_ids:
                continue
            hist.time_since_seen_s = max(0.0, frame_time_s - hist.last_seen_wall_s)
            if hist.time_since_seen_s > timeout_s:
                stale_ids.append(tid)
        for tid in stale_ids:
            del self.track_histories[tid]
            self.wave_detector.reset_track(tid)
            for side in ("L", "R"):
                self._wave_last_state.pop((tid, side), None)

        self.tracks_pub.publish(array_msg)

    def _build_track(self, track_id, bbox, confidence, keypoints, keypoints_conf, img_w, img_h,
                      header, frame_time_s, depth_image, intrinsics, depth_frame_id, source_camera):
        history = self.track_histories.setdefault(track_id, TrackHistory())
        if history.first_seen_s is None:
            history.first_seen_s = frame_time_s
        history.frame_count += 1
        history.time_since_seen_s = 0.0
        history.last_seen_wall_s = frame_time_s

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

        # ---- 3D-Position (Abschnitt 4) ----
        has_3d = False
        position_3d = None
        depth_confidence = 0.0
        frame_id_out = header.frame_id
        distance_m = None

        if depth_image is not None and intrinsics is not None:
            depth_est = estimate_patch_depth(
                depth_image, center_x_px=cx, center_y_px=cy,
                depth_scale_to_m=self.get_parameter("depth_scale_to_m").value,
            )
            if depth_est is not None:
                point_optical = deproject_pixel(cx, cy, depth_est.depth_m, intrinsics)
                transformed = self._transform_to_base_frame(
                    point_optical, depth_frame_id or header.frame_id, header.stamp,
                )
                if transformed is not None:
                    has_3d = True
                    position_3d = transformed
                    distance_m = depth_est.depth_m
                    depth_confidence = depth_est.confidence
                    frame_id_out = self.get_parameter("base_frame").value

        history.distance_m = distance_m
        history.has_valid_depth = has_3d
        history.depth_confidence = depth_confidence
        if has_3d:
            history.positions_m.append((position_3d.x, position_3d.y, frame_time_s))
            # Nur ein begrenztes Fenster behalten -- interest_scoring braucht
            # nur die letzten beiden Punkte, unbegrenztes Wachstum vermeiden.
            if len(history.positions_m) > 50:
                history.positions_m = history.positions_m[-50:]

        stable_for_s = frame_time_s - history.first_seen_s
        min_frames = self.get_parameter("min_stable_frames").value
        min_duration = self.get_parameter("min_stable_duration_s").value
        stable = (
            history.frame_count >= min_frames
            and stable_for_s >= min_duration
            and history.time_since_seen_s <= self.get_parameter("track_timeout_s").value
        )

        i_score = interest_score(history)

        msg = PersonTrack()
        msg.header = header
        msg.track_id = track_id
        msg.confidence = confidence
        msg.bbox_x = int(x1)
        msg.bbox_y = int(y1)
        msg.bbox_width = int(x2 - x1)
        msg.bbox_height = int(y2 - y1)
        msg.image_x = float(cx)
        msg.image_y = float(cy)
        msg.has_3d_position = has_3d
        if has_3d:
            msg.position_3d.x = position_3d.x
            msg.position_3d.y = position_3d.y
            msg.position_3d.z = position_3d.z
        msg.frame_id = frame_id_out
        msg.last_seen = self.get_clock().now().to_msg()
        msg.distance_m = distance_m or 0.0
        msg.has_velocity = False
        msg.body_orientation_rad = float("nan")
        msg.interest_score = i_score
        msg.stable = stable
        msg.stable_for_s = max(0.0, stable_for_s)
        msg.depth_confidence = depth_confidence
        msg.source_camera = source_camera

        if self.get_parameter("enable_wave_detection").value:
            self._update_wave_detection(track_id, keypoints, keypoints_conf, frame_time_s, header)

        return msg

    def _update_wave_detection(self, track_id, keypoints, keypoints_conf, frame_time_s, header):
        def _conf(idx):
            return float(keypoints_conf[idx]) if keypoints_conf is not None else 1.0

        def _xy(idx):
            kp = keypoints[idx]
            if kp[0] == 0 and kp[1] == 0:
                return None
            return (float(kp[0]), float(kp[1]))

        sides = (
            ("L", L_SHOULDER, L_ELBOW, L_WRIST),
            ("R", R_SHOULDER, R_ELBOW, R_WRIST),
        )
        for side, shoulder_idx, elbow_idx, wrist_idx in sides:
            pose = PoseObservation(
                timestamp_s=frame_time_s,
                shoulder_xy=_xy(shoulder_idx), shoulder_confidence=_conf(shoulder_idx),
                elbow_xy=_xy(elbow_idx), elbow_confidence=_conf(elbow_idx),
                wrist_xy=_xy(wrist_idx), wrist_confidence=_conf(wrist_idx),
            )
            event = self.wave_detector.update(track_id, side, pose)
            if event is None:
                continue
            key = (track_id, side)
            if self._wave_last_state.get(key) == event.state:
                continue  # nur bei Zustandsaenderung publizieren, nicht jeden Frame
            self._wave_last_state[key] = event.state

            out = WaveGestureEvent()
            out.header = header
            out.track_id = track_id
            out.gesture_name = event.gesture_name
            out.confidence = event.confidence
            out.stable = event.stable
            out.observed_duration_s = event.observed_duration_s
            out.last_seen = self.get_clock().now().to_msg()
            out.state = event.state
            self.wave_pub.publish(out)

    def _transform_to_base_frame(self, point_optical, optical_frame_id, stamp):
        """Fehlende/veraltete TF fuehrt IMMER zu None (-> has_3d_position
        bleibt False), NIE zu einer geschaetzten Position. Transformation
        nach map wird in diesem Auftrag bewusst NICHT versucht -- es gibt
        keine echte Lokalisierung (siehe docs/ARCHITECTURE_REALSense_BT.md,
        Entwicklungsauftrag 2)."""
        base_frame = self.get_parameter("base_frame").value
        ps = PointStamped()
        ps.header.frame_id = optical_frame_id
        ps.header.stamp = stamp
        ps.point.x, ps.point.y, ps.point.z = point_optical.x, point_optical.y, point_optical.z
        try:
            timeout = rclpy.duration.Duration(seconds=self.get_parameter("tf_timeout_s").value)
            transform = self.tf_buffer.lookup_transform(base_frame, optical_frame_id, stamp, timeout)
            self._last_tf_lookup_ok = True
            transformed = tf2_geometry_msgs.do_transform_point(ps, transform)
            return transformed.point
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as e:
            self._last_tf_lookup_ok = False
            self.get_logger().debug(f"TF {optical_frame_id}->{base_frame} nicht verfuegbar: {e}")
            return None

    def _publish_diagnostics(self):
        now = time.time()
        image_age = (now - self._last_color_stamp_s) if self._last_color_stamp_s else float("inf")
        depth_age = (now - self._last_depth_stamp_s) if self._last_depth_stamp_s else float("inf")
        valid_3d = sum(1 for h in self.track_histories.values() if h.has_valid_depth)
        msg = String()
        msg.data = (
            f"image_age_s={image_age:.2f} depth_age_s={depth_age:.2f} "
            f"tf_ok={self._last_tf_lookup_ok} valid_3d_tracks={valid_3d} "
            f"total_tracks={len(self.track_histories)}"
        )
        self.diagnostics_pub.publish(msg)


def _stamp_to_s(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


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
