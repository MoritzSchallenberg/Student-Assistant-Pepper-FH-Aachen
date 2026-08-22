"""
Voice-Activity-Detection + Aeusserungs-Segmentierung.

Zwei austauschbare Backends:
- SileroVadBackend (bevorzugt): https://github.com/snakers4/silero-vad,
  lokal/offline, per `pip install silero-vad`.
- EnergyVadBackend (Fallback): einfache RMS-Schwelle, portiert aus dem
  bewiesen funktionierenden flask_wrapper/stt/listen_pulse.py. Wird
  automatisch verwendet, wenn `silero_vad` nicht installiert ist --
  blockiert NICHT das Gesamtsystem (Anforderung aus dem Auftrag,
  Abschnitt 17, sinngemaess auch hier angewendet).

UtteranceSegmenter kombiniert ein Backend mit Hysterese (Mindest-
Sprechdauer, Stille-Ende, Maximaldauer) und liefert vollstaendige
Aeusserungen inkl. Pre-Roll aus dem RingBuffer.
"""
import logging
import numpy as np

from .ring_buffer import RingBuffer

SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


class VadBackend:
    """speech_probability(int16-PCM-Chunk) -> float in [0, 1]"""
    name = "base"

    def speech_probability(self, chunk: bytes) -> float:
        raise NotImplementedError


class EnergyVadBackend(VadBackend):
    """RMS-Schwellenwert-VAD, wie in listen_pulse.py bewiesen funktionierend.
    Liefert 1.0/0.0 statt echter Wahrscheinlichkeit -- fuer den
    UtteranceSegmenter reicht das (er vergleicht nur gegen threshold)."""
    name = "energy"

    def __init__(self, rms_threshold: float = 400.0):
        self.rms_threshold = rms_threshold

    def speech_probability(self, chunk: bytes) -> float:
        samples = np.frombuffer(chunk, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        return 1.0 if rms > self.rms_threshold else 0.0


class SileroVadBackend(VadBackend):
    """Echte neuronale VAD. Erwartet 512-Sample-Fenster bei 16kHz (Silero-
    Vorgabe) -- laengere Chunks werden intern in Sub-Fenster zerlegt und
    der Maximalwert genommen (konservativ: ein einziges "Sprache"-Fenster
    im Chunk reicht, um den Chunk als Sprache zu werten)."""
    name = "silero"
    WINDOW_SAMPLES = 512

    def __init__(self):
        from silero_vad import load_silero_vad
        import torch
        self._torch = torch
        self.model = load_silero_vad()

    def speech_probability(self, chunk: bytes) -> float:
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) < self.WINDOW_SAMPLES:
            return 0.0
        probs = []
        for start in range(0, len(samples) - self.WINDOW_SAMPLES + 1, self.WINDOW_SAMPLES):
            window = samples[start:start + self.WINDOW_SAMPLES]
            tensor = self._torch.from_numpy(window)
            with self._torch.no_grad():
                probs.append(self.model(tensor, SAMPLE_RATE).item())
        return max(probs) if probs else 0.0


def create_vad_backend(prefer_silero: bool = True) -> VadBackend:
    if prefer_silero:
        try:
            return SileroVadBackend()
        except Exception as e:
            logger.warning(
                f"Silero VAD nicht verfuegbar ({e}), falle auf Energie-VAD zurueck. "
                f"'pip install silero-vad' fuer bessere Erkennung."
            )
    return EnergyVadBackend()


class UtteranceSegmenter:
    """Zustandsmaschine: sammelt Chunks, bis eine vollstaendige Aeusserung
    erkannt ist (VAD-Start -> genug Sprache -> genug Stille -> Ende)."""

    def __init__(
        self,
        backend: VadBackend,
        ring_buffer: RingBuffer,
        threshold: float = 0.5,
        preroll_s: float = 0.3,
        min_speech_s: float = 0.3,
        silence_end_s: float = 0.7,
        max_utterance_s: float = 15.0,
        chunk_ms: float = 100.0,
    ):
        self.backend = backend
        self.ring_buffer = ring_buffer
        self.threshold = threshold
        self.preroll_s = preroll_s
        self.min_speech_chunks = max(1, int(min_speech_s * 1000 / chunk_ms))
        self.silence_end_chunks = max(1, int(silence_end_s * 1000 / chunk_ms))
        self.max_chunks = max(1, int(max_utterance_s * 1000 / chunk_ms))
        self.chunk_ms = chunk_ms

        self._speech_chunks = []
        self._speech_count = 0
        self._silence_run = 0
        self._in_speech = False

    def reset(self):
        self._speech_chunks = []
        self._speech_count = 0
        self._silence_run = 0
        self._in_speech = False

    def process_chunk(self, chunk: bytes):
        """Fuegt einen Chunk hinzu. Gibt vollstaendige Aeusserung (bytes)
        zurueck, sobald eine erkannt wurde, sonst None."""
        self.ring_buffer.push(chunk, self.chunk_ms)
        prob = self.backend.speech_probability(chunk)
        is_speech = prob >= self.threshold

        if is_speech:
            if not self._in_speech and self._speech_count == 0:
                # Sprechbeginn -- Pre-Roll aus dem Ringpuffer mit reinnehmen
                self._speech_chunks = [self.ring_buffer.get_preroll(self.preroll_s)]
            self._speech_chunks.append(chunk)
            self._speech_count += 1
            self._silence_run = 0
            if self._speech_count >= self.min_speech_chunks:
                self._in_speech = True
            return None

        # Stille
        if self._in_speech:
            self._speech_chunks.append(chunk)
            self._silence_run += 1
            if self._silence_run >= self.silence_end_chunks or len(self._speech_chunks) >= self.max_chunks:
                utterance = b"".join(self._speech_chunks)
                self.reset()
                return utterance
            return None

        # Weder in Sprache noch genug Vorlauf gesammelt -> verwerfen
        self._speech_chunks = []
        self._speech_count = 0
        return None

    def flush(self):
        """Gibt eine laufende Aeusserung zurueck, falls die Audioquelle
        endet/abbricht waehrend noch Sprache erkannt war (z.B. Datei-Ende,
        Verbindungsabbruch) -- sonst ginge der letzte Satz sonst verloren,
        weil nie eine Stille-Phase zum regulaeren Abschluss kam."""
        if self._in_speech and self._speech_chunks:
            utterance = b"".join(self._speech_chunks)
            self.reset()
            return utterance
        self.reset()
        return None
