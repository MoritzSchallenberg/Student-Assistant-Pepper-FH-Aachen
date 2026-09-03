import numpy as np

from ihk_pepper_audio.ring_buffer import RingBuffer
from ihk_pepper_audio.vad_segmenter import UtteranceSegmenter, VadBackend

CHUNK_MS = 100
SAMPLES_PER_CHUNK = int(16000 * CHUNK_MS / 1000)


def _silence_chunk():
    return np.zeros(SAMPLES_PER_CHUNK, dtype=np.int16).tobytes()


def _speech_chunk():
    # konstant "laut" -> von der Fake-VAD unten immer als Sprache erkannt
    return (np.ones(SAMPLES_PER_CHUNK, dtype=np.int16) * 5000).tobytes()


class ScriptedVadBackend(VadBackend):
    """Erkennt Chunks anhand ihres Inhalts als Sprache/Stille (siehe
    _speech_chunk/_silence_chunk oben) -- deterministisch, keine ML-Abhaengigkeit."""
    name = "scripted"

    def speech_probability(self, chunk: bytes) -> float:
        samples = np.frombuffer(chunk, dtype=np.int16)
        return 1.0 if np.abs(samples).mean() > 100 else 0.0


def _make_segmenter(**kwargs):
    return UtteranceSegmenter(
        backend=ScriptedVadBackend(), ring_buffer=RingBuffer(max_duration_s=5.0),
        threshold=0.5, preroll_s=0.1, min_speech_s=0.2, silence_end_s=0.3,
        max_utterance_s=5.0, chunk_ms=CHUNK_MS, **kwargs,
    )


def test_speech_then_silence_completes_utterance():
    seg = _make_segmenter()
    result = None
    for _ in range(3):
        result = seg.process_chunk(_speech_chunk())
        assert result is None
    for _ in range(5):
        result = seg.process_chunk(_silence_chunk())
        if result is not None:
            break
    assert result is not None
    assert len(result) > 0


def test_pure_silence_never_completes():
    seg = _make_segmenter()
    for _ in range(20):
        result = seg.process_chunk(_silence_chunk())
        assert result is None


def test_flush_returns_in_progress_utterance_without_trailing_silence():
    """Regressionstest: eine Test-Datei mit durchgehender Sprache und
    keiner Stille am Ende gab vor dem flush()-Fix nie eine Aeusserung
    zurueck (siehe docs/IMPLEMENTATION_REPORT.md)."""
    seg = _make_segmenter()
    for _ in range(5):
        result = seg.process_chunk(_speech_chunk())
        assert result is None  # nie eine Stille -> process_chunk allein liefert nichts

    flushed = seg.flush()
    assert flushed is not None
    assert len(flushed) > 0


def test_flush_returns_none_when_not_in_speech():
    seg = _make_segmenter()
    for _ in range(3):
        seg.process_chunk(_silence_chunk())
    assert seg.flush() is None
