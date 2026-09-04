"""
Persistenter Vector-Memory-Speicher (Entwicklungsauftrag 3, AP6). SQLite,
gleiches Schema-/Verbindungsmuster wie identity_registry_db.py/
ihk_pepper_dialog/faq_cache.py. Kein ROS.

Speichert AUSSCHLIESSLICH validierte Gespraechszusammenfassungen
(validate_memory_write() aus vector_memory.py wird vor jedem Schreiben
aufgerufen, lehnt ohne passenden/eingewilligten Identity-Record ab).
NIE gespeichert: rohe LLM-Prompts/Chain-of-Thought/Bilder/Audio/
ungeprüfte Namen/rohe Gesichts-Embeddings/jede einzelne LLM-1-
Zwischenantwort -- dafuer gibt es in diesem Schema strukturell kein
Feld, `summary` ist immer eine kurze, nachtraeglich erzeugte
Zusammenfassung, nie eine rohe LLM-Ausgabe.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .embedding_backend import create_embedding_backend, normalize_text
from .identity_registry import IdentityRecord
from .vector_memory import MemoryEntry, validate_memory_write

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    session_id TEXT,
    source TEXT,
    timestamp REAL NOT NULL,
    topics TEXT NOT NULL,
    summary TEXT NOT NULL,
    sources TEXT,
    valid_until REAL,
    embedding_ref TEXT,
    embedding BLOB,
    consent_status_at_write TEXT NOT NULL
);
"""


def _iso_to_unix(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    return time.mktime(time.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ"))


class VectorMemoryStore:
    def __init__(self, db_path: str, embedding_backend=None):
        resolved = Path(db_path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(resolved)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.embedding_backend = embedding_backend or create_embedding_backend()

    def write_validated_summary(self, entry: MemoryEntry, identity: Optional[IdentityRecord]) -> list:
        """Gibt eine Liste von Fehlermeldungen zurueck -- leer = erfolgreich
        geschrieben. Schreibt NICHTS, wenn validate_memory_write() auch
        nur einen Fehler findet."""
        errors = validate_memory_write(entry, identity)
        if errors:
            return errors

        embedding = None
        if entry.text_summary:
            raw = self.embedding_backend.encode(entry.text_summary)
            embedding = raw.tolist() if hasattr(raw, "tolist") else raw

        self.conn.execute(
            "INSERT INTO memory_entries (person_id, session_id, source, timestamp, "
            "topics, summary, sources, valid_until, embedding_ref, embedding, "
            "consent_status_at_write) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry.person_id, entry.session_id, entry.source, time.time(),
                json.dumps(entry.topics), entry.text_summary, json.dumps(entry.sources),
                _iso_to_unix(entry.valid_until_iso), entry.embedding_ref,
                json.dumps(embedding), identity.consent_status,
            ),
        )
        self.conn.commit()
        return []

    def query_by_topic(self, person_id: str, topic: str) -> list:
        """Nur nicht abgelaufene Eintraege DERSELBEN person_id --
        niemals Ergebnisse einer fremden Person."""
        now = time.time()
        rows = self.conn.execute(
            "SELECT topics, summary, sources FROM memory_entries WHERE person_id = ? "
            "AND (valid_until IS NULL OR valid_until >= ?)",
            (person_id, now),
        ).fetchall()
        results = []
        normalized_topic = normalize_text(topic)
        for row_topics, summary, sources in rows:
            topics = json.loads(row_topics)
            if any(normalize_text(t) == normalized_topic for t in topics):
                results.append({
                    "topic": topic, "summary": summary,
                    "sources": json.loads(sources) if sources else [], "confidence": 1.0,
                })
        return results

    def query_semantic(self, person_id: str, text: str, threshold: float = 0.6) -> list:
        """Fällt ohne Embedding-Modell auf normalisierten
        Schluesselwort-/Textvergleich zurueck (DifflibFallbackBackend) --
        niemals Ergebnisse einer fremden person_id."""
        now = time.time()
        rows = self.conn.execute(
            "SELECT topics, summary, sources FROM memory_entries WHERE person_id = ? "
            "AND (valid_until IS NULL OR valid_until >= ?) AND summary != ''",
            (person_id, now),
        ).fetchall()
        query_emb = self.embedding_backend.encode(text)
        best = []
        for row_topics, summary, sources in rows:
            candidate_emb = self.embedding_backend.encode(summary)
            score = self.embedding_backend.similarity(query_emb, candidate_emb)
            if score >= threshold:
                topics = json.loads(row_topics)
                best.append({
                    "topic": topics[0] if topics else "", "summary": summary,
                    "sources": json.loads(sources) if sources else [], "confidence": score,
                })
        best.sort(key=lambda r: r["confidence"], reverse=True)
        return best

    def delete_for_person(self, person_id: str) -> int:
        cur = self.conn.execute("DELETE FROM memory_entries WHERE person_id = ?", (person_id,))
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()
