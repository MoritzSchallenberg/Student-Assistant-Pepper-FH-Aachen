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
import threading
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
        # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 9 (Kandidat A):
        # search() lud bisher bei JEDER Anfrage saemtliche Zeilen aus
        # SQLite neu und deserialisierte deren JSON-Felder erneut, auch
        # wenn sich der Index seit der letzten Anfrage nicht veraendert
        # hatte. Ein unveraenderlicher Snapshot (_cached_entries) wird
        # jetzt genau EINMAL geladen und bis zum naechsten TATSAECHLICHEN
        # reindex() (nicht dem fruehen 'unchanged'-Fingerprint-Pfad, der
        # die Daten gar nicht aendert) wiederverwendet. Harte Filter
        # (passes_hard_filters()) laufen weiterhin bei JEDER Anfrage neu
        # gegen den aktuellen Request -- nur das teure Laden/
        # Deserialisieren wird wiederverwendet, keine fertige
        # Autorisierungsentscheidung wird je gecacht.
        self._snapshot_lock = threading.Lock()
        self._cached_entries = None

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
        # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 9: Invalidierung
        # ERST nach erfolgreichem commit() -- ein zwischen DELETE und
        # commit() abgefragter Snapshot bliebe sonst der ALTE, gueltige
        # Stand (kein teilweise aufgebauter Index wird je sichtbar).
        with self._snapshot_lock:
            self._cached_entries = None
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

    def _entries_snapshot(self) -> list:
        """Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 9 (Kandidat A):
        gibt den unveraenderlichen, generationengebundenen Snapshot
        zurueck -- laedt ihn genau einmal, wenn er (noch) fehlt oder
        durch den letzten reindex() invalidiert wurde. Threadsicher
        (mehrere gleichzeitige search()-Aufrufe teilen sich denselben
        Ladevorgang, keiner baut versehentlich zweimal)."""
        with self._snapshot_lock:
            if self._cached_entries is None:
                self._cached_entries = self._load_all_entries()
            return self._cached_entries

    def search(self, request: GestureSearchRequest) -> list:
        """Gibt eine Liste von (GestureIndexEntry, score) zurueck --
        reine Delegation an gesture_search.rank_candidates() gegen den
        aktuellen Snapshot (siehe _entries_snapshot()). Harte Filter
        (passes_hard_filters(), Teil von rank_candidates()) laufen dabei
        weiterhin bei JEDER Anfrage frisch gegen den aktuellen request --
        gecacht wird ausschliesslich das teure SQL-Laden/JSON-
        Deserialisieren, nie eine fertige Auswahl-/Autorisierungs-
        entscheidung."""
        entries = self._entries_snapshot()
        return rank_candidates(entries, request, self.embedding_backend)

    def entry_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM gesture_index").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
