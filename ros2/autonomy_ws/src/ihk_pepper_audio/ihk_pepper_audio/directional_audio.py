"""
DirectionalAudioBackend-Familie (Entwicklungsauftrag 04-B, AP6,
Abschnitt 6). Nimmt einen rohen Mehrkanalblock (RawAudioBlock, siehe
respeaker_transport.py) entgegen und erzeugt daraus ein verbessertes
Mono-Signal plus eine horizontale Richtungsschaetzung.

Absichtlich austauschbar (gleiches Prinzip wie MotionTransport/
ReSpeakerAudioTransport): das reale Herstellermodul
(ReSpeakerVendorBackend) ist NICHT verifiziert nutzbar (siehe
docs/RESPEAKER_TRANSPORT.md) -- ein CPU-faehiger Fallback
(GccPhatDelayAndSumBackend) folgt in einem spaeteren Commit. Dieses
Modul definiert zunaechst den Vertrag plus zwei sofort testbare,
einfache Implementierungen (PassthroughTestBackend/MockDirectionalBackend).

WICHTIG (Auftrag Abschnitt 6): ist keine verlaessliche
Richtungsbestimmung moeglich, MUSS valid=False gemeldet werden -- niemals
still auf eine angeblich gerichtete Aufnahme zurueckfallen (kein Backend
in diesem Modul erfindet eine Richtung, wenn es keine hat).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .respeaker_transport import RawAudioBlock


@dataclass(frozen=True)
class DirectionalAudioResult:
    mono_pcm: bytes
    azimuth_rad: float
    doa_confidence: float
    vad_active: bool
    input_rms_dbfs: float
    output_rms_dbfs: float
    valid: bool
    reason: str = ""


class DirectionalAudioBackend(ABC):
    @abstractmethod
    def process(self, block: RawAudioBlock) -> DirectionalAudioResult:
        ...


def _silence_dbfs() -> float:
    """-inf ist fuer Vergleichszwecke unhandlich -- ein sehr niedriger,
    aber endlicher Wert steht fuer "kein messbarer Pegel" (reines
    Nullsignal)."""
    return -120.0


def _rms_dbfs_int16_mono(pcm_bytes: bytes) -> float:
    """Reine Pegelberechnung, keine Bibliotheksabhaengigkeit -- nutzt
    dieselbe Nullvermeidung wie ueberall sonst im Projekt, wo Log von 0
    droht (siehe circuit_breaker.py-Vorbild: nie log(0))."""
    import math
    import struct

    if not pcm_bytes:
        return _silence_dbfs()
    sample_count = len(pcm_bytes) // 2
    if sample_count == 0:
        return _silence_dbfs()
    samples = struct.unpack(f"<{sample_count}h", pcm_bytes[:sample_count * 2])
    sum_sq = sum(s * s for s in samples)
    rms = math.sqrt(sum_sq / sample_count)
    if rms <= 0.0:
        return _silence_dbfs()
    full_scale = 32768.0
    return 20.0 * math.log10(rms / full_scale)


class PassthroughTestBackend(DirectionalAudioBackend):
    """Extrahiert NUR den ersten Kanal als Mono-Signal, schaetzt KEINE
    Richtung (valid=False, ehrlich gekennzeichnet) -- fuer
    respeaker_offline_test/Launch-Modi, in denen der Audiopfad
    end-zu-Ende durchlaufen werden soll, ohne dass ein
    DoA-Backend ueberhaupt beteiligt ist."""

    def __init__(self, vad_threshold_dbfs: float = -45.0):
        self.vad_threshold_dbfs = vad_threshold_dbfs

    def process(self, block: RawAudioBlock) -> DirectionalAudioResult:
        # Kanal 0 aus interleaved int16-Mehrkanaldaten extrahieren.
        import struct
        frame_count = len(block.pcm_bytes) // (2 * block.channel_count)
        mono_samples = []
        for i in range(frame_count):
            offset = i * block.channel_count * 2
            (sample,) = struct.unpack_from("<h", block.pcm_bytes, offset)
            mono_samples.append(sample)
        mono_pcm = struct.pack(f"<{len(mono_samples)}h", *mono_samples) if mono_samples else b""
        input_rms = _rms_dbfs_int16_mono(mono_pcm)
        vad_active = input_rms > self.vad_threshold_dbfs
        return DirectionalAudioResult(
            mono_pcm=mono_pcm,
            azimuth_rad=0.0,
            doa_confidence=0.0,
            vad_active=vad_active,
            input_rms_dbfs=input_rms,
            output_rms_dbfs=input_rms,
            valid=False,
            reason="passthrough_backend_no_direction_estimate",
        )


class MockDirectionalBackend(DirectionalAudioBackend):
    """Liefert ein fest injiziertes oder per result_fn(block) berechnetes
    DirectionalAudioResult -- fuer Tests, die eine EXAKTE Richtung/
    Konfidenz brauchen, ohne echte Signalverarbeitung."""

    def __init__(self, result_fn=None, fixed_result: DirectionalAudioResult | None = None):
        if result_fn is None and fixed_result is None:
            raise ValueError("entweder result_fn oder fixed_result muss gesetzt sein")
        self._result_fn = result_fn
        self._fixed_result = fixed_result

    def process(self, block: RawAudioBlock) -> DirectionalAudioResult:
        if self._result_fn is not None:
            return self._result_fn(block)
        return self._fixed_result


class ReSpeakerVendorBackend(DirectionalAudioBackend):
    """Platzhalter fuer die herstellereigene Onboard-DoA/Beamforming-
    Bibliothek (siehe docs/RESPEAKER_TRANSPORT.md: historisch auf
    Python 2/aelteren Debian-Staenden aufgesetzt -- NICHT ungeprueft auf
    dem NUC installiert, wie vom Auftrag Abschnitt 6 explizit verboten).
    NICHT implementiert -- jede Methode wirft NotImplementedError, exakt
    wie LocalPepperQiHelperTransport in motion_transport.py fuer den
    analogen Fall (dokumentierter, absichtlich nicht umgesetzter Pfad,
    solange kein reales Geraet zur Verifikation erreichbar ist)."""

    def process(self, block: RawAudioBlock) -> DirectionalAudioResult:
        raise NotImplementedError(
            "ReSpeakerVendorBackend ist nicht implementiert -- die "
            "Herstellerbibliothek wurde nicht ungeprueft uebernommen "
            "(siehe docs/RESPEAKER_TRANSPORT.md). Verwende "
            "GccPhatDelayAndSumBackend als CPU-Fallback."
        )
