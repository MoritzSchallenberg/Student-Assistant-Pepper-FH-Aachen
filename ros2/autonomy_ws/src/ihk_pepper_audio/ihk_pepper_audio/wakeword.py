"""
Optionale Wakeword-Erkennung ueber openWakeWord
(https://github.com/dscripka/openWakeWord).

UNGETESTET in dieser Session (kein trainiertes "Hey Pepper"-Modell
vorhanden, siehe Auftrag Abschnitt 9 -- "zunaechst kein zwingend
mitzuliefernes eigenes Modell"). Ohne konfiguriertes Modell laeuft das
System einfach ohne Wakeword-Gate weiter (jede Aeusserung wird
verarbeitet) -- siehe DialogManager.wakeword_enabled.
"""
import logging

logger = logging.getLogger(__name__)


class WakewordDetector:
    def __init__(self, model_path: str = "", threshold: float = 0.5):
        self.enabled = bool(model_path)
        self.threshold = threshold
        self.model = None
        if self.enabled:
            try:
                from openwakeword.model import Model
                self.model = Model(wakeword_models=[model_path])
            except Exception as e:
                logger.warning(
                    f"openWakeWord/Modell '{model_path}' nicht ladbar ({e}) -- "
                    f"Wakeword-Gate wird deaktiviert, System bleibt nutzbar."
                )
                self.enabled = False

    def detect(self, pcm_int16_chunk: bytes) -> bool:
        """True, falls Wakeword im Chunk erkannt wurde. Wenn kein Modell
        geladen ist, immer False (Aufrufer sollte dann enabled=False
        pruefen und den Wakeword-Zustand ueberspringen, nicht blockieren)."""
        if not self.enabled or self.model is None:
            return False
        import numpy as np
        samples = np.frombuffer(pcm_int16_chunk, dtype=np.int16)
        prediction = self.model.predict(samples)
        return any(score >= self.threshold for score in prediction.values())
