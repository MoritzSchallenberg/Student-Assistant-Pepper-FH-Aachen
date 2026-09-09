#!/usr/bin/env python3
"""
gesture_memory_node: duenner ROS-Wrapper um GestureIndexStore
(Ergaenzungsauftrag 04-A, Gesten-Vektordatenbank). Exponiert 2 Services
(SearchGestures, ReindexGestureDatabase) und veroeffentlicht die
Ergebnisliste jeder Suche zusaetzlich auf einem Topic (Introspektion/
Test/Debugging, RViz-freundlich als einfacher `ros2 topic echo`).

Baut den Index beim Start EINMAL automatisch auf (nicht erzwungen --
reindex(force=False) erkennt einen unveraenderten Katalog ueber den
Fingerabdruck und ueberspringt die Neuberechnung). Das deckt "nach jeder
Aenderung am Gestenkatalog neu indizieren" fuer den Normalfall
"Katalogaenderung + Neustart des Nodes" bereits ab; der explizite
ReindexGestureDatabase-Service ist fuer den Fall gedacht, dass der
Katalog sich AEHREND der Node-Laufzeit aendert (z.B. gesturectl legt
waehrend des Betriebs eine neue Geste an).

production_mode ist bewusst ein eigener Node-Parameter (nicht Teil jeder
einzelnen Anfrage) -- ein Aufrufer soll den Produktionsmodus nicht
versehentlich pro Anfrage abschalten koennen; SearchGestures.request.
production_mode existiert trotzdem separat, damit auch ein einzelner
Testlauf explizit "so als waere es Produktion" pruefen kann, OHNE den
ganzen Node umzukonfigurieren. Wirksam ist production_mode=true, sobald
IRGENDEINE der beiden Quellen es setzt (Node-Parameter ODER Anfrage) --
nie eine stille Abschwaechung in die unsichere Richtung."""
import os

import rclpy
from rclpy.node import Node

from ihk_pepper_bridge.gesture_catalog import GestureCatalog
from ihk_pepper_interfaces.msg import GestureCandidate, GestureCandidateArray
from ihk_pepper_interfaces.srv import ReindexGestureDatabase, SearchGestures

from .gesture_index_db import GestureIndexStore
from .gesture_search import GestureSearchRequest

DEFAULT_GESTURE_DB = os.path.expanduser("~/.ihk_pepper_memory/gesture_index.db")


def _default_catalog_dir() -> str:
    from ament_index_python.packages import get_package_share_directory
    return os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")


class GestureMemoryNode(Node):
    def __init__(self):
        super().__init__("gesture_memory")

        self.declare_parameter("gesture_catalog_dir", _default_catalog_dir())
        self.declare_parameter("gesture_db_path", DEFAULT_GESTURE_DB)
        self.declare_parameter("production_mode", False)

        catalog_dir = self.get_parameter("gesture_catalog_dir").value
        self.catalog = GestureCatalog(catalog_dir)
        self.store = GestureIndexStore(self.get_parameter("gesture_db_path").value)

        startup_result = self.store.reindex(self.catalog, force=False)
        self.get_logger().info(
            f"gesture_memory gestartet -- catalog_dir={catalog_dir}, "
            f"db={self.get_parameter('gesture_db_path').value}, "
            f"production_mode={self.get_parameter('production_mode').value}, "
            f"embedding_backend={self.store.embedding_backend.name}, "
            f"start_reindex={startup_result}"
        )

        self.results_pub = self.create_publisher(GestureCandidateArray, "~/last_search_results", 10)
        self.create_service(SearchGestures, "search_gestures", self._handle_search_gestures)
        self.create_service(ReindexGestureDatabase, "reindex_gesture_database", self._handle_reindex)

    def _handle_search_gestures(self, request, response):
        node_production_mode = bool(self.get_parameter("production_mode").value)
        search_request = GestureSearchRequest(
            query=request.query,
            interaction_state=request.interaction_state,
            nav2_moving=request.nav2_moving,
            mapping_active=request.mapping_active,
            # Nie unsicherer als der Node-Parameter (siehe Docstring).
            production_mode=node_production_mode or request.production_mode,
            minimum_tested_status=request.minimum_tested_status,
            max_duration_s=request.max_duration_s,
            exclude_recent=list(request.exclude_recent),
            top_k=request.top_k,
            include_system_only=request.include_system_only,
        )
        try:
            ranked = self.store.search(search_request)
        except Exception as e:
            self.get_logger().error(f"SearchGestures fehlgeschlagen: {e}")
            response.success = False
            response.message = str(e)
            response.candidates = []
            return response

        candidates = [
            GestureCandidate(
                name=entry.name, description=entry.description, score=float(score),
                tested_status=entry.tested_status, duration_s=float(entry.duration_s),
                allowed_interaction_states=list(entry.allowed_interaction_states),
                requires_stationary=entry.requires_stationary,
                affects_head=entry.affects_head,
                system_only=entry.system_only, selectable_by_llm=entry.selectable_by_llm,
            )
            for entry, score in ranked
        ]
        response.success = True
        response.message = f"{len(candidates)} Treffer"
        response.candidates = candidates

        array_msg = GestureCandidateArray()
        array_msg.header.stamp = self.get_clock().now().to_msg()
        array_msg.candidates = candidates
        self.results_pub.publish(array_msg)
        return response

    def _handle_reindex(self, request, response):
        try:
            result = self.store.reindex(self.catalog, force=request.force)
        except Exception as e:
            self.get_logger().error(f"ReindexGestureDatabase fehlgeschlagen: {e}")
            response.success = False
            response.message = str(e)
            response.indexed_count = 0
            response.skipped_count = 0
            response.embedding_backend = self.store.embedding_backend.name
            return response

        response.success = True
        response.message = "unveraendert, Reindex uebersprungen" if result["unchanged"] else "neu indiziert"
        response.indexed_count = result["indexed_count"]
        response.skipped_count = result["skipped_count"]
        response.embedding_backend = self.store.embedding_backend.name
        return response

    def destroy_node(self):
        self.store.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GestureMemoryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
