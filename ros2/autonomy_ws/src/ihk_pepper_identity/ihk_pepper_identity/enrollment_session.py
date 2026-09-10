"""
Reine Zustandsmaschine fuer EINE Einschreibungssitzung
(Entwicklungsauftrag 04-B, AP7.1, Abschnitt 7). Kein ROS --
face_identity_node.py::_on_enroll_request() startet eine Sitzung, jeder
folgende synchronisierte Kameraframe ruft observe_enrollment_frame()
auf, bis completed oder failed gesetzt ist oder das Zeitlimit
(node-seitig durchgesetzt) ablaeuft.

Eine Sitzung darf NUR abgeschlossen werden, wenn:
  - JEDER gezaehlte Frame genau EINE sichtbare Person zeigt (Auftrag:
    "die Identitaet ist nicht mehrdeutig") -- ein Frame mit 0 oder
    mehreren Personen wird uebersprungen (kein Fehlschlag der ganzen
    Sitzung, nur dieser eine Frame zaehlt nicht),
  - Liveness fuer diesen Frame bestanden hat,
  - die neu berechnete Einbettung ausreichend AEHNLICH zur ERSTEN
    dieser Sitzung ist (Konsistenzpruefung -- verhindert, dass zwei
    verschiedene Personen nacheinander vor die Kamera treten und
    faelschlich als EINE Einschreibung gezaehlt werden; eine zu grosse
    Abweichung beendet die GESAMTE Sitzung als Fehlschlag, nicht nur
    diesen Frame),
  - required_observations solcher konsistenter Beobachtungen gesammelt
    wurden.

Das gespeicherte Template ist der Mittelwert aller gesammelten
Einbettungen dieser Sitzung (robuster gegen einzelne Ausreisser als
nur die letzte)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class EnrollmentState:
    person_id: str
    required_observations: int
    minimum_consistency_similarity: float
    embeddings: List[bytes] = field(default_factory=list)
    completed: bool = False
    failed: bool = False
    fail_reason: str = ""

    def final_embedding(self) -> Optional[bytes]:
        if not self.completed or not self.embeddings:
            return None
        arrays = [np.frombuffer(e, dtype=np.float32) for e in self.embeddings]
        mean = np.mean(arrays, axis=0).astype(np.float32)
        return mean.tobytes()


def _cosine_similarity(a: bytes, b: bytes) -> float:
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    if va.shape != vb.shape or va.size == 0:
        return -1.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom < 1e-9:
        return -1.0
    return float(np.dot(va, vb) / denom)


def observe_enrollment_frame(
    state: EnrollmentState,
    num_visible_tracks: int,
    liveness_passed: bool,
    embedding: Optional[bytes],
) -> EnrollmentState:
    """Reine Funktion (mutiert und liefert dasselbe state-Objekt zurueck,
    fuer bequeme Verkettung im Aufrufer). Ein bereits abgeschlossenes/
    fehlgeschlagenes state wird unveraendert zurueckgegeben."""
    if state.completed or state.failed:
        return state
    if num_visible_tracks != 1:
        return state  # mehrdeutig oder niemand sichtbar -- Frame uebersprungen
    if not liveness_passed or embedding is None:
        return state  # dieser Frame zaehlt nicht, Sitzung laeuft weiter

    if state.embeddings:
        similarity = _cosine_similarity(state.embeddings[0], embedding)
        if similarity < state.minimum_consistency_similarity:
            state.failed = True
            state.fail_reason = "unterschiedliche_personen_erkannt"
            return state

    state.embeddings.append(embedding)
    if len(state.embeddings) >= state.required_observations:
        state.completed = True
    return state
