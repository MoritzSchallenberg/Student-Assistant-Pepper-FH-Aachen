"""Kontinuierlicher Ringpuffer fuer 16kHz-Mono-int16-PCM, mit Vorlaufzeit
(pre-roll), damit Wortanfaenge nicht abgeschnitten werden, wenn die
VAD den Sprechbeginn immer erst ein paar Chunks spaeter erkennt."""
import collections

SAMPLE_RATE = 16000


class RingBuffer:
    def __init__(self, max_duration_s: float = 30.0):
        self._max_chunks = None
        self._chunks = collections.deque()
        self._chunk_ms = None
        self.max_duration_s = max_duration_s

    def push(self, chunk: bytes, chunk_ms: float):
        if self._chunk_ms is None:
            self._chunk_ms = chunk_ms
            self._max_chunks = max(1, int(self.max_duration_s * 1000 / chunk_ms))
        self._chunks.append(chunk)
        while len(self._chunks) > self._max_chunks:
            self._chunks.popleft()

    def get_preroll(self, duration_s: float) -> bytes:
        """Letzte `duration_s` Sekunden aus dem Puffer (fuer Wortanfang)."""
        if not self._chunks or self._chunk_ms is None:
            return b""
        n_chunks = max(1, int(duration_s * 1000 / self._chunk_ms))
        recent = list(self._chunks)[-n_chunks:]
        return b"".join(recent)

    def clear(self):
        self._chunks.clear()
