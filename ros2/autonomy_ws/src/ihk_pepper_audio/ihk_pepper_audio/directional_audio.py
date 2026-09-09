"""
DirectionalAudioBackend-Familie (Entwicklungsauftrag 04-B, AP6,
Abschnitt 6). Nimmt einen rohen Mehrkanalblock (RawAudioBlock, siehe
respeaker_transport.py) entgegen und erzeugt daraus ein verbessertes
Mono-Signal plus eine horizontale Richtungsschaetzung.

Absichtlich austauschbar (gleiches Prinzip wie MotionTransport/
ReSpeakerAudioTransport): das reale Herstellermodul
(ReSpeakerVendorBackend) ist NICHT verifiziert nutzbar (siehe
docs/RESPEAKER_TRANSPORT.md) -- GccPhatDelayAndSumBackend ist der
CPU-faehige Fallback dafuer (Standard-GCC-PHAT-Algorithmus, siehe dessen
eigene Klassendoku fuer die ehrliche Einschraenkung: Zwei-Mikrofon-
Halbebenen-Schaetzung, KEINE volle 360-Grad-Aufloesung).

WICHTIG (Auftrag Abschnitt 6): ist keine verlaessliche
Richtungsbestimmung moeglich, MUSS valid=False gemeldet werden -- niemals
still auf eine angeblich gerichtete Aufnahme zurueckfallen (kein Backend
in diesem Modul erfindet eine Richtung, wenn es keine hat).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

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


class GccPhatDelayAndSumBackend(DirectionalAudioBackend):
    """CPU-faehiger Fallback fuer den Fall, dass die Herstellerbibliothek
    nicht verifiziert nutzbar ist (siehe ReSpeakerVendorBackend). Nutzt
    ein Standard-GCC-PHAT-Verfahren (veroeffentlichter, allgemein
    bekannter Algorithmus -- Generalized Cross Correlation mit Phase
    Transform, siehe z.B. Knapp/Carter 1976) zwischen genau ZWEI
    konfigurierten Mikrofonkanaelen fuer die Richtungsschaetzung, und ein
    einfaches ganzzahliges Sample-Delay-and-Sum ueber ALLE konfigurierten
    Mikrofonkanaele fuer das verbesserte Mono-Signal.

    WICHTIGE EHRLICHE EINSCHRAENKUNG (Auftrag Abschnitt 6): die
    Zwei-Mikrofon-GCC-PHAT-Schaetzung liefert nur eine
    Halbebenen-Schaetzung (bei einem Mikrofonpaar sind Vorne/Hinten
    symmetrisch mehrdeutig) -- fuer eine volle 360-Grad-Aufloesung
    braeuchte es mehrere Mikrofonpaare kombiniert (NICHT implementiert)
    oder das Herstellermodul. Das Delay-and-Sum selbst verschiebt
    Kanaele nur um GANZE Samples (keine Subsample-Interpolation) -- eine
    grobe, aber schnelle Naeherung. GETESTET gegen SYNTHETISCHE,
    kuenstlich verzoegerte Signale (siehe test_directional_audio.py) --
    NICHT gegen echte ReSpeaker-Hardwaredaten (hwverificationrequired,
    siehe docs/RESPEAKER_CALIBRATION.md fuer den vorgesehenen
    Kalibrierungsablauf am realen Geraet)."""

    SPEED_OF_SOUND_M_S = 343.0

    def __init__(
        self,
        microphone_channels: List[int],
        mic_spacing_m: float = 0.035,
        sample_rate_hz: int = 16000,
        vad_threshold_dbfs: float = -45.0,
        min_confidence: float = 0.3,
        smoothing_window: int = 1,
    ):
        if len(microphone_channels) < 2:
            raise ValueError("GccPhatDelayAndSumBackend braucht mindestens 2 Mikrofonkanaele")
        self.microphone_channels = list(microphone_channels)
        self.mic_spacing_m = mic_spacing_m
        self.sample_rate_hz = sample_rate_hz
        self.vad_threshold_dbfs = vad_threshold_dbfs
        self.min_confidence = min_confidence
        self.smoothing_window = max(1, smoothing_window)
        self._recent_azimuths: List[float] = []

    @staticmethod
    def _extract_channel(block: RawAudioBlock, channel_index: int):
        import numpy as np

        samples = np.frombuffer(block.pcm_bytes, dtype=np.int16)
        frame_count = len(samples) // block.channel_count
        samples = samples[: frame_count * block.channel_count]
        reshaped = samples.reshape(frame_count, block.channel_count)
        return reshaped[:, channel_index].astype(np.float64)

    def _gcc_phat(self, sig, refsig):
        import numpy as np

        n = sig.shape[0] + refsig.shape[0]
        SIG = np.fft.rfft(sig, n=n)
        REFSIG = np.fft.rfft(refsig, n=n)
        cross_spectrum = SIG * np.conj(REFSIG)
        denom = np.abs(cross_spectrum)
        denom[denom < 1e-10] = 1e-10
        cc = np.fft.irfft(cross_spectrum / denom, n=n)
        max_shift = n // 2
        cc = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
        peak_index = int(np.argmax(np.abs(cc)))
        shift = peak_index - max_shift
        tau = shift / float(self.sample_rate_hz)
        peak = float(np.abs(cc[peak_index]))
        mean_abs = float(np.mean(np.abs(cc))) + 1e-12
        # Grobe, nicht kalibrierte Konfidenz aus der Peak-Schaerfe --
        # kein physikalisch hergeleiteter Wert, nur ein Startpunkt (siehe
        # docs/RESPEAKER_CALIBRATION.md).
        confidence = min(1.0, peak / (mean_abs * len(cc)))
        return tau, confidence

    def process(self, block: RawAudioBlock) -> DirectionalAudioResult:
        import math

        import numpy as np

        if block.channel_count <= max(self.microphone_channels):
            return DirectionalAudioResult(
                mono_pcm=b"", azimuth_rad=0.0, doa_confidence=0.0, vad_active=False,
                input_rms_dbfs=_silence_dbfs(), output_rms_dbfs=_silence_dbfs(),
                valid=False, reason="channel_count_mismatch",
            )

        channels = [self._extract_channel(block, c) for c in self.microphone_channels]
        ref = channels[0]
        other = channels[1]

        max_tau = self.mic_spacing_m / self.SPEED_OF_SOUND_M_S
        tau, confidence = self._gcc_phat(other, ref)
        tau = max(-max_tau, min(max_tau, tau))

        sin_theta = tau * self.SPEED_OF_SOUND_M_S / self.mic_spacing_m
        sin_theta = max(-1.0, min(1.0, sin_theta))
        azimuth = math.asin(sin_theta)
        if self.smoothing_window > 1:
            self._recent_azimuths.append(azimuth)
            self._recent_azimuths = self._recent_azimuths[-self.smoothing_window:]
            azimuth = float(np.mean(self._recent_azimuths))

        input_rms = self._rms_dbfs(ref)
        vad_active = input_rms > self.vad_threshold_dbfs
        valid = (confidence >= self.min_confidence) and vad_active

        # Einfaches Delay-and-Sum: alle konfigurierten Kanaele werden per
        # ganzzahliger Sample-Verschiebung auf den Referenzkanal
        # ausgerichtet und gemittelt -- keine Subsample-Interpolation
        # (siehe Klassendoku oben).
        shift_samples = int(round(tau * self.sample_rate_hz))
        aligned = [ref] + [np.roll(ch, shift_samples) for ch in channels[1:]]
        summed = np.mean(aligned, axis=0)
        summed_int16 = np.clip(summed, -32768, 32767).astype(np.int16)
        mono_pcm = summed_int16.tobytes()
        output_rms = self._rms_dbfs(summed)

        return DirectionalAudioResult(
            mono_pcm=mono_pcm, azimuth_rad=azimuth, doa_confidence=confidence,
            vad_active=vad_active, input_rms_dbfs=input_rms, output_rms_dbfs=output_rms,
            valid=valid, reason="" if valid else "low_confidence_or_no_speech",
        )

    @staticmethod
    def _rms_dbfs(samples) -> float:
        import math

        import numpy as np

        if samples.size == 0:
            return _silence_dbfs()
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        if rms <= 0.0:
            return _silence_dbfs()
        return 20.0 * math.log10(rms / 32768.0)


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
