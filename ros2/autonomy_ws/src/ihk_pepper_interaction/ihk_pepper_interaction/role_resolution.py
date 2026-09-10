"""
Vertrauenswürdige Rollenauflösung (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 8). REIN, kein ROS -- command_router_node.py bindet
get_effective_role_fn an eine echte identity_registry_db.py-Instanz.

Der zentrale Grundsatz (Auftrag Abschnitt 8): "Die Identity-Komponente
darf höchstens eine Person-ID liefern. Die Rolle wird aus der
vertrauenswürdigen Personen-Registry geladen." -- PersonIdentity.role
(ein Feld, das über ein Sensor-/Erkennungstopic ankommt) wird HIER
NIEMALS gelesen/vertraut. face_identity_node.py setzt dieses Feld
absichtlich nur auf einen sicheren Platzhalter (siehe dessen
Moduldoku) -- vor AP7.1 vertraute command_router_node.py::
_lookup_identity() diesem Feld noch direkt, das war der bestätigte
Fehler, den dieses Modul schließt.

Regeln, alle fail-closed auf ROLE_STUDENT:
    unbekannt                  -> STUDENT
    bekannt ohne Rolle          -> STUDENT (get_effective_role_fn selbst
                                   liefert das für eine unbekannte
                                   person_id, siehe identity_registry_db.py)
    abgelaufene Identität       -> STUDENT (effective_role() in
                                   identity_registry.py, ueber
                                   get_effective_role_fn)
    mehrdeutiges Matching       -> STUDENT (identity_frame_processor.py
                                   liefert in diesem Fall bereits
                                   known=False, siehe dort)
    fehlender Registry-Zugriff  -> STUDENT (get_effective_role_fn wirft
                                   -> hier abgefangen, NIE propagiert)
    widerrufene Einwilligung    -> UNKNOWN + STUDENT (consent_granted=False)
    gültige Zuordnung           -> hinterlegte Rolle
"""
from __future__ import annotations

from typing import Callable, Optional

from .roles import ROLE_STUDENT


def resolve_role(
    known: bool,
    consent_granted: bool,
    person_id: str,
    get_effective_role_fn: Callable[[str, Optional[float]], str],
    now: Optional[float] = None,
) -> str:
    """Reine Funktion. get_effective_role_fn wird NUR aufgerufen, wenn
    known UND consent_granted UND eine nicht-leere person_id vorliegen
    -- jede Ausnahme daraus (Registry nicht erreichbar) wird abgefangen,
    NIE nach aussen weitergereicht (Auftrag: 'fehlender Registry-Zugriff
    -> STUDENT', nicht 'Knoten stürzt ab')."""
    if not known or not consent_granted or not person_id:
        return ROLE_STUDENT
    try:
        return get_effective_role_fn(person_id, now)
    except Exception:
        return ROLE_STUDENT
