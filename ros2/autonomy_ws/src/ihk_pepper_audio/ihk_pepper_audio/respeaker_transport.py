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

LocalAlsaTransport/SshPcmTransport/NetworkPcmTransport (Commit 2) sind
alle drei UNGETESTET gegen echte Hardware (kein ReSpeaker Core v2.0 in
dieser Session erreichbar) -- siehe docs/RESPEAKER_TRANSPORT.md fuer den
genauen hwverificationrequired-Stand jeder einzelnen Annahme (Geraete-
name, arecord-Aufrufsyntax, Netzwerkprotokoll).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .ssh_hardening import connect_hardened


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


def resolve_alsa_device_index(devices: list, name_substring: str):
    """Reine, injizierbare Suchfunktion (kein sounddevice-Import noetig)
    -- sucht ein Eingabegeraet, dessen Name name_substring enthaelt
    (gross-/kleinschreibungsunabhaengig). Verhindert eine fest
    eingetragene Karten-ID (hw:0,0) als Produktionsstandard (Auftrag
    Abschnitt 4): gibt None zurueck, wenn nichts passt, statt auf einen
    Index zu raten."""
    name_lower = name_substring.lower()
    for idx, dev in enumerate(devices):
        if name_lower in dev.get("name", "").lower() and dev.get("max_input_channels", 0) > 0:
            return idx
    return None


class LocalAlsaTransport(ReSpeakerAudioTransport):
    """ReSpeaker im (nicht verifizierten) USB-Audio-Gadget-Modus --
    erscheint dem NUC als gewoehnliches Mehrkanal-ALSA-Geraet, ueber
    sounddevice angesprochen (gleiche Bibliothek wie
    audio_source.py::MicrophoneSource). UNGETESTET gegen echte Hardware
    (kein ReSpeaker in dieser Session erreichbar) -- insbesondere ist
    NICHT verifiziert, ob der Core v2.0 diesen Modus ueberhaupt anbietet,
    siehe docs/RESPEAKER_TRANSPORT.md."""

    def __init__(
        self,
        device_name: str = "seeed-8mic-voicecard",
        channel_count: int = 8,
        sample_rate_hz: int = 16000,
        block_duration_ms: int = 20,
        now_fn=time.monotonic,
    ):
        self.device_name = device_name
        self.channel_count = channel_count
        self.sample_rate_hz = sample_rate_hz
        self.block_duration_ms = block_duration_ms
        self._now_fn = now_fn
        self._stream = None
        self._queue = None
        self._sequence = 0

    def connect(self) -> None:
        import queue

        import sounddevice as sd

        devices = sd.query_devices()
        device_index = resolve_alsa_device_index(list(devices), self.device_name)
        if device_index is None:
            raise ReSpeakerTransportError(
                f"ALSA-Geraet mit Namen '{self.device_name}' nicht gefunden -- "
                f"eine fest eingetragene Karten-ID (hw:0,0) ist kein "
                f"Produktionsstandard (siehe docs/RESPEAKER_TRANSPORT.md)."
            )
        self._queue = queue.Queue()
        frames_per_block = int(self.sample_rate_hz * (self.block_duration_ms / 1000.0))

        def _callback(indata, frames, time_info, status):
            self._queue.put(bytes(indata))

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate_hz, blocksize=frames_per_block,
                dtype="int16", channels=self.channel_count, device=device_index,
                callback=_callback,
            )
            self._stream.start()
        except Exception as e:
            raise ReSpeakerTransportError(f"ALSA-Stream konnte nicht gestartet werden: {e}") from e
        self._sequence = 0

    def read_block(self) -> RawAudioBlock:
        if self._queue is None:
            raise ReSpeakerTransportError("nicht verbunden, connect() zuerst aufrufen")
        try:
            pcm = self._queue.get(timeout=2.0)
        except Exception as e:
            raise ReSpeakerTransportError(f"Kein Audio vom ALSA-Geraet: {e}") from e
        block = RawAudioBlock(
            pcm_bytes=pcm, channel_count=self.channel_count,
            sample_rate_hz=self.sample_rate_hz, sample_format="S16_LE",
            monotonic_timestamp=self._now_fn(), sequence=self._sequence,
        )
        self._sequence += 1
        return block

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        self._stream = None
        self._queue = None

    def is_connected(self) -> bool:
        return self._stream is not None


class SshPcmTransport(ReSpeakerAudioTransport):
    """Kontrollierter Capture-Prozess AUF dem ReSpeaker selbst (siehe
    docs/RESPEAKER_TRANSPORT.md) -- Rohdaten per gehaerteter SSH-Pipe
    (ssh_hardening.py: RejectPolicy, kein AutoAddPolicy) zum NUC
    gestreamt. UNGETESTET gegen echte Hardware -- der genaue
    arecord-Aufruf/Geraetename ist hwverificationrequired, deshalb ueber
    capture_command_template konfigurierbar statt fest verdrahtet."""

    DEFAULT_CAPTURE_COMMAND_TEMPLATE = (
        "arecord -D {device_name} -f {sample_format} -r {sample_rate_hz} "
        "-c {channel_count} --raw -"
    )

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        device_name: str = "seeed-8mic-voicecard",
        channel_count: int = 8,
        sample_rate_hz: int = 16000,
        sample_format: str = "S16_LE",
        block_duration_ms: int = 20,
        port: int = 22,
        timeout_s: float = 10.0,
        capture_command_template: str | None = None,
        now_fn=time.monotonic,
        project_known_hosts_env_var: str = "RESPEAKER_KNOWN_HOSTS_PATH",
        project_default_known_hosts_path: str = "",
    ):
        self.host = host
        self.username = username
        self.password = password
        self.device_name = device_name
        self.channel_count = channel_count
        self.sample_rate_hz = sample_rate_hz
        self.sample_format = sample_format
        self.block_duration_ms = block_duration_ms
        self.port = port
        self.timeout_s = timeout_s
        self.capture_command_template = capture_command_template or self.DEFAULT_CAPTURE_COMMAND_TEMPLATE
        self._now_fn = now_fn
        self._project_known_hosts_env_var = project_known_hosts_env_var
        self._project_default_known_hosts_path = project_default_known_hosts_path
        self._client = None
        self._stdout = None
        self._sequence = 0

    def connect(self) -> None:
        import paramiko

        client = paramiko.SSHClient()
        try:
            connect_hardened(
                client, self.host, self.username, self.password,
                port=self.port, timeout=self.timeout_s,
                project_known_hosts_env_var=self._project_known_hosts_env_var,
                project_default_known_hosts_path=self._project_default_known_hosts_path,
            )
        except Exception as e:
            raise ReSpeakerTransportError(f"SSH-Verbindung zum ReSpeaker fehlgeschlagen: {e}") from e
        cmd = self.capture_command_template.format(
            device_name=self.device_name, sample_format=self.sample_format,
            sample_rate_hz=self.sample_rate_hz, channel_count=self.channel_count,
        )
        _stdin, stdout, _stderr = client.exec_command(cmd)
        stdout.channel.settimeout(self.timeout_s)
        self._client = client
        self._stdout = stdout
        self._sequence = 0

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._stdout.read(n - len(buf))
            if not chunk:
                raise ReSpeakerTransportError("SSH-PCM-Stream beendet (ReSpeaker nicht erreichbar?)")
            buf += chunk
        return buf

    def read_block(self) -> RawAudioBlock:
        if self._stdout is None:
            raise ReSpeakerTransportError("nicht verbunden, connect() zuerst aufrufen")
        frames = int(self.sample_rate_hz * (self.block_duration_ms / 1000.0))
        bytes_needed = frames * self.channel_count * 2
        try:
            pcm = self._read_exact(bytes_needed)
        except ReSpeakerTransportError:
            raise
        except Exception as e:
            raise ReSpeakerTransportError(f"SSH-PCM-Stream unterbrochen: {e}") from e
        block = RawAudioBlock(
            pcm_bytes=pcm, channel_count=self.channel_count,
            sample_rate_hz=self.sample_rate_hz, sample_format=self.sample_format,
            monotonic_timestamp=self._now_fn(), sequence=self._sequence,
        )
        self._sequence += 1
        return block

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._stdout = None

    def is_connected(self) -> bool:
        return self._client is not None


class NetworkPcmTransport(ReSpeakerAudioTransport):
    """Generischer roher TCP-PCM-Stream (kein eigenes Rahmenprotokoll,
    liest einfach einen kontinuierlichen interleaved int16-Mehrkanal-
    strom) -- NICHT verifiziert, ob der Core v2.0 ein solches Protokoll
    tatsaechlich anbietet, siehe docs/RESPEAKER_TRANSPORT.md."""

    def __init__(
        self,
        host: str,
        port: int,
        channel_count: int = 8,
        sample_rate_hz: int = 16000,
        sample_format: str = "S16_LE",
        block_duration_ms: int = 20,
        timeout_s: float = 5.0,
        now_fn=time.monotonic,
    ):
        self.host = host
        self.port = port
        self.channel_count = channel_count
        self.sample_rate_hz = sample_rate_hz
        self.sample_format = sample_format
        self.block_duration_ms = block_duration_ms
        self.timeout_s = timeout_s
        self._now_fn = now_fn
        self._socket = None
        self._sequence = 0

    def connect(self) -> None:
        import socket

        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
            self._socket.settimeout(self.timeout_s)
        except Exception as e:
            raise ReSpeakerTransportError(f"TCP-Verbindung zum ReSpeaker fehlgeschlagen: {e}") from e
        self._sequence = 0

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._socket.recv(n - len(buf))
            if not chunk:
                raise ReSpeakerTransportError("TCP-Verbindung beendet (ReSpeaker nicht erreichbar?)")
            buf += chunk
        return buf

    def read_block(self) -> RawAudioBlock:
        if self._socket is None:
            raise ReSpeakerTransportError("nicht verbunden, connect() zuerst aufrufen")
        frames = int(self.sample_rate_hz * (self.block_duration_ms / 1000.0))
        bytes_needed = frames * self.channel_count * 2
        try:
            pcm = self._read_exact(bytes_needed)
        except ReSpeakerTransportError:
            raise
        except OSError as e:
            raise ReSpeakerTransportError(f"TCP-Stream unterbrochen: {e}") from e
        block = RawAudioBlock(
            pcm_bytes=pcm, channel_count=self.channel_count,
            sample_rate_hz=self.sample_rate_hz, sample_format=self.sample_format,
            monotonic_timestamp=self._now_fn(), sequence=self._sequence,
        )
        self._sequence += 1
        return block

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
        self._socket = None

    def is_connected(self) -> bool:
        return self._socket is not None


def create_transport(kind: str, **kwargs) -> ReSpeakerAudioTransport:
    """Fabrikfunktion, analog zu audio_source.py::create_source()."""
    if kind == "mock":
        return MockPcmTransport(**kwargs)
    if kind == "local_alsa":
        return LocalAlsaTransport(**kwargs)
    if kind == "ssh_pcm":
        return SshPcmTransport(**kwargs)
    if kind == "network_pcm":
        return NetworkPcmTransport(**kwargs)
    raise ValueError(f"Unbekannter Transport: {kind!r}")
