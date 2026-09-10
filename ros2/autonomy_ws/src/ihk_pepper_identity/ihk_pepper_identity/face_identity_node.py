#!/usr/bin/env python3
"""
face_identity_node: echter ROS2-Node, der RealSense-Farbbilder,
Tiefenbilder und CameraInfo synchronisiert, mit
/perception_node/person_tracks kombiniert, Gesichter erkennt, sie
räumlich Tracks zuordnet, Liveness und Mehrframe-Bestätigung
durchführt und NUR bei aktuell gültiger Einwilligung eine persistente
Identität veröffentlicht (Entwicklungsauftrag 04-B, AP7.1, Abschnitt
6). Schließt die in AP7 offen dokumentierte Lücke ("kein
Identity-Laufzeitknoten") -- ihk_pepper_identity war bis hierhin ein
reines Bibliothekspaket ohne registrierten console_scripts-Eintrag.

Veröffentlicht /identity/person_identities (PersonIdentityArray, siehe
ihk_pepper_interfaces). Diagnose ausschließlich als Text-Zusammenfassung
auf /identity/status -- KEIN Rohbild, KEIN Face-Crop, KEIN Embedding
verlässt jemals diesen Node auf irgendeinem Topic (Auftrag Abschnitt 6:
"Keine Rohbilder, Face Crops oder Embeddings auf normalen
Diagnosetopics veröffentlichen").

EHRLICHER STAND (Rollenaufloesung, Auftrag Abschnitt 8/AP7.1.4): dieser
Node liefert AUSSCHLIESSLICH eine bestätigte person_id (oder
known=False) -- role/role_verified bleiben hier IMMER auf dem
sicheren Platzhalter ("student"/False). Die eigentliche, vertrauens-
würdige Rollenauflösung (identity_registry_db.py::get_effective_role())
und die Umstellung von command_router_node.py, NICHT mehr
PersonIdentity.role direkt zu vertrauen, folgen in einem separaten
Commit (role_resolution.py) -- ein Identity-Node, der selbst eine
Rolle "erfindet", wäre genau die in Auftrag Abschnitt 8 verbotene
Vermischung von Identität und Rolle.

Fail-closed durchgehend: fehlendes Modell blockiert das Gesamtsystem
NICHT (DisabledFaceDetector/DisabledIdentityBackend sind gültige,
sichere Defaults -- Standardkonfiguration dieses Nodes), ein einzelner
defekter Frame beendet den Node NICHT (_on_synced() fängt jede
Ausnahme selbst ab), veraltete/fehlende Tracks führen zu einer leeren
Veröffentlichung statt eines Absturzes, ein nicht erreichbarer
Biometrie-/Registry-Speicher führt zu einer leeren Kandidatenliste
bzw. verweigertem Consent (NIE zu einer automatisch angenommenen
Identität)."""
import time

import message_filters
import rclpy
from cv_bridge import CvBridge
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String

from ihk_pepper_interfaces.msg import PersonIdentity, PersonIdentityArray, PersonTrackArray
from ihk_pepper_interfaces.srv import EnrollPerson
from ihk_pepper_person_memory.identity_registry_db import ConsentStatus, IdentityRegistryStore

from .biometric_template_store import BiometricTemplateStore
from .enrollment_session import EnrollmentState, observe_enrollment_frame
from .face_detector_backend import DisabledFaceDetector, LocalOnnxFaceDetector, MockFaceDetector
from .face_identity_backend import DisabledIdentityBackend, LocalOnnxIdentityBackend, MockIdentityBackend
from .face_track_association import TrackBoundingBox, match_faces_to_tracks
from .identity_frame_processor import IdentityFrameConfig, process_frame
from .liveness import check_liveness
from .persistent_identity_confirmer import PersistentIdentityConfirmer

# Auftrag Abschnitt 8: der Platzhalter-Rollenwert dieses Nodes -- NIE
# ein anderer Wert, siehe Moduldoku. Bewusst als String-Literal, nicht
# aus roles.py importiert, um keine Rollenentscheidung in diesem Node
# vorzutaeuschen.
_PLACEHOLDER_ROLE = "student"


class FaceIdentityNode(Node):
    def __init__(self):
        super().__init__("face_identity")

        self.declare_parameter("image_topic", "/camera/front/image_raw")
        self.declare_parameter("depth_topic", "/camera/front/depth/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/front/camera_info")
        self.declare_parameter("sync_slop_s", 0.05)
        self.declare_parameter("depth_scale_to_m", 1.0)
        self.declare_parameter("person_tracks_max_age_s", 1.0)

        # disabled|mock|local_onnx -- disabled ist der sichere Default,
        # damit ein normaler Start ohne explizite Konfiguration NIE
        # ein Modell laedt (Auftrag Abschnitt 5).
        self.declare_parameter("face_detector_kind", "disabled")
        self.declare_parameter("face_detector_model_path", "")
        self.declare_parameter("face_detector_minimum_confidence", 0.5)

        self.declare_parameter("identity_backend_kind", "disabled")
        self.declare_parameter("identity_backend_model_path", "")

        # "" = Node-interner Default aus biometric_template_store.py
        # bzw. Consent-Pruefung dauerhaft deaktiviert (IMMER
        # known=False), siehe _consent_lookup()/_template_candidates().
        self.declare_parameter("biometric_db_path", "")
        self.declare_parameter("identity_registry_db_path", "")

        self.declare_parameter("required_consecutive_matches", 3)
        self.declare_parameter("confirmation_validity_s", 30.0)
        self.declare_parameter("result_validity_s", 2.0)
        self.declare_parameter("minimum_iou", 0.3)
        self.declare_parameter("ambiguity_margin", 0.1)
        self.declare_parameter("minimum_depth_confidence", 0.3)
        self.declare_parameter("minimum_track_distance_m", 0.3)
        self.declare_parameter("maximum_track_distance_m", 4.0)
        self.declare_parameter("minimum_liveness_valid_samples", 20)
        self.declare_parameter("minimum_liveness_depth_std_m", 0.008)
        self.declare_parameter("minimum_match_similarity", 0.55)
        self.declare_parameter("minimum_match_margin", 0.05)

        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 7: Einschreibung.
        self.declare_parameter("enrollment_required_observations", 5)
        self.declare_parameter("enrollment_minimum_consistency_similarity", 0.85)
        self.declare_parameter("enrollment_default_timeout_s", 20.0)
        self.declare_parameter("enrollment_poll_interval_s", 0.05)

        self.bridge = CvBridge()
        self._face_detector = _build_face_detector(self)
        self._identity_backend = _build_identity_backend(self)
        self._confirmer = PersistentIdentityConfirmer(
            required_consecutive_matches=self.get_parameter("required_consecutive_matches").value,
            confirmation_validity_s=self.get_parameter("confirmation_validity_s").value,
        )

        self._biometric_store = None
        try:
            db_path = self.get_parameter("biometric_db_path").value
            self._biometric_store = BiometricTemplateStore(db_path) if db_path else BiometricTemplateStore()
        except Exception as e:
            self.get_logger().error(
                f"BiometricTemplateStore nicht verfuegbar -- persistente Zuordnung "
                f"bleibt fail-closed IMMER unknown: {e}")

        self._identity_registry = None
        registry_path = self.get_parameter("identity_registry_db_path").value
        if registry_path:
            try:
                self._identity_registry = IdentityRegistryStore(registry_path)
            except Exception as e:
                self.get_logger().error(
                    f"IdentityRegistryStore nicht erreichbar -- Consent-Pruefung bleibt "
                    f"fail-closed IMMER verweigert: {e}")

        self._latest_tracks = None
        self._latest_tracks_received_s = 0.0
        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 7: hoechstens EINE
        # aktive Einschreibungssitzung gleichzeitig -- None, solange
        # keine laeuft.
        self._enrollment_state = None

        self.identity_pub = self.create_publisher(PersonIdentityArray, "/identity/person_identities", 10)
        self.status_pub = self.create_publisher(String, "/identity/status", 10)

        self.create_subscription(
            PersonTrackArray, "/perception_node/person_tracks", self._on_tracks, 10)

        # ReentrantCallbackGroup: der (blockierende) Einschreibungs-
        # Service-Handler muss gleichzeitig mit _on_synced() laufen
        # koennen (das liefert waehrend der Sitzung die eigentlichen
        # Beobachtungen) -- gleiches Prinzip wie person_approach_node.py.
        cb_group = ReentrantCallbackGroup()
        self.enroll_srv = self.create_service(
            EnrollPerson, "enroll_person", self._on_enroll_request, callback_group=cb_group)

        image_topic = self.get_parameter("image_topic").value
        depth_topic = self.get_parameter("depth_topic").value
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
            f"face_identity gestartet (face_detector="
            f"{self.get_parameter('face_detector_kind').value}, identity_backend="
            f"{self.get_parameter('identity_backend_kind').value})."
        )

    # ---- Eingehende Daten ----

    def _on_tracks(self, msg: PersonTrackArray):
        self._latest_tracks = msg
        self._latest_tracks_received_s = time.time()

    def _current_tracks(self):
        """Auftrag Abschnitt 6, Punkt 10: veraltete Trackdaten fuehren
        zu einer LEEREN Trackliste (also keiner Identitaetsmeldung),
        NIE zu einer Weiterverwendung eines alten Standes."""
        max_age = self.get_parameter("person_tracks_max_age_s").value
        if self._latest_tracks is None or (time.time() - self._latest_tracks_received_s) > max_age:
            return []
        return [
            TrackBoundingBox(
                track_id=int(t.track_id), bbox_x=t.bbox_x, bbox_y=t.bbox_y,
                bbox_width=t.bbox_width, bbox_height=t.bbox_height,
                has_3d_position=t.has_3d_position, distance_m=t.distance_m,
                depth_confidence=t.depth_confidence,
            )
            for t in self._latest_tracks.tracks
        ]

    def _consent_lookup(self, person_id: str) -> bool:
        if self._identity_registry is None or not person_id:
            return False
        try:
            record = self._identity_registry.lookup(person_id)
        except Exception as e:
            self.get_logger().warn(f"Consent-Abfrage fehlgeschlagen (fail-closed): {e}")
            return False
        return record is not None and record.consent_status == ConsentStatus.GRANTED.value

    def _template_candidates(self):
        """NUR Personen mit AKTUELL erteiltem Consent -- ein Widerruf
        seit dem letzten Frame wirkt sofort (Auftrag Abschnitt 7:
        "widerrufene Templates nicht weiter zum Matching laden"),
        keine zwischengespeicherte Kandidatenliste."""
        if self._biometric_store is None or self._identity_registry is None:
            return []
        candidates = []
        try:
            for person_id in self._biometric_store.all_person_ids():
                if not self._consent_lookup(person_id):
                    continue
                embedding = self._biometric_store.get_template(person_id)
                if embedding is not None:
                    candidates.append((person_id, embedding))
        except Exception as e:
            self.get_logger().warn(f"Template-Kandidaten nicht ladbar (fail-closed, leer): {e}")
            return []
        return candidates

    @staticmethod
    def _depth_patch(depth_image, depth_scale_to_m, face) -> list:
        """Reine Pixel-Extraktion (gleiches Prinzip wie
        perception_node.py::estimate_patch_depth) -- NIE ein erfundener
        Wert, nur tatsaechlich im Tiefenbild vorhandene Pixel innerhalb
        der Gesichts-Bounding-Box."""
        if depth_image is None:
            return []
        h_img, w_img = depth_image.shape[0], depth_image.shape[1]
        x0 = max(0, face.bbox_x)
        y0 = max(0, face.bbox_y)
        x1 = min(w_img, face.bbox_x + face.bbox_width)
        y1 = min(h_img, face.bbox_y + face.bbox_height)
        if x1 <= x0 or y1 <= y0:
            return []
        patch = depth_image[y0:y1, x0:x1]
        return [float(v) * depth_scale_to_m for v in patch.flatten()]

    def _on_synced(self, color_msg: Image, depth_msg: Image, info_msg: CameraInfo):
        try:
            self._process_synced(color_msg, depth_msg, info_msg)
        except Exception as e:
            # Auftrag Abschnitt 6: ein einzelner defekter Frame darf den
            # Node NICHT beenden -- geloggt, nicht propagiert.
            self.get_logger().error(f"face_identity: Frame-Verarbeitung fehlgeschlagen: {e}")

    def _process_synced(self, color_msg, depth_msg, info_msg):
        now_s = time.time()
        tracks = self._current_tracks()
        if not tracks:
            self._publish_identities([], color_msg.header)
            return

        frame_bgr = self.bridge.imgmsg_to_cv2(color_msg, desired_encoding="bgr8")
        depth_image = self.bridge.imgmsg_to_cv2(depth_msg, desired_encoding="passthrough")
        depth_scale = self.get_parameter("depth_scale_to_m").value

        faces = self._face_detector.detect(frame_bgr, now_s)
        self._progress_enrollment(tracks, faces, depth_image, depth_scale, frame_bgr)

        config = IdentityFrameConfig(
            minimum_iou=self.get_parameter("minimum_iou").value,
            ambiguity_margin=self.get_parameter("ambiguity_margin").value,
            minimum_depth_confidence=self.get_parameter("minimum_depth_confidence").value,
            minimum_track_distance_m=self.get_parameter("minimum_track_distance_m").value,
            maximum_track_distance_m=self.get_parameter("maximum_track_distance_m").value,
            minimum_liveness_valid_samples=self.get_parameter("minimum_liveness_valid_samples").value,
            minimum_liveness_depth_std_m=self.get_parameter("minimum_liveness_depth_std_m").value,
            minimum_match_similarity=self.get_parameter("minimum_match_similarity").value,
            minimum_match_margin=self.get_parameter("minimum_match_margin").value,
            result_validity_s=self.get_parameter("result_validity_s").value,
        )

        results = process_frame(
            tracks=tracks, faces=faces,
            depth_patch_fn=lambda face: self._depth_patch(depth_image, depth_scale, face),
            identity_backend=self._identity_backend, confirmer=self._confirmer,
            template_candidates_fn=self._template_candidates,
            consent_lookup_fn=self._consent_lookup,
            image=frame_bgr, now_s=now_s, config=config,
        )
        self._publish_identities(results, color_msg.header)
        self.status_pub.publish(String(
            data=f"tracks={len(tracks)} faces={len(faces)} known={sum(1 for r in results if r.known)}"
        ))

    def _publish_identities(self, results, header):
        msg = PersonIdentityArray()
        msg.header = header
        for r in results:
            identity = PersonIdentity()
            identity.header = header
            identity.track_id = r.track_id
            identity.person_id = r.person_id
            identity.display_name = ""
            # Auftrag Abschnitt 8/AP7.1.4: NIE eine Rolle aus diesem Node
            # -- siehe Moduldoku und _PLACEHOLDER_ROLE.
            identity.role = _PLACEHOLDER_ROLE
            identity.recognition_confidence = r.recognition_confidence
            identity.known = r.known
            identity.consent_granted = r.consent_granted
            identity.liveness_passed = r.liveness_passed
            identity.role_verified = False
            identity.reason = r.reason
            msg.identities.append(identity)
        self.identity_pub.publish(msg)

    # ---- Einschreibung (Entwicklungsauftrag 04-B, AP7.1, Abschnitt 7) ----

    def _progress_enrollment(self, tracks, faces, depth_image, depth_scale, image):
        """Wird aus JEDEM synchronisierten Frame aufgerufen, tut aber
        nichts, solange keine Sitzung laeuft (_on_enroll_request()
        setzt _enrollment_state). Getrennt von der normalen
        Identitaets-Pipeline (identity_frame_processor.py) -- ein
        Enrollment darf NICHT von den dortigen Distanz-/Bestaetigungs-
        Schwellen abhaengen, die fuer laufenden Betrieb, nicht fuer
        eine bewusst ausgeloeste Einschreibung gedacht sind."""
        state = self._enrollment_state
        if state is None or state.completed or state.failed:
            return
        matches = match_faces_to_tracks(
            faces, tracks,
            minimum_iou=self.get_parameter("minimum_iou").value,
            ambiguity_margin=self.get_parameter("ambiguity_margin").value,
        )
        num_visible = len(matches)
        embedding = None
        liveness_passed = False
        if num_visible == 1:
            only_match = next(iter(matches.values()))
            depth_values = self._depth_patch(depth_image, depth_scale, only_match.face)
            liveness = check_liveness(
                depth_values,
                self.get_parameter("minimum_liveness_depth_std_m").value,
                self.get_parameter("minimum_liveness_valid_samples").value,
            )
            liveness_passed = liveness.passed
            if liveness_passed:
                bbox = (only_match.face.bbox_x, only_match.face.bbox_y,
                        only_match.face.bbox_width, only_match.face.bbox_height)
                embedding_result = self._identity_backend.identify_persistent(image, bbox)
                if embedding_result.valid:
                    embedding = embedding_result.embedding
        observe_enrollment_frame(state, num_visible, liveness_passed, embedding)

    def _on_enroll_request(self, request, response):
        """Blockierender Service-Handler (Auftrag Abschnitt 7) -- laeuft
        auf einer ReentrantCallbackGroup, damit _on_synced() waehrend
        des Wartens weiter Beobachtungen sammeln kann (braucht einen
        MultiThreadedExecutor, siehe main()). Kein Enrollment automatisch
        waehrend eines normalen Gespraechs -- dieser Service ist der
        EINZIGE Ausloeser, nur ueber identityctl enroll erreichbar."""
        if self._biometric_store is None or self._identity_registry is None:
            response.success = False
            response.reason = "identitaets_speicher_nicht_verfuegbar"
            response.frames_collected = 0
            return response
        if self._enrollment_state is not None and not (
                self._enrollment_state.completed or self._enrollment_state.failed):
            response.success = False
            response.reason = "andere_einschreibung_laeuft_bereits"
            response.frames_collected = 0
            return response

        try:
            record = self._identity_registry.lookup(request.person_id)
        except Exception as e:
            response.success = False
            response.reason = f"registry_fehler:{e}"
            response.frames_collected = 0
            return response
        if record is None:
            response.success = False
            response.reason = "person_nicht_in_registry"
            response.frames_collected = 0
            return response
        if record.consent_status != ConsentStatus.GRANTED.value:
            response.success = False
            response.reason = "keine_einwilligung"
            response.frames_collected = 0
            return response

        timeout_s = request.timeout_s or self.get_parameter("enrollment_default_timeout_s").value
        self._enrollment_state = EnrollmentState(
            person_id=request.person_id,
            required_observations=self.get_parameter("enrollment_required_observations").value,
            minimum_consistency_similarity=self.get_parameter(
                "enrollment_minimum_consistency_similarity").value,
        )
        self.get_logger().info(
            f"Einschreibungssitzung fuer {request.person_id} gestartet "
            f"(Grund: {request.reason!r}, Zeitlimit {timeout_s:.1f}s)."
        )

        poll_interval = self.get_parameter("enrollment_poll_interval_s").value
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._enrollment_state.completed or self._enrollment_state.failed:
                break
            time.sleep(poll_interval)

        state = self._enrollment_state
        self._enrollment_state = None  # Sitzung in JEDEM Fall beenden

        if state.completed:
            embedding = state.final_embedding()
            try:
                self._biometric_store.store_template(request.person_id, embedding)
            except Exception as e:
                response.success = False
                response.reason = f"speichern_fehlgeschlagen:{e}"
                response.frames_collected = len(state.embeddings)
                return response
            self.get_logger().info(
                f"Einschreibung fuer {request.person_id} abgeschlossen "
                f"({len(state.embeddings)} Beobachtungen)."
            )
            response.success = True
            response.reason = ""
            response.frames_collected = len(state.embeddings)
            return response

        if state.failed:
            response.success = False
            response.reason = state.fail_reason
            response.frames_collected = len(state.embeddings)
            return response

        response.success = False
        response.reason = "zeitueberschreitung"
        response.frames_collected = len(state.embeddings)
        return response


def _build_face_detector(node):
    kind = node.get_parameter("face_detector_kind").value
    if kind == "mock":
        return MockFaceDetector()
    if kind == "local_onnx":
        try:
            return LocalOnnxFaceDetector(
                model_path=node.get_parameter("face_detector_model_path").value,
                minimum_confidence=node.get_parameter("face_detector_minimum_confidence").value,
            )
        except Exception as e:
            node.get_logger().error(
                f"LocalOnnxFaceDetector nicht verfuegbar, falle auf "
                f"DisabledFaceDetector zurueck: {e}")
            return DisabledFaceDetector()
    return DisabledFaceDetector()


def _build_identity_backend(node):
    kind = node.get_parameter("identity_backend_kind").value
    if kind == "mock":
        return MockIdentityBackend()
    if kind == "local_onnx":
        try:
            return LocalOnnxIdentityBackend(
                model_path=node.get_parameter("identity_backend_model_path").value)
        except Exception as e:
            node.get_logger().error(
                f"LocalOnnxIdentityBackend nicht verfuegbar, falle auf "
                f"DisabledIdentityBackend zurueck: {e}")
            return DisabledIdentityBackend()
    return DisabledIdentityBackend()


def main(args=None):
    rclpy.init(args=args)
    node = FaceIdentityNode()
    # MultiThreadedExecutor: der blockierende Einschreibungs-Service
    # (_on_enroll_request) muss gleichzeitig mit _on_synced() laufen
    # koennen (gleiches Prinzip wie person_approach_node.py).
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
