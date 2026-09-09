"""
Austauschbare Audioquellen. Alle liefern 16kHz-Mono-int16-PCM-Chunks ueber
einen Generator, damit Ringpuffer/VAD unabhaengig von der Quelle bleiben.

Quellen:
- FileAudioSource: WAV-Datei, fuer Tests/Mocks (Section 41).
- MicrophoneSource: externes USB-Mikrofon am Rechner (sounddevice).
- PepperPulseAudioSource: der bewiesen funktionierende Fallback aus
  apps/web/stt/listen_loop.py -- SSH-Stream von Peppers
  PulseAudio-"microphone"-Source. MUSS als Fallback erhalten bleiben,
  siehe docs/STATUS.md ("/audio"-ROS-Topic funktioniert auf diesem Pepper
  nicht zuverlaessig).

Automatische Wiederverbindung: jede Quelle wirft AudioSourceError bei
Ausfall, der aufrufende Code (audio_node.py) faengt das ab, wartet kurz
und ruft erneut connect() auf.
"""
import io
import time
import wave

import numpy as np

from .directional_audio import DirectionalAudioBackend, PassthroughTestBackend
from .respeaker_transport import ReSpeakerAudioTransport, ReSpeakerTransportError

SAMPLE_RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * (CHUNK_MS / 1000.0)) * 2  # int16 mono


class AudioSourceError(RuntimeError):
    pass


class AudioSource:
    name = "base"

    def connect(self):
        raise NotImplementedError

    def read_chunk(self) -> bytes:
        """Liefert CHUNK_BYTES an int16-Mono-PCM-Samples bei SAMPLE_RATE,
        oder wirft AudioSourceError bei Ausfall."""
        raise NotImplementedError

    def close(self):
        pass


class FileAudioSource(AudioSource):
    """Liest eine WAV-Datei chunkweise, resampelt NICHT -- Testdateien
    muessen bereits 16kHz/Mono/16bit sein (siehe test/fixtures/)."""
    name = "file"

    def __init__(self, path: str, loop: bool = False, realtime: bool = True):
        self.path = path
        self.loop = loop
        self.realtime = realtime
        self._wav = None
        self._frames = None
        self._pos = 0

    def connect(self):
        self._wav = wave.open(self.path, "rb")
        if self._wav.getframerate() != SAMPLE_RATE or self._wav.getnchannels() != 1:
            raise AudioSourceError(
                f"{self.path}: erwartet {SAMPLE_RATE}Hz Mono, "
                f"hat {self._wav.getframerate()}Hz {self._wav.getnchannels()}ch"
            )
        self._frames = self._wav.readframes(self._wav.getnframes())
        self._pos = 0

    def read_chunk(self) -> bytes:
        if self._frames is None:
            raise AudioSourceError("nicht verbunden, connect() zuerst aufrufen")
        end = self._pos + CHUNK_BYTES
        chunk = self._frames[self._pos:end]
        self._pos = end
        if len(chunk) == 0:
            if self.loop:
                self._pos = CHUNK_BYTES
                chunk = self._frames[0:CHUNK_BYTES]
            else:
                raise AudioSourceError("Datei-Ende erreicht")
        if len(chunk) < CHUNK_BYTES:
            chunk = chunk + b"\x00" * (CHUNK_BYTES - len(chunk))
        if self.realtime:
            time.sleep(CHUNK_MS / 1000.0)
        return chunk

    def close(self):
        if self._wav:
            self._wav.close()


class MicrophoneSource(AudioSource):
    """Externes USB-Mikrofon ueber sounddevice. UNGETESTET in dieser
    Session (kein USB-Mikrofon an diesem Rechner angeschlossen) --
    siehe docs/IMPLEMENTATION_REPORT.md."""
    name = "microphone"

    def __init__(self, device=None):
        self.device = device
        self._stream = None
        self._queue = None

    def connect(self):
        import sounddevice as sd
        import queue
        self._queue = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                pass  # Overflow/Underflow -- wird beim naechsten read_chunk sichtbar (leere Queue)
            self._queue.put(bytes(indata))

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, blocksize=CHUNK_BYTES // 2,
                dtype="int16", channels=1, device=self.device,
                callback=callback,
            )
            self._stream.start()
        except Exception as e:
            raise AudioSourceError(f"Mikrofon nicht verfuegbar: {e}") from e

    def read_chunk(self) -> bytes:
        if self._queue is None:
            raise AudioSourceError("nicht verbunden, connect() zuerst aufrufen")
        try:
            return self._queue.get(timeout=2.0)
        except Exception as e:
            raise AudioSourceError(f"Kein Audio vom Mikrofon: {e}") from e

    def close(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()


class PepperPulseAudioSource(AudioSource):
    """SSH-Stream von Peppers PulseAudio-"microphone"-Source. Bewiesen
    funktionierender Fallback (siehe docs/STATUS.md), portiert aus
    apps/web/stt/listen_pulse.py -- dort haengt der reine
    Live-Stream-Ansatz allerdings gelegentlich (offenes TODO); dieser
    Wrapper nutzt denselben Mechanismus, kapselt ihn aber mit Timeout
    und Reconnect-Logik in audio_node.py."""
    name = "pepper_pulseaudio"

    def __init__(self, host, user, password):
        self.host = host
        self.user = user
        self.password = password
        self._client = None
        self._channel = None
        self._stdout = None

    def connect(self):
        import paramiko

        from .ssh_hardening import HostKeyChangedError, UnknownHostKeyError, connect_hardened

        client = paramiko.SSHClient()
        try:
            # Entwicklungsauftrag 04-B, AP6: AutoAddPolicy entfernt --
            # bestaetigter Fund, siehe docs/RESPEAKER_TRANSPORT.md. Gleiche
            # Haertung wie apps/web/pepper/qicli.py (RejectPolicy, System-
            # UND projekteigene known_hosts, kein automatisches Vertrauen).
            connect_hardened(
                client, self.host, self.user, self.password, timeout=10,
                project_known_hosts_env_var="PEPPER_KNOWN_HOSTS_PATH",
            )
        except (HostKeyChangedError, UnknownHostKeyError) as e:
            raise AudioSourceError(str(e)) from e
        except Exception as e:
            raise AudioSourceError(f"SSH-Verbindung fehlgeschlagen: {e}") from e

        cmd = (
            f"parecord --device=microphone --raw --format=s16le "
            f"--rate={SAMPLE_RATE} --channels=1 -"
        )
        stdin, stdout, stderr = client.exec_command(cmd)
        self._client = client
        self._stdout = stdout

    def read_chunk(self) -> bytes:
        if self._stdout is None:
            raise AudioSourceError("nicht verbunden, connect() zuerst aufrufen")
        chunk = self._stdout.read(CHUNK_BYTES)
        if not chunk:
            raise AudioSourceError("PulseAudio-Stream beendet (Pepper nicht erreichbar?)")
        return chunk

    def close(self):
        if self._client:
            self._client.close()


class ReSpeakerCoreV2Source(AudioSource):
    """ReSpeaker Core v2.0 als primaere Tonaufnahmequelle
    (Entwicklungsauftrag 04-B, AP6, Abschnitt 5). Kapselt einen
    austauschbaren ReSpeakerAudioTransport (rohe Mehrkanaldaten, siehe
    respeaker_transport.py) + ein DirectionalAudioBackend
    (Mono-Reduktion + Richtungsschaetzung, siehe directional_audio.py)
    hinter der etablierten AudioSource-Schnittstelle -- read_chunk()
    liefert weiterhin exakt CHUNK_BYTES an 16kHz-Mono-int16-PCM, der
    bestehende VAD-/Whisper-Pfad muss NICHTS ueber Mehrkanaldaten wissen.

    Diagnosedaten (Auftrag Abschnitt 18) als oeffentliche Attribute
    abrufbar: last_azimuth_rad, last_doa_confidence, last_vad_active,
    last_direction_valid, last_backend_reason, dropped_stale_frames,
    packet_loss_count, buffer_overflow_count."""

    name = "respeaker_core_v2"

    def __init__(
        self,
        transport: ReSpeakerAudioTransport,
        directional_backend: DirectionalAudioBackend = None,
        maximum_buffer_ms: float = 500.0,
        maximum_frame_age_ms: float = 200.0,
        expected_channel_count: int | None = None,
        now_fn=time.monotonic,
    ):
        self._transport = transport
        self._backend = directional_backend or PassthroughTestBackend()
        self.maximum_buffer_ms = maximum_buffer_ms
        self.maximum_frame_age_ms = maximum_frame_age_ms
        self.expected_channel_count = expected_channel_count
        self._now_fn = now_fn
        self._mono_buffer = bytearray()
        self._expected_sequence = None

        self.last_azimuth_rad = 0.0
        self.last_doa_confidence = 0.0
        self.last_vad_active = False
        self.last_direction_valid = False
        self.last_backend_reason = ""
        self.dropped_stale_frames = 0
        self.packet_loss_count = 0
        self.buffer_overflow_count = 0

    def connect(self):
        self._transport.connect()
        self._mono_buffer = bytearray()
        self._expected_sequence = None

    def _max_buffer_bytes(self) -> int:
        return int(SAMPLE_RATE * (self.maximum_buffer_ms / 1000.0)) * 2  # int16 mono

    def _ingest_one_block(self):
        try:
            block = self._transport.read_block()
        except ReSpeakerTransportError as e:
            raise AudioSourceError(f"ReSpeaker-Transport fehlgeschlagen: {e}") from e

        if self.expected_channel_count is not None and block.channel_count != self.expected_channel_count:
            raise AudioSourceError(
                f"Unerwartete Kanalzahl vom ReSpeaker: erwartet "
                f"{self.expected_channel_count}, erhalten {block.channel_count} -- "
                f"kein stillschweigendes Weiterverarbeiten falsch interpretierter Daten."
            )

        # Paketverlust: eine Luecke in der Sequenznummer zeigt verlorene
        # Bloecke an -- wird nur gezaehlt/diagnostiziert, bricht den
        # Strom NICHT ab (ein einzelner verlorener Block ist kein
        # Verbindungsabbruch).
        if self._expected_sequence is not None and block.sequence != self._expected_sequence:
            self.packet_loss_count += 1
        self._expected_sequence = block.sequence + 1

        age_ms = (self._now_fn() - block.monotonic_timestamp) * 1000.0
        if age_ms > self.maximum_frame_age_ms:
            self.dropped_stale_frames += 1
            return  # veraltete Frames verwerfen -- kein Beitrag zum Mono-Puffer

        result = self._backend.process(block)
        self.last_azimuth_rad = result.azimuth_rad
        self.last_doa_confidence = result.doa_confidence
        self.last_vad_active = result.vad_active
        self.last_direction_valid = result.valid
        self.last_backend_reason = result.reason

        self._mono_buffer.extend(result.mono_pcm)
        max_bytes = self._max_buffer_bytes()
        if len(self._mono_buffer) > max_bytes:
            # Kein unbegrenzter Puffer (Auftrag Abschnitt 5): aeltesten
            # Ueberschuss verwerfen, NIE unbegrenzt wachsen lassen.
            overflow = len(self._mono_buffer) - max_bytes
            del self._mono_buffer[:overflow]
            self.buffer_overflow_count += 1

    def read_chunk(self) -> bytes:
        while len(self._mono_buffer) < CHUNK_BYTES:
            self._ingest_one_block()
        chunk = bytes(self._mono_buffer[:CHUNK_BYTES])
        del self._mono_buffer[:CHUNK_BYTES]
        return chunk

    def close(self):
        self._transport.close()


def build_respeaker_transport_from_config(cfg: dict):
    """Baut einen ReSpeakerAudioTransport direkt aus dem in Auftrag
    Abschnitt 5 gezeigten YAML-Schema (audio.*) -- Kanalzuordnung
    (microphone_channels/loopback_channels) ist zum jetzigen Zeitpunkt
    nur eine Vorlage (siehe docs/RESPEAKER_TRANSPORT.md, "Was noch zu
    verifizieren ist"), wird hier NICHT weiter interpretiert (das macht
    DirectionalAudioBackend, sobald die reale Reihenfolge bekannt ist)."""
    from .respeaker_transport import create_transport

    transport_kind = cfg.get("transport", "mock")
    channel_count = cfg.get("input_channels", 8)
    sample_rate_hz = cfg.get("sample_rate_hz", SAMPLE_RATE)
    block_duration_ms = cfg.get("block_duration_ms", 20)
    device_name = cfg.get("device_name", "seeed-8mic-voicecard")

    kwargs = dict(channel_count=channel_count, sample_rate_hz=sample_rate_hz,
                  block_duration_ms=block_duration_ms)
    if transport_kind == "local_alsa":
        kwargs["device_name"] = device_name
    elif transport_kind == "ssh_pcm":
        kwargs.update(
            host=cfg.get("respeaker_host", ""), username=cfg.get("respeaker_user", ""),
            password=cfg.get("respeaker_password", ""), device_name=device_name,
        )
    elif transport_kind == "network_pcm":
        kwargs.update(host=cfg.get("respeaker_host", ""), port=cfg.get("respeaker_port", 0))
    return create_transport(transport_kind, **kwargs)


def create_source(kind: str, **kwargs) -> AudioSource:
    if kind == "file":
        return FileAudioSource(**kwargs)
    if kind == "microphone":
        return MicrophoneSource(**kwargs)
    if kind == "pepper_pulseaudio":
        return PepperPulseAudioSource(**kwargs)
    if kind == "respeaker_core_v2":
        return ReSpeakerCoreV2Source(**kwargs)
    raise ValueError(f"Unbekannte Audioquelle: {kind}")
