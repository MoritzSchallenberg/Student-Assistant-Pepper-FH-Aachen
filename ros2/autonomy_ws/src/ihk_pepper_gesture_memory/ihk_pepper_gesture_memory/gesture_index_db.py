"""
Persistenter Gesten-Suchindex (Ergaenzungsauftrag 04-A). SQLite, gleiches
Schema-/Verbindungsmuster wie ihk_pepper_person_memory/vector_memory_db.py.
Kein ROS.

reindex() baut den Index DETERMINISTISCH aus dem bestehenden
YAML-Gestenkatalog (ihk_pepper_bridge.gesture_catalog.GestureCatalog)
neu auf -- dieselbe validierte Gesture-Klasse wie beim echten Abspielen,
keine zweite, potenziell abweichende YAML-Parsing-Implementierung.
Fehlerhafte YAML-Dateien werden (wie in GestureCatalog.reload()) mit
Fehlermeldung uebersprungen statt den gesamten Reindex-Vorgang
abzubrechen.

Entwicklungsauftrag 04-B, AP8 (11/14): system_only/selectable_by_llm/
semantic_tags sind jetzt ECHTE, validierte Gesture-Attribute (kanonische
Top-Level-YAML-Felder, siehe gesture_catalog.py::Gesture) -- der frueher
noetige Fallback auf gesture.metadata (das freie dict-Feld) entfaellt
hier, weil Gesture.__init__ diesen Fallback bereits SELBST auflest
(_resolve_legacy_bool_field()) und IMMER ein echtes bool-Attribut liefert.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .embedding_backend import create_embedding_backend
from .gesture_search import GestureIndexEntry, GestureSearchRequest, rank_candidates

SCHEMA = """
CREATE TABLE IF NOT EXISTS gesture_index (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    tested_status TEXT NOT NULL,
    duration_s REAL NOT NULL,
    allowed_interaction_states TEXT NOT NULL,
    requires_stationary INTEGER NOT NULL,
    affects_head INTEGER NOT NULL,
    system_only INTEGER NOT NULL,
    selectable_by_llm INTEGER NOT NULL,
    semantic_tags TEXT NOT NULL,
    embedding TEXT,
    source_path TEXT NOT NULL,
    source_mtime REAL NOT NULL,
    indexed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS gesture_index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _catalog_fingerprint(catalog) -> str:
    """Deterministischer Fingerabdruck aus (Name, Dateiaenderungszeit)
    aller aktuell geladenen Gesten -- reindex(force=False) ueberspringt
    die (bei sentence-transformers nicht ganz billige) Neuberechnung
    aller Embeddings, wenn sich seit dem letzten Reindex nachweislich
    nichts geaendert hat."""
    parts = []
    for name in catalog.names():
        gesture = catalog.get(name)
        try:
            mtime = Path(gesture.source_path).stat().st_mtime
        except OSError:
            mtime = 0.0
        parts.append(f"{name}:{mtime}")
    return "|".join(sorted(parts))


class GestureIndexStore:
    def __init__(self, db_path: str, embedding_backend=None):
        resolved = Path(db_path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(resolved)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self._migrate_schema()
        self.conn.commit()
        self.embedding_backend = embedding_backend or create_embedding_backend()

    def _migrate_schema(self) -> None:
        """Entwicklungsauftrag 04-B, AP8 (11/14): 'CREATE TABLE IF NOT
        EXISTS' legt KEINE fehlende Spalte in einer bereits bestehenden
        Datei nach -- eine aeltere gesture_index.db (ohne semantic_tags,
        aus einer frueheren Session) wuerde reindex() sonst mit einem
        sqlite3.OperationalError abbrechen. Fuegt die Spalte nach, falls
        sie fehlt (bestehende Zeilen bekommen automatisch NULL -->
        '[]' beim naechsten reindex() ohnehin ueberschrieben)."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(gesture_index)")}
        if "semantic_tags" not in columns:
            self.conn.execute(
                "ALTER TABLE gesture_index ADD COLUMN semantic_tags TEXT NOT NULL DEFAULT '[]'"
            )

    def reindex(self, catalog, force: bool = False) -> dict:
        """Baut den Index komplett neu auf (kein inkrementelles Patchen
        einzelner Zeilen -- ein deterministischer Neuaufbau ist einfacher
        korrekt zu halten als ein Diff-Update, und der Katalog ist klein
        genug, dass das nicht ins Gewicht faellt). Gibt
        {"indexed_count", "skipped_count", "unchanged"} zurueck."""
        reload_errors = catalog.reload()
        fingerprint = _catalog_fingerprint(catalog)

        if not force:
            row = self.conn.execute(
                "SELECT value FROM gesture_index_meta WHERE key = 'fingerprint'"
            ).fetchone()
            if row is not None and row[0] == fingerprint:
                current_count = self.conn.execute(
                    "SELECT COUNT(*) FROM gesture_index"
                ).fetchone()[0]
                return {
                    "indexed_count": current_count,
                    "skipped_count": len(reload_errors),
                    "unchanged": True,
                }

        now = time.time()
        self.conn.execute("DELETE FROM gesture_index")
        indexed = 0
        for name in catalog.names():
            gesture = catalog.get(name)
            # Entwicklungsauftrag 04-B, AP8 (11/14), Abschnitt 8: semantic_tags
            # fliessen jetzt in den Suchtext ein -- test_note/Keyframes/
            # technische Migrationshistorien BEWUSST NICHT (die stehen nur
            # in gesture.test_note bzw. gesture.keyframes, werden hier nie
            # gelesen).
            text_for_embedding = (
                f"{gesture.name} {gesture.description} {' '.join(gesture.semantic_tags)}"
            ).strip()
            raw_embedding = self.embedding_backend.encode(text_for_embedding)
            embedding = raw_embedding.tolist() if hasattr(raw_embedding, "tolist") else raw_embedding

            try:
                mtime = Path(gesture.source_path).stat().st_mtime
            except OSError:
                mtime = 0.0

            self.conn.execute(
                "INSERT INTO gesture_index (name, description, tested_status, duration_s, "
                "allowed_interaction_states, requires_stationary, affects_head, system_only, "
                "selectable_by_llm, semantic_tags, embedding, source_path, source_mtime, indexed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gesture.name, gesture.description, gesture.tested_status, gesture.duration_s(),
                    json.dumps(gesture.allowed_interaction_states), int(gesture.requires_stationary),
                    int(gesture.affects_head()),
                    int(gesture.system_only), int(gesture.selectable_by_llm),
                    json.dumps(gesture.semantic_tags),
                    json.dumps(embedding), gesture.source_path, mtime, now,
                ),
            )
            indexed += 1

        self.conn.execute(
            "INSERT INTO gesture_index_meta (key, value) VALUES ('fingerprint', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (fingerprint,),
        )
        self.conn.commit()
        return {
            "indexed_count": indexed,
            "skipped_count": len(reload_errors),
            "unchanged": False,
        }

    def _load_all_entries(self) -> list:
        rows = self.conn.execute(
            "SELECT name, description, tested_status, duration_s, allowed_interaction_states, "
            "requires_stationary, affects_head, system_only, selectable_by_llm, semantic_tags, "
            "embedding FROM gesture_index"
        ).fetchall()
        entries = []
        for (name, description, tested_status, duration_s, states_json, requires_stationary,
                affects_head, system_only, selectable_by_llm, tags_json, embedding_json) in rows:
            entries.append(GestureIndexEntry(
                name=name, description=description, tested_status=tested_status,
                duration_s=duration_s, allowed_interaction_states=json.loads(states_json),
                requires_stationary=bool(requires_stationary), affects_head=bool(affects_head),
                system_only=bool(system_only), selectable_by_llm=bool(selectable_by_llm),
                semantic_tags=json.loads(tags_json) if tags_json else [],
                embedding=json.loads(embedding_json) if embedding_json else None,
            ))
        return entries

    def search(self, request: GestureSearchRequest) -> list:
        """Gibt eine Liste von (GestureIndexEntry, score) zurueck --
        reine Delegation an gesture_search.rank_candidates() nach dem
        Laden aller Zeilen (der Katalog ist klein, kein Grund fuer eine
        eigene SQL-Aehnlichkeitssuche)."""
        entries = self._load_all_entries()
        return rank_candidates(entries, request, self.embedding_backend)

    def entry_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM gesture_index").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
