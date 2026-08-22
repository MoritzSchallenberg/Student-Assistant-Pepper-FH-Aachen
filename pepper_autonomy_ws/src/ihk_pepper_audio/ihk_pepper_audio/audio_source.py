"""
Austauschbare Audioquellen. Alle liefern 16kHz-Mono-int16-PCM-Chunks ueber
einen Generator, damit Ringpuffer/VAD unabhaengig von der Quelle bleiben.

Quellen:
- FileAudioSource: WAV-Datei, fuer Tests/Mocks (Section 41).
- MicrophoneSource: externes USB-Mikrofon am Rechner (sounddevice).
- PepperPulseAudioSource: der bewiesen funktionierende Fallback aus
  flask_wrapper/stt/listen_loop.py -- SSH-Stream von Peppers
  PulseAudio-"microphone"-Source. MUSS als Fallback erhalten bleiben,
  siehe STATUS.md ("/audio"-ROS-Topic funktioniert auf diesem Pepper
  nicht zuverlaessig).

Automatische Wiederverbindung: jede Quelle wirft AudioSourceError bei
Ausfall, der aufrufende Code (audio_node.py) faengt das ab, wartet kurz
und ruft erneut connect() auf.
"""
import io
import time
import wave

import numpy as np

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
    siehe IMPLEMENTATION_REPORT.md."""
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
    funktionierender Fallback (siehe STATUS.md), portiert aus
    flask_wrapper/stt/listen_pulse.py -- dort haengt der reine
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
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(hostname=self.host, username=self.user,
                            password=self.password, timeout=10)
        except paramiko.ssh_exception.BadAuthenticationType as e:
            if "keyboard-interactive" not in e.allowed_types:
                raise AudioSourceError(str(e)) from e
            transport = client.get_transport()
            transport.auth_interactive(
                self.user, lambda t, i, p: [self.password for _ in p]
            )
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


def create_source(kind: str, **kwargs) -> AudioSource:
    if kind == "file":
        return FileAudioSource(**kwargs)
    if kind == "microphone":
        return MicrophoneSource(**kwargs)
    if kind == "pepper_pulseaudio":
        return PepperPulseAudioSource(**kwargs)
    raise ValueError(f"Unbekannte Audioquelle: {kind}")
