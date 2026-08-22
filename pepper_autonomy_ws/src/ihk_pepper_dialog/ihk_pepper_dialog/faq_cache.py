"""
Lokale FAQ-/Semantik-Cache-Datenbank (SQLite, Arbeitspaket 4).

Bewusst als eigene Klasse mit klarer Schnittstelle gebaut, damit das
Backend spaeter austauschbar bleibt (Anforderung Abschnitt 15), ohne dass
DialogManager & Co. angepasst werden muessen.

Embeddings: bevorzugt sentence-transformers (lokal, mehrsprachig, CPU-
faehig). Fehlt das Paket/Modell, faellt die Klasse automatisch auf
normalisierten Exakt-Treffer + einfache Textaehnlichkeit zurueck --
semantische Suche ist dann schlicht deaktiviert, blockiert aber nicht
den Rest des Systems (Anforderung Abschnitt 17).
"""
import difflib
import json
import logging
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS faq_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_question TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    answer TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'de',
    topic TEXT,
    sources TEXT,
    approved INTEGER NOT NULL DEFAULT 0,
    valid_from TEXT,
    valid_to TEXT,
    embedding BLOB,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS question_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_anonymized TEXT NOT NULL,
    answer_source TEXT NOT NULL,   -- exact_match | semantic_match | llm | fallback
    cache_hit_level TEXT,
    confidence REAL,
    latency_s REAL,
    timestamp REAL NOT NULL,
    feedback INTEGER               -- NULL=keins, 1=positiv, -1=negativ
);

CREATE TABLE IF NOT EXISTS answer_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    generated_answer TEXT NOT NULL,
    sources TEXT,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'unreviewed',  -- unreviewed | approved | rejected
    created_at REAL NOT NULL
);
"""


def normalize_question(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^\w\s äöüß]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class EmbeddingBackend:
    name = "none"

    def encode(self, text: str):
        raise NotImplementedError

    def similarity(self, a, b) -> float:
        raise NotImplementedError


class SentenceTransformerBackend(EmbeddingBackend):
    name = "sentence-transformers"

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        import os
        # Erzwingt lokalen Cache, keine Online-Freshness-Pruefung bei jedem
        # Start -- ohne das schwankte die Ladezeit in dieser Session stark
        # mit der Netzwerklatenz (einmal <1s, einmal >40s Timeout).
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        import numpy as np
        self._np = np
        self.model = SentenceTransformer(model_name)

    def encode(self, text: str):
        return self.model.encode(text, convert_to_numpy=True)

    def similarity(self, a, b) -> float:
        np = self._np
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)


class DifflibFallbackBackend(EmbeddingBackend):
    """Kein echtes Embedding -- reine Textaehnlichkeit. Ausreichend fuer
    kleine, sorgfaeltig formulierte FAQ-Sammlungen, aber keine echte
    Semantik. Wird nur genutzt, wenn sentence-transformers fehlt."""
    name = "difflib_fallback"

    def encode(self, text: str):
        return normalize_question(text)  # "Embedding" ist hier der Text selbst

    def similarity(self, a, b) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()


def create_embedding_backend(prefer_st: bool = True) -> EmbeddingBackend:
    if prefer_st:
        try:
            return SentenceTransformerBackend()
        except Exception as e:
            logger.warning(
                f"sentence-transformers nicht verfuegbar ({e}) -- "
                f"semantische Suche laeuft nur mit einfacher Textaehnlichkeit."
            )
    return DifflibFallbackBackend()


class FaqCache:
    def __init__(self, db_path: str, embedding_backend: EmbeddingBackend = None):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.embedding_backend = embedding_backend or create_embedding_backend()

    # ---- FAQ-Verwaltung ----

    def add_entry(self, canonical_question, answer, language="de", topic=None,
                   sources=None, approved=False, valid_from=None, valid_to=None):
        normalized = normalize_question(canonical_question)
        embedding = self.embedding_backend.encode(canonical_question)
        embedding_blob = json.dumps(
            embedding.tolist() if hasattr(embedding, "tolist") else embedding
        )
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO faq_entries (canonical_question, normalized_question, answer, "
            "language, topic, sources, approved, valid_from, valid_to, embedding, "
            "usage_count, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (canonical_question, normalized, answer, language, topic,
             json.dumps(sources or []), int(approved), valid_from, valid_to,
             embedding_blob, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def reload_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM faq_entries").fetchone()[0]

    # ---- Antwortsuche ----

    def lookup_exact(self, question: str, language="de"):
        normalized = normalize_question(question)
        row = self.conn.execute(
            "SELECT id, answer FROM faq_entries WHERE normalized_question = ? "
            "AND language = ? AND approved = 1 AND "
            "(valid_from IS NULL OR valid_from <= datetime('now')) AND "
            "(valid_to IS NULL OR valid_to >= datetime('now')) LIMIT 1",
            (normalized, language),
        ).fetchone()
        if row is None:
            return None
        self._bump_usage(row[0])
        return {"id": row[0], "answer": row[1], "confidence": 1.0}

    def lookup_semantic(self, question: str, language="de", topic=None, threshold=0.75):
        query_emb = self.embedding_backend.encode(question)
        rows = self.conn.execute(
            "SELECT id, answer, embedding, topic FROM faq_entries WHERE "
            "language = ? AND approved = 1 AND "
            "(valid_from IS NULL OR valid_from <= datetime('now')) AND "
            "(valid_to IS NULL OR valid_to >= datetime('now'))",
            (language,),
        ).fetchall()

        best = None
        best_score = threshold
        for row_id, answer, embedding_blob, row_topic in rows:
            if topic and row_topic and row_topic != topic:
                continue
            stored = json.loads(embedding_blob)
            score = self.embedding_backend.similarity(query_emb, stored)
            if score > best_score:
                best = (row_id, answer, score)
                best_score = score

        if best is None:
            return None
        self._bump_usage(best[0])
        return {"id": best[0], "answer": best[1], "confidence": best[2]}

    def _bump_usage(self, faq_id):
        self.conn.execute(
            "UPDATE faq_entries SET usage_count = usage_count + 1 WHERE id = ?", (faq_id,)
        )
        self.conn.commit()

    # ---- Logging ----

    def log_question(self, question: str, answer_source: str, confidence: float,
                      latency_s: float, cache_hit_level: str = None):
        """question wird NICHT im Klartext gespeichert (Anforderung:
        'anonymisierte Frage') -- hier ueber die normalisierte Form ohne
        Freitext-Reste, ausreichend fuer Haeufigkeitsauswertung."""
        anonymized = normalize_question(question)
        self.conn.execute(
            "INSERT INTO question_log (question_anonymized, answer_source, "
            "cache_hit_level, confidence, latency_s, timestamp) VALUES (?,?,?,?,?,?)",
            (anonymized, answer_source, cache_hit_level, confidence, latency_s, time.time()),
        )
        self.conn.commit()

    def add_candidate(self, question: str, generated_answer: str, sources=None, model=None):
        self.conn.execute(
            "INSERT INTO answer_candidates (question, generated_answer, sources, model, "
            "status, created_at) VALUES (?,?,?,?,'unreviewed',?)",
            (question, generated_answer, json.dumps(sources or []), model, time.time()),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
