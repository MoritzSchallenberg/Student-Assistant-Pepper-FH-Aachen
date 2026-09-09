"""
Vergleicht eine frisch berechnete Gesichtseinbettung gegen gespeicherte
biometrische Vorlagen (Entwicklungsauftrag 04-B, AP7, Abschnitt 7).
Reine Logik, KEINE Datenbank-/ROS-Abhaengigkeit -- bekommt die
Kandidatenliste bereits als (person_id, embedding)-Paare uebergeben
(der Aufrufer holt sie z.B. aus biometric_template_store.py, NUR fuer
Personen mit erteiltem Consent).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class IdentityMatchResult:
    person_id: Optional[str]
    matched: bool
    similarity: float
    margin: float
    reason: str = ""


def _cosine_similarity(a: bytes, b: bytes) -> float:
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    if va.shape != vb.shape or va.size == 0:
        return -1.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom < 1e-9:
        return -1.0
    return float(np.dot(va, vb) / denom)


def match_embedding(
    query_embedding: bytes,
    candidates: List[Tuple[str, bytes]],
    minimum_similarity: float = 0.55,
    minimum_margin: float = 0.05,
) -> IdentityMatchResult:
    """Reine Funktion. Mehrdeutigkeit (zwei fast gleich gute
    Kandidaten) fuehrt IMMER zu matched=False -- NIE zu einer geratenen
    Person (Auftrag Abschnitt 7: "mehrdeutige Ergebnisse werden
    abgelehnt"), gleiches Prinzip wie audiovisual_association.py's
    Mehrdeutigkeitsabweisung bei zu geringem Winkelabstand."""
    if not candidates:
        return IdentityMatchResult(None, False, 0.0, 0.0, "keine_kandidaten")

    scored = sorted(
        ((pid, _cosine_similarity(query_embedding, emb)) for pid, emb in candidates),
        key=lambda x: x[1], reverse=True,
    )
    best_id, best_sim = scored[0]

    if best_sim < minimum_similarity:
        return IdentityMatchResult(None, False, best_sim, 0.0, "keine_ausreichende_aehnlichkeit")

    if len(scored) == 1:
        return IdentityMatchResult(best_id, True, best_sim, 1.0, "")

    _second_id, second_sim = scored[1]
    margin = best_sim - second_sim
    if margin < minimum_margin:
        return IdentityMatchResult(None, False, best_sim, margin, "mehrdeutig")
    return IdentityMatchResult(best_id, True, best_sim, margin, "")
