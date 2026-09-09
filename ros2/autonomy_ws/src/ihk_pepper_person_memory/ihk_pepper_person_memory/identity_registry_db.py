"""
Persistenter Identity-Registry-Speicher (Entwicklungsauftrag 3, AP5).
SQLite, Schema-/Verbindungsmuster angelehnt an
ihk_pepper_dialog/faq_cache.py (executescript(SCHEMA), Path(...).mkdir).
Kein ROS -- person_memory_node.py ist der duenne ROS-Wrapper darum.

ByteTrack-track_id und person_id werden STRIKT getrennt: diese Klasse
weiss nichts von Tracks, nimmt ausschliesslich bereits entschiedene
person_id-Werte entgegen (von Tests oder spaeter einem echten, in
diesem Auftrag noch nicht gebauten Erkennungsdienst). Ohne bestaetigte
Identitaet bleibt eine Person unbekannt -- lookup() liefert dann None,
niemals eine geratene/teilweise Identitaet.

Kein Gesichtsbild-/Embedding-Feld in diesem Schema (Auftrag-Vorgabe --
das gehoert nicht in diese Datenbank). Jede Schreiboperation verlangt
einen `reason`-String, protokolliert in identity_audit_log (append-only).

Entwicklungsauftrag 04-B, AP7, Abschnitt 6: um role/role_assigned_at/
role_assigned_by/role_valid_until erweitert -- migrationsfaehig
(_migrate_add_role_columns() erstellt VOR jeder Schemaaenderung an einer
bereits befuellten Datenbank eine Sicherungskopie, siehe dort). set_role()/
revoke_role() sind die EINZIGEN Schreibpfade fuer die Rolle -- KEIN
ROS2-Service ruft sie auf (siehe person_memory_node.py: keine neue
SetRole-Service-Registrierung), nur peoplectl (lokales CLI-Werkzeug,
siehe docs/PERSON_ROLES_AND_AUTHORIZATION.md).
"""
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

from ihk_pepper_interaction.roles import ROLE_STUDENT, VALID_ROLES

from .identity_registry import ConsentStatus, IdentityRecord, effective_role

SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
    person_id TEXT PRIMARY KEY,
    display_name TEXT,
    consent_status TEXT NOT NULL DEFAULT 'not_asked',
    created_at REAL NOT NULL,
    last_seen_at REAL,
    last_recognition_confidence REAL NOT NULL DEFAULT 0.0,
    retention_deadline REAL
);

CREATE TABLE IF NOT EXISTS identity_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    timestamp REAL NOT NULL
);
"""

VALID_CONSENT_VALUES = frozenset(c.value for c in ConsentStatus)
DEFAULT_RETENTION_DAYS = 180.0

# Entwicklungsauftrag 04-B, AP7, Abschnitt 6: neue Spalten fuer die
# migrationsfaehige Schemaaktualisierung -- (Name, SQL-Typ-mit-Default).
_ROLE_COLUMNS = (
    ("role", f"TEXT NOT NULL DEFAULT '{ROLE_STUDENT}'"),
    ("role_assigned_at", "REAL"),
    ("role_assigned_by", "TEXT"),
    ("role_valid_until", "REAL"),
)


def _iso_or_none(unix_ts) -> Optional[str]:
    if unix_ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(unix_ts))


class IdentityRegistryStore:
    def __init__(self, db_path: str, retention_days: float = DEFAULT_RETENTION_DAYS):
        resolved = Path(db_path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(resolved)
        self.retention_days = retention_days
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate_add_role_columns()

    def _migrate_add_role_columns(self) -> None:
        """Idempotent -- laeuft bei JEDEM Start, tut aber nur beim ersten
        Mal tatsaechlich etwas. Erstellt VOR jeder Aenderung an einer
        bereits befuellten Tabelle eine Sicherungskopie der Datenbankdatei
        (Auftrag Abschnitt 6: "Vor der Migration muss eine Datenbank-
        sicherung erzeugt werden") -- bei einer frischen, leeren
        Datenbank entfaellt das (nichts zu schuetzen, keine unnoetigen
        Backup-Dateien fuer jeden frischen Testlauf)."""
        existing_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(identities)").fetchall()
        }
        missing = [(name, sql_type) for name, sql_type in _ROLE_COLUMNS
                   if name not in existing_columns]
        if not missing:
            return

        row_count = self.conn.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
        if row_count > 0:
            self._backup_before_migration()

        for name, sql_type in missing:
            self.conn.execute(f"ALTER TABLE identities ADD COLUMN {name} {sql_type}")
        self.conn.commit()

    def _backup_before_migration(self) -> str:
        backup_path = f"{self.db_path}.pre-role-migration-{int(time.time())}.bak"
        self.conn.commit()
        shutil.copy2(self.db_path, backup_path)
        return backup_path

    def _audit(self, person_id: str, action: str, reason: str) -> None:
        if not reason:
            raise ValueError("jede Schreiboperation braucht einen reason")
        self.conn.execute(
            "INSERT INTO identity_audit_log (person_id, action, reason, timestamp) "
            "VALUES (?,?,?,?)",
            (person_id, action, reason, time.time()),
        )
        self.conn.commit()

    def lookup(self, person_id: str) -> Optional[IdentityRecord]:
        row = self.conn.execute(
            "SELECT person_id, display_name, consent_status, last_seen_at, "
            "retention_deadline, last_recognition_confidence, role, "
            "role_assigned_at, role_assigned_by, role_valid_until FROM identities "
            "WHERE person_id = ?", (person_id,),
        ).fetchone()
        if row is None:
            return None
        return IdentityRecord(
            person_id=row[0], display_name=row[1], consent_status=row[2],
            last_seen_iso=_iso_or_none(row[3]), retention_deadline_iso=_iso_or_none(row[4]),
            confidence=row[5], role=row[6], role_assigned_at_iso=_iso_or_none(row[7]),
            role_assigned_by=row[8], role_valid_until_iso=_iso_or_none(row[9]),
        )

    def create_or_touch(self, person_id: str, confidence: float = 0.0,
                         reason: str = "recognition_update") -> IdentityRecord:
        """Legt einen neuen Datensatz an (consent_status=not_asked,
        sicherer Default) oder aktualisiert last_seen_at/confidence eines
        bestehenden. Erzeugt NIE selbst eine Einwilligung."""
        now = time.time()
        existing = self.conn.execute(
            "SELECT person_id FROM identities WHERE person_id=?", (person_id,)
        ).fetchone()
        if existing is None:
            retention_deadline = now + self.retention_days * 86400.0
            self.conn.execute(
                "INSERT INTO identities (person_id, consent_status, created_at, "
                "last_seen_at, last_recognition_confidence, retention_deadline) "
                "VALUES (?,?,?,?,?,?)",
                (person_id, ConsentStatus.NOT_ASKED.value, now, now, confidence, retention_deadline),
            )
            self._audit(person_id, "create", reason)
        else:
            self.conn.execute(
                "UPDATE identities SET last_seen_at=?, last_recognition_confidence=? "
                "WHERE person_id=?",
                (now, confidence, person_id),
            )
            self._audit(person_id, "touch", reason)
        return self.lookup(person_id)

    def set_consent(self, person_id: str, status: str, reason: str) -> IdentityRecord:
        if status not in VALID_CONSENT_VALUES:
            raise ValueError(f"ungueltiger consent_status: {status!r}")
        if self.lookup(person_id) is None:
            raise KeyError(f"unbekannte person_id: {person_id!r}")
        self.conn.execute(
            "UPDATE identities SET consent_status=? WHERE person_id=?", (status, person_id)
        )
        self._audit(person_id, f"set_consent:{status}", reason)
        return self.lookup(person_id)

    def set_display_name(self, person_id: str, display_name: Optional[str], reason: str) -> IdentityRecord:
        if self.lookup(person_id) is None:
            raise KeyError(f"unbekannte person_id: {person_id!r}")
        self.conn.execute(
            "UPDATE identities SET display_name=? WHERE person_id=?", (display_name, person_id)
        )
        self._audit(person_id, "set_display_name", reason)
        return self.lookup(person_id)

    # ---- Rollen (Entwicklungsauftrag 04-B, AP7, Abschnitt 6) ----
    # NUR von peoplectl aufgerufen -- KEIN ROS2-Service exponiert diese
    # Methoden (siehe person_memory_node.py), kein LLM kann sie erreichen.

    def set_role(self, person_id: str, role: str, assigned_by: str, reason: str,
                 valid_until_ts: Optional[float] = None) -> IdentityRecord:
        if role not in VALID_ROLES:
            raise ValueError(f"ungueltige Rolle: {role!r}")
        if self.lookup(person_id) is None:
            raise KeyError(f"unbekannte person_id: {person_id!r}")
        now = time.time()
        self.conn.execute(
            "UPDATE identities SET role=?, role_assigned_at=?, role_assigned_by=?, "
            "role_valid_until=? WHERE person_id=?",
            (role, now, assigned_by, valid_until_ts, person_id),
        )
        self._audit(person_id, f"set_role:{role}", reason)
        return self.lookup(person_id)

    def revoke_role(self, person_id: str, assigned_by: str, reason: str) -> IdentityRecord:
        """Setzt die Rolle explizit zurueck auf ROLE_STUDENT (Auftrag:
        "peoplectl revoke-role") -- kein Loeschen des Datensatzes selbst."""
        return self.set_role(person_id, ROLE_STUDENT, assigned_by, reason, valid_until_ts=None)

    def get_effective_role(self, person_id: str, now: Optional[float] = None) -> str:
        """Wendet effective_role() (Ablauf-Regel) auf den ROH
        gespeicherten Wert an -- IMMER ROLE_STUDENT fuer eine unbekannte
        person_id (kein Datensatz = keine erworbene Rolle)."""
        now = time.time() if now is None else now
        row = self.conn.execute(
            "SELECT role, role_valid_until FROM identities WHERE person_id=?", (person_id,),
        ).fetchone()
        if row is None:
            return ROLE_STUDENT
        return effective_role(row[0], row[1], now)

    def delete(self, person_id: str, reason: str) -> bool:
        """Echtes Loeschen der Zeile (kein blosses Flag) -- entspricht
        "Loeschung muss moeglich sein". Der Audit-Log-Eintrag selbst
        bleibt (enthaelt nur person_id+Grund+Zeitstempel, kein weiterer
        Personenbezug) -- er dokumentiert, DASS geloescht wurde."""
        cur = self.conn.execute("DELETE FROM identities WHERE person_id=?", (person_id,))
        self._audit(person_id, "delete", reason)
        return cur.rowcount > 0

    def list_all(self):
        """Fuer peoplectl list -- alle bekannten Identitaeten, sortiert
        nach person_id. Kein Filterkriterium (peoplectl selbst
        entscheidet, was angezeigt wird)."""
        rows = self.conn.execute("SELECT person_id FROM identities ORDER BY person_id").fetchall()
        return [self.lookup(row[0]) for row in rows]

    def audit_log_for(self, person_id: str):
        """Fuer peoplectl show -- alle Audit-Eintraege EINER Person,
        chronologisch. Liefert Tupel (action, reason, timestamp)."""
        return self.conn.execute(
            "SELECT action, reason, timestamp FROM identity_audit_log "
            "WHERE person_id=? ORDER BY timestamp", (person_id,),
        ).fetchall()

    def get_context(self, person_id: str) -> dict:
        """Liefert den Personenkontext im von retriever.py erwarteten
        dict-Format. NUR bei consent_status=granted gilt die Person als
        'known' -- ohne Einwilligung bleibt sie strukturell unbekannt,
        selbst wenn ein Datensatz existiert."""
        record = self.lookup(person_id)
        if record is None or record.consent_status != ConsentStatus.GRANTED.value:
            return {"known": False, "display_name": None, "person_id": None}
        return {"known": True, "display_name": record.display_name, "person_id": person_id}

    def close(self) -> None:
        self.conn.close()
