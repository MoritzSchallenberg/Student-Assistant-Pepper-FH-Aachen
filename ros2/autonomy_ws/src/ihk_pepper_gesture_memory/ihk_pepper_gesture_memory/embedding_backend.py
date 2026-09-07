"""
Austauschbares Embedding-Backend (Ergaenzungsauftrag 04-A, Gesten-
Vektordatenbank). Bewusst eine eigenstaendige, absichtlich identische
Kopie des Musters aus ihk_pepper_person_memory/embedding_backend.py
(die selbst wiederum ihk_pepper_dialog/faq_cache.py::EmbeddingBackend/
SentenceTransformerBackend/DifflibFallbackBackend/create_embedding_backend()
nachbildet) -- NICHT von dort importiert, um keine feste
Paketabhaengigkeit auf ihk_pepper_person_memory (oder venv_dialog)
einzufuehren. create_embedding_backend() faellt ohne installiertes
sentence-transformers sauber auf reinen Text-/Themenvergleich zurueck
(Auftrag: "lokales, mehrsprachiges Modell mit CPU-Betrieb und
Schluesselwort-/difflib-Fallback").
"""
import difflib
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^\w\s äöüß]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class EmbeddingBackend:
    name = "none"

    def encode(self, text: str):
        raise NotImplementedError

    def similarity(self, a, b) -> float:
        raise NotImplementedError


class SentenceTransformerBackend(EmbeddingBackend):
    name = "sentence-transformers"

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        import numpy as np
        self._np = np
        self.model = SentenceTransformer(model_name)

    def encode(self, text: str):
        return self.model.encode(text, convert_to_numpy=True)

    def similarity(self, a, b) -> float:
        np = self._np
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)


class DifflibFallbackBackend(EmbeddingBackend):
    """Kein echtes Embedding -- reiner Text-/Themenvergleich ueber
    Name+Beschreibung. Semantische Gestensuche ist dann effektiv ein
    Schluesselwortabgleich, der Rest des Systems funktioniert weiter
    (Auftrag-Vorgabe: "Fallback ohne Embedding-Modell")."""

    name = "difflib_fallback"

    def encode(self, text: str):
        return normalize_text(text)

    def similarity(self, a, b) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()


def create_embedding_backend(prefer_st: bool = True) -> EmbeddingBackend:
    if prefer_st:
        try:
            return SentenceTransformerBackend()
        except Exception as e:
            logger.warning(
                f"sentence-transformers nicht verfuegbar ({e}) -- "
                f"Gesten-Vektorsuche laeuft nur mit Text-/Themenvergleich."
            )
    return DifflibFallbackBackend()
