"""Kurzzeit-Gespraechsgedaechtnis pro Sitzung (Arbeitspaket 13).

Keine dauerhafte personenbezogene Zuordnung -- eine Sitzung ist rein
zeitlich/durch ENGAGED-Uebergang definiert, nicht an eine Person-ID
gebunden (das wuerde biometrische Wiedererkennung voraussetzen, die
bewusst NICHT gebaut wird, siehe Arbeitspaket 1)."""
import time
import uuid


class Session:
    def __init__(self, max_messages: int = 10):
        self.session_id = str(uuid.uuid4())
        self.max_messages = max_messages
        self.messages = []  # Liste von {"role": "user"/"assistant", "text": str, "ts": float}
        self.last_activity = time.time()

    def add(self, role: str, text: str):
        self.messages.append({"role": role, "text": text, "ts": time.time()})
        self.messages = self.messages[-self.max_messages:]
        self.last_activity = time.time()

    def is_expired(self, timeout_s: float) -> bool:
        return (time.time() - self.last_activity) > timeout_s

    def as_context_string(self) -> str:
        """Einfache Verlaufs-Repraesentation, z.B. um sie AnythingLLM als
        zusaetzlichen Kontext vor die aktuelle Frage zu haengen, damit
        Folgefragen wie 'Und wann ist das?' funktionieren."""
        lines = []
        for m in self.messages[:-1]:  # letzte (aktuelle Frage) nicht doppelt
            prefix = "Nutzer" if m["role"] == "user" else "Pepper"
            lines.append(f"{prefix}: {m['text']}")
        return "\n".join(lines)


class SessionManager:
    def __init__(self, max_messages: int = 10, timeout_s: float = 120.0):
        self.max_messages = max_messages
        self.timeout_s = timeout_s
        self._sessions: dict[str, Session] = {}
        self._active_session_id = None

    def start_session(self) -> Session:
        session = Session(max_messages=self.max_messages)
        self._sessions[session.session_id] = session
        self._active_session_id = session.session_id
        return session

    def get_active(self):
        if self._active_session_id is None:
            return None
        session = self._sessions.get(self._active_session_id)
        if session is None:
            return None
        if session.is_expired(self.timeout_s):
            self.end_active()
            return None
        return session

    def end_active(self):
        if self._active_session_id is not None:
            self._sessions.pop(self._active_session_id, None)
            self._active_session_id = None

    def cleanup_expired(self):
        expired = [sid for sid, s in self._sessions.items() if s.is_expired(self.timeout_s)]
        for sid in expired:
            self._sessions.pop(sid, None)
            if sid == self._active_session_id:
                self._active_session_id = None
