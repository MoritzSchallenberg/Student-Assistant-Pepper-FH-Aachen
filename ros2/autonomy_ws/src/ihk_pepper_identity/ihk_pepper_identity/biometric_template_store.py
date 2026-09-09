"""
Getrennte, geschuetzte Ablage fuer biometrische Vorlagen
(Entwicklungsauftrag 04-B, AP7, Abschnitt 7). Biometrische Templates
gehoeren AUSDRUECKLICH NICHT in die bestehende Identity-Datenbank
(identity_registry_db.py) -- eigene Datei, eigenes Schema, eigene
Verschluesselung.

Anforderungen aus dem Auftrag, alle hier durchgesetzt:
    - Dateirechte 0600 (Datenbankdatei UND Schluesseldatei)
    - Verschluesselung im Ruhezustand (Fernet/AES128-CBC+HMAC, siehe
      cryptography-Bibliothek, bereits Projektabhaengigkeit)
    - Referenz ausschliesslich ueber person_id (NIE track_id -- diese
      Trennung ist Auftrag-weit etabliert, siehe identity_registry.py)
    - Loeschfunktion (delete_template())
    - Aufbewahrungsfrist (retention_days, purge_expired())
    - kein Export in Logs -- dieses Modul hat KEINEN Logger, gibt
      niemals Klartext-Embeddings zurueck ausser an den direkten
      Aufrufer von get_template()
    - keine Ablage in der Vektordatenbank -- strukturell getrennt,
      kein Importpfad zu vector_memory_db.py
    - keine Weitergabe an die LLM-Pipeline -- kein Importpfad zu
      ihk_pepper_llm_contracts

Widerrufener Consent MUSS das Template loeschen -- das ist Aufgabe des
AUFRUFERS (z.B. der set_consent-Service-Handler in person_memory_node.py
oder ein spaeterer Identity-Node), diese Klasse stellt nur delete_template()
bereit, ruft es nicht von selbst auf (kein Wissen ueber Consent-Zustand
in diesem Modul)."""
from __future__ import annotations

import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_BIOMETRIC_DB_PATH = "/var/lib/ihk-pepper/identity/biometric_templates.db"
DEFAULT_RETENTION_DAYS = 180.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS biometric_templates (
    person_id TEXT PRIMARY KEY,
    encrypted_embedding BLOB NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    retention_deadline REAL NOT NULL
);
"""


class BiometricTemplateStore:
    def __init__(self, db_path: str = DEFAULT_BIOMETRIC_DB_PATH, key_path: Optional[str] = None,
                 retention_days: float = DEFAULT_RETENTION_DAYS):
        resolved = Path(db_path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(resolved)
        self.retention_days = retention_days
        self._key_path = key_path or f"{self.db_path}.key"
        self._fernet = Fernet(self._load_or_create_key())
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._restrict_permissions(self.db_path)

    def _load_or_create_key(self) -> bytes:
        key_file = Path(self._key_path)
        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.write_bytes(key)
        self._restrict_permissions(str(key_file))
        return key

    @staticmethod
    def _restrict_permissions(path: str) -> None:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # z.B. Dateisystem ohne Unix-Rechte -- best effort, kein Absturz

    def store_template(self, person_id: str, embedding: bytes) -> None:
        if not person_id:
            raise ValueError("person_id darf nicht leer sein")
        encrypted = self._fernet.encrypt(embedding)
        now = time.time()
        deadline = now + self.retention_days * 86400.0
        existing = self.conn.execute(
            "SELECT person_id FROM biometric_templates WHERE person_id=?", (person_id,)
        ).fetchone()
        if existing is None:
            self.conn.execute(
                "INSERT INTO biometric_templates (person_id, encrypted_embedding, "
                "created_at, updated_at, retention_deadline) VALUES (?,?,?,?,?)",
                (person_id, encrypted, now, now, deadline),
            )
        else:
            self.conn.execute(
                "UPDATE biometric_templates SET encrypted_embedding=?, updated_at=?, "
                "retention_deadline=? WHERE person_id=?",
                (encrypted, now, deadline, person_id),
            )
        self.conn.commit()

    def get_template(self, person_id: str, now: Optional[float] = None) -> Optional[bytes]:
        """None bei fehlendem, abgelaufenem, oder nicht entschluesselbarem
        Eintrag -- NIE ein erratenes/leeres Ersatz-Embedding."""
        now = time.time() if now is None else now
        row = self.conn.execute(
            "SELECT encrypted_embedding, retention_deadline FROM biometric_templates "
            "WHERE person_id=?", (person_id,),
        ).fetchone()
        if row is None:
            return None
        encrypted, deadline = row
        if now > deadline:
            return None
        try:
            return self._fernet.decrypt(encrypted)
        except InvalidToken:
            return None

    def has_template(self, person_id: str, now: Optional[float] = None) -> bool:
        return self.get_template(person_id, now=now) is not None

    def delete_template(self, person_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM biometric_templates WHERE person_id=?", (person_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def purge_expired(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        cur = self.conn.execute("DELETE FROM biometric_templates WHERE retention_deadline < ?", (now,))
        self.conn.commit()
        return cur.rowcount

    def all_person_ids(self):
        return [row[0] for row in self.conn.execute(
            "SELECT person_id FROM biometric_templates").fetchall()]

    def close(self) -> None:
        self.conn.close()
