#!/usr/bin/env python3
"""
person_memory_node: duenner ROS-Wrapper um IdentityRegistryStore +
VectorMemoryStore (Entwicklungsauftrag 3, AP5/AP6). Exponiert 5
Services: LookupPerson, SetConsent, SetDisplayName, DeletePerson,
GetPersonContext.

DB-Pfad konfigurierbar, Default ausserhalb jedes Git-/Colcon-Baums
(gleiches Prinzip wie ~/.ihk_pepper_maps/ aus Entwicklungsauftrag 2) --
Datenbanken sind Laufzeitdaten, keine Quelltextartefakte.

Kein LLM ruft diese Services jemals auf -- nur ein RunDialogue-Action-
Server (menschlich/BT-ausgeloest) oder ein Test-/Bedienwerkzeug.
"""
import os

import rclpy
from rclpy.node import Node

from ihk_pepper_interfaces.srv import (
    DeletePerson,
    GetPersonContext,
    LookupPerson,
    SetConsent,
    SetDisplayName,
    WriteMemorySummary,
)

from .identity_registry_db import IdentityRegistryStore
from .vector_memory import MemoryEntry
from .vector_memory_db import VectorMemoryStore

DEFAULT_IDENTITY_DB = os.path.expanduser("~/.ihk_pepper_memory/identity.db")
DEFAULT_VECTOR_DB = os.path.expanduser("~/.ihk_pepper_memory/vector_memory.db")


class PersonMemoryNode(Node):
    def __init__(self):
        super().__init__("person_memory")

        self.declare_parameter("identity_db_path", DEFAULT_IDENTITY_DB)
        self.declare_parameter("vector_memory_db_path", DEFAULT_VECTOR_DB)

        self.identity_store = IdentityRegistryStore(
            self.get_parameter("identity_db_path").value)
        self.vector_store = VectorMemoryStore(
            self.get_parameter("vector_memory_db_path").value)

        self.create_service(LookupPerson, "lookup_person", self._handle_lookup_person)
        self.create_service(SetConsent, "set_consent", self._handle_set_consent)
        self.create_service(SetDisplayName, "set_display_name", self._handle_set_display_name)
        self.create_service(DeletePerson, "delete_person", self._handle_delete_person)
        self.create_service(GetPersonContext, "get_person_context", self._handle_get_person_context)
        self.create_service(WriteMemorySummary, "write_memory_summary", self._handle_write_memory_summary)

        self.get_logger().info(
            f"person_memory gestartet -- identity_db={self.get_parameter('identity_db_path').value}, "
            f"vector_memory_db={self.get_parameter('vector_memory_db_path').value}"
        )

    def _handle_lookup_person(self, request, response):
        record = self.identity_store.lookup(request.person_id)
        if record is None:
            response.known = False
            response.display_name = ""
            response.consent_status = ""
            response.confidence = 0.0
            response.last_seen_iso = ""
            return response
        response.known = True
        response.display_name = record.display_name or ""
        response.consent_status = record.consent_status
        response.confidence = record.confidence
        response.last_seen_iso = record.last_seen_iso or ""
        return response

    def _handle_set_consent(self, request, response):
        try:
            # Auftrag AP5 sieht bewusst KEINEN eigenen "Person anlegen"-
            # Service vor (kein LLM darf eine Person anlegen) -- die
            # allererste Konsens-Anfrage fuer eine noch unbekannte
            # person_id legt den Datensatz implizit an (mit dem sicheren
            # Default consent_status=not_asked), ausschliesslich ueber
            # diesen von einem Menschen/RunDialogue ausgeloesten Weg.
            if self.identity_store.lookup(request.person_id) is None:
                self.identity_store.create_or_touch(request.person_id, reason=request.reason)
            self.identity_store.set_consent(request.person_id, request.consent_status, request.reason)
            response.success = True
            response.message = ""
        except (ValueError, KeyError) as e:
            response.success = False
            response.message = str(e)
        return response

    def _handle_set_display_name(self, request, response):
        try:
            self.identity_store.set_display_name(request.person_id, request.display_name, request.reason)
            response.success = True
            response.message = ""
        except KeyError as e:
            response.success = False
            response.message = str(e)
        return response

    def _handle_delete_person(self, request, response):
        identity_deleted = self.identity_store.delete(request.person_id, request.reason)
        memory_deleted = self.vector_store.delete_for_person(request.person_id)
        response.success = True
        response.message = (
            f"identity_geloescht={identity_deleted}, memory_eintraege_geloescht={memory_deleted}"
        )
        return response

    def _handle_get_person_context(self, request, response):
        ctx = self.identity_store.get_context(request.person_id)
        response.known = ctx["known"]
        response.display_name = ctx["display_name"] or ""
        return response

    def _handle_write_memory_summary(self, request, response):
        """Schreibt NUR, wenn validate_memory_write() (aufgerufen ueber
        VectorMemoryStore.write_validated_summary()) keine Fehler findet
        -- insbesondere NIE ohne dokumentierte Einwilligung. KEIN
        stiller Erfolg bei Ablehnung."""
        identity = self.identity_store.lookup(request.person_id)
        entry = MemoryEntry(
            person_id=request.person_id, source=request.source, timestamp_iso="",
            topics=list(request.topics), text_summary=request.summary,
            sources=list(request.sources), valid_until_iso=request.valid_until_iso or None,
            session_id=request.session_id,
        )
        errors = self.vector_store.write_validated_summary(entry, identity)
        response.success = not errors
        response.message = "; ".join(errors)
        return response

    def destroy_node(self):
        self.identity_store.close()
        self.vector_store.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonMemoryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
