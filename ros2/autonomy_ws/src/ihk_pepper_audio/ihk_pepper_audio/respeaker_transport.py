"""
ReSpeakerAudioTransport-Familie (Entwicklungsauftrag 04-B, AP6,
Abschnitt 4/5). Trennt "wie kommen rohe Mehrkanaldaten vom ReSpeaker Core
v2.0 zum NUC" von "was macht ReSpeakerCoreV2Source damit" -- gleiches
"Logik von Transport trennen"-Muster wie MotionTransport
(docs/GESTURE_TRANSPORT.md).

Der tatsaechliche Verbindungsweg (lokales ALSA-Geraet im USB-Gadget-
Modus, SSH-Pipe zu einem Capture-Prozess auf dem ReSpeaker selbst, oder
ein dediziertes Netzwerkprotokoll) ist in dieser Session NICHT
verifizierbar -- kein ReSpeaker Core v2.0 erreichbar. Siehe
docs/RESPEAKER_TRANSPORT.md fuer die vollstaendige, ehrliche
Hardware-/Transportanalyse.

Konkrete Implementierungen (LocalAlsaTransport/SshPcmTransport/
NetworkPcmTransport) folgen in einem spaeteren Commit -- dieses Modul
definiert zunaechst nur den Vertrag (abstrakte Basis, Datencontainer,
Fehlerklasse) plus den reinen, sofort testbaren MockPcmTransport.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


class ReSpeakerTransportError(RuntimeError):
    """Wird bei Verbindungsverlust/Zeitueberschreitung/Formatfehler
    geworfen -- der Aufrufer (ReSpeakerCoreV2Source) faengt das ab,
    wartet kurz und versucht einen begrenzten Reconnect (kein
    unbegrenztes Retry)."""


@dataclass(frozen=True)
class RawAudioBlock:
    """Ein roher Mehrkanalblock, wie er von einem ReSpeakerAudioTransport
    geliefert wird -- NOCH NICHT auf ein Mono-Signal reduziert oder
    irgendwie interpretiert (das macht DirectionalAudioBackend, siehe
    directional_audio.py)."""

    pcm_bytes: bytes                # interleaved int16, channel_count Kanaele pro Frame
    channel_count: int
    sample_rate_hz: int
    sample_format: str              # z.B. "S16_LE"
    monotonic_timestamp: float      # time.monotonic() bei Empfang -- NICHT wall-clock
                                     # (Uhrensynchronisation zwischen ReSpeaker/NUC ist
                                     # ungeklaert, siehe docs/RESPEAKER_TRANSPORT.md)
    sequence: int                   # streng monoton steigend -- eine Luecke zeigt
                                     # Paketverlust an, ohne dass der Transport selbst
                                     # eine Ursache kennen muss


class ReSpeakerAudioTransport(ABC):
    """Abstrakte Basis. connect()/close() duerfen mehrfach aufgerufen
    werden (idempotent). read_block() blockiert hoechstens bis zu einem
    intern definierten Timeout -- NIEMALS unbegrenzt (gleiches Prinzip
    wie ueberall sonst im Projekt, siehe DEFAULT_CANCEL_TIMEOUT_S in
    motion_transport.py)."""

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def read_block(self) -> RawAudioBlock:
        """Wirft ReSpeakerTransportError bei Verbindungsverlust/Timeout/
        unerwartetem Format -- gibt NIE ein leeres/kaputtes Block-Objekt
        zurueck, das der Aufrufer faelschlich als gueltig behandeln
        koennte."""
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...


class MockPcmTransport(ReSpeakerAudioTransport):
    """Deterministische synthetische Mehrkanaldaten fuer Tests -- keine
    Hardware, kein Netzwerk. now_fn injizierbar (gleiches Muster wie
    ActuatorArbiter(now_fn=time.monotonic)), damit Zeitstempel-Logik in
    Tests ohne echtes Warten pruefbar ist.

    block_fn(sequence: int) -> bytes (optional): liefert den PCM-Inhalt
    fuer jeden Block -- Standard: Stille (alles Nullen). fail_after
    (optional): laesst read_block() ab diesem Sequenzzaehler
    ReSpeakerTransportError werfen (simuliert Verbindungsabbruch)."""

    def __init__(
        self,
        channel_count: int = 8,
        sample_rate_hz: int = 16000,
        block_duration_ms: int = 20,
        sample_format: str = "S16_LE",
        now_fn=time.monotonic,
        block_fn=None,
        fail_after: int | None = None,
    ):
        self.channel_count = channel_count
        self.sample_rate_hz = sample_rate_hz
        self.block_duration_ms = block_duration_ms
        self.sample_format = sample_format
        self._now_fn = now_fn
        self._block_fn = block_fn
        self._fail_after = fail_after
        self._connected = False
        self._sequence = 0

    def _frames_per_block(self) -> int:
        return int(self.sample_rate_hz * (self.block_duration_ms / 1000.0))

    def connect(self) -> None:
        self._connected = True
        self._sequence = 0

    def read_block(self) -> RawAudioBlock:
        if not self._connected:
            raise ReSpeakerTransportError("nicht verbunden, connect() zuerst aufrufen")
        if self._fail_after is not None and self._sequence >= self._fail_after:
            raise ReSpeakerTransportError("MockPcmTransport: simulierter Verbindungsabbruch")
        frames = self._frames_per_block()
        sample_count = frames * self.channel_count
        if self._block_fn is not None:
            pcm = self._block_fn(self._sequence)
        else:
            pcm = b"\x00\x00" * sample_count
        block = RawAudioBlock(
            pcm_bytes=pcm,
            channel_count=self.channel_count,
            sample_rate_hz=self.sample_rate_hz,
            sample_format=self.sample_format,
            monotonic_timestamp=self._now_fn(),
            sequence=self._sequence,
        )
        self._sequence += 1
        return block

    def close(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected


def create_transport(kind: str, **kwargs) -> ReSpeakerAudioTransport:
    """Fabrikfunktion, analog zu audio_source.py::create_source() --
    LocalAlsaTransport/SshPcmTransport/NetworkPcmTransport folgen in
    einem spaeteren Commit (siehe Moduldoku oben)."""
    if kind == "mock":
        return MockPcmTransport(**kwargs)
    raise ValueError(
        f"Unbekannter oder noch nicht implementierter Transport: {kind!r} "
        f"(local_alsa/ssh_pcm/network_pcm folgen in einem spaeteren Commit, "
        f"siehe docs/RESPEAKER_TRANSPORT.md)"
    )
