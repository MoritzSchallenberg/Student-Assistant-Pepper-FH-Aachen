"""
Austauschbares Embedding-Backend (Entwicklungsauftrag 3, AP6). Bewusst
eine eigenstaendige, absichtlich identische Kopie des Musters aus
ihk_pepper_dialog/faq_cache.py::EmbeddingBackend/SentenceTransformerBackend/
DifflibFallbackBackend/create_embedding_backend() -- NICHT von dort
importiert, damit ihk_pepper_person_memory keine feste Abhaengigkeit auf
ihk_pepper_dialog/venv_dialog bekommt (vermeidet dieselbe zirkulaere-
Abhaengigkeit-Problematik wie bei providers.py::AnythingLLMProvider,
siehe docs/DEVELOPMENT_ORDER_03_REPORT.md AP2). create_embedding_backend()
faellt ohne installiertes sentence-transformers sauber auf reinen
Text-/Themenvergleich zurueck -- laeuft im normalen numpy<2-Hauptworkspace
ohne Sonderbehandlung (Auftrag AP6: "keine Cloud-Abhaengigkeit
erforderlich", "Fallback ohne Embedding-Modell").
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
    """Kein echtes Embedding -- reiner Text-/Themenvergleich. Semantische
    Erinnerung ist dann effektiv deaktiviert, das uebrige System
    funktioniert weiter (Auftrag-Vorgabe)."""

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
                f"semantisches Personengedaechtnis laeuft nur mit Text-/Themenvergleich."
            )
    return DifflibFallbackBackend()
