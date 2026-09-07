"""
Reine Filter-/Rangierungslogik fuer die Gesten-Vektorsuche
(Ergaenzungsauftrag 04-A). Kein ROS, kein SQLite hier -- nur Dataclasses
und Funktionen, damit die Sicherheitslogik unabhaengig von einer echten
Datenbank/einem echten Embedding-Modell getestet werden kann (gleiches
Trennungsprinzip wie response_plan.py::ResponsePlanValidator).

Harte Filter (passes_hard_filters) laufen IMMER VOR jeder semantischen
Bewertung -- ein Kandidat, der einen Hartfilter nicht besteht, kann
durch keinen noch so hohen Aehnlichkeitswert wieder hereinkommen.
"""
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_TOP_K = 5

# Reihenfolge ist hier bewusst als Rang kodiert (nicht nur eine Menge),
# damit "production_mode" (== nur live_validated) und ein per Anfrage
# gesetztes minimum_tested_status einheitlich als "mindestens Rang X"
# geprueft werden koennen.
TESTED_STATUS_RANK = {"draft": 0, "dry_run_validated": 1, "live_validated": 2}


@dataclass
class GestureIndexEntry:
    """Ein indizierter Katalog-Eintrag. `embedding` ist absichtlich
    backend-agnostisch (Liste von float bei SentenceTransformerBackend,
    ein normalisierter String bei DifflibFallbackBackend) -- Aufrufer
    reichen sie unveraendert an embedding_backend.similarity() weiter."""

    name: str
    description: str = ""
    tested_status: str = "draft"
    duration_s: float = 0.0
    allowed_interaction_states: list = field(default_factory=list)
    requires_stationary: bool = False
    affects_head: bool = False
    system_only: bool = False
    selectable_by_llm: bool = True
    embedding: object = None


@dataclass
class GestureSearchRequest:
    query: str = ""
    interaction_state: str = ""
    nav2_moving: bool = False
    mapping_active: bool = False
    production_mode: bool = False
    minimum_tested_status: str = ""
    max_duration_s: float = 0.0
    exclude_recent: list = field(default_factory=list)
    top_k: int = 0
    include_system_only: bool = False


def _minimum_required_rank(request: GestureSearchRequest) -> int:
    if request.production_mode:
        # Auftrag: "im Produktionsmodus standardmaessig nur
        # live_validated" -- ein per Anfrage gesetztes
        # minimum_tested_status kann das NICHT absenken, nur die
        # nicht-Produktionsseite hat ueberhaupt einen konfigurierbaren
        # Mindeststatus.
        return TESTED_STATUS_RANK["live_validated"]
    return TESTED_STATUS_RANK.get(request.minimum_tested_status, TESTED_STATUS_RANK["draft"])


def passes_hard_filters(entry: GestureIndexEntry, request: GestureSearchRequest) -> bool:
    if TESTED_STATUS_RANK.get(entry.tested_status, -1) < _minimum_required_rank(request):
        return False
    if entry.allowed_interaction_states and request.interaction_state:
        if request.interaction_state not in entry.allowed_interaction_states:
            return False
    if request.nav2_moving and entry.requires_stationary:
        return False
    if request.mapping_active and entry.affects_head:
        return False
    if request.max_duration_s and request.max_duration_s > 0 and entry.duration_s > request.max_duration_s:
        return False
    if entry.name in (request.exclude_recent or []):
        return False
    if entry.system_only and not request.include_system_only:
        return False
    if not entry.selectable_by_llm and request.query and not request.include_system_only:
        # Auftrag: "system_only-Gesten sind strukturell nie LLM-
        # waehlbar" -- selectable_by_llm=False wird bei einer echten
        # (nicht-leeren) Suchanfrage genauso behandelt wie system_only,
        # ausser ein interner Aufrufer setzt include_system_only
        # explizit (z.B. gesturectl-Introspektion).
        return False
    return True


def rank_candidates(
    entries: list,
    request: GestureSearchRequest,
    embedding_backend,
) -> list:
    """Gibt eine Liste von (GestureIndexEntry, score) zurueck, hoechste
    Aehnlichkeit zuerst, auf top_k begrenzt (Server-Default
    DEFAULT_TOP_K, falls request.top_k<=0). Ohne query: stabile
    alphabetische Reihenfolge, score=1.0 (kein Aehnlichkeitsvergleich
    ohne Suchtext moeglich/sinnvoll)."""
    filtered = [e for e in entries if passes_hard_filters(e, request)]

    if not request.query:
        results = [(e, 1.0) for e in sorted(filtered, key=lambda e: e.name)]
    else:
        query_emb = embedding_backend.encode(request.query)
        scored = [
            (e, embedding_backend.similarity(query_emb, e.embedding))
            for e in filtered
        ]
        # Sekundaerschluessel `name` fuer eine deterministische
        # Reihenfolge bei gleichem Score (Tests duerfen sich auf eine
        # feste Reihenfolge verlassen).
        scored.sort(key=lambda pair: (-pair[1], pair[0].name))
        results = scored

    top_k = request.top_k if request.top_k and request.top_k > 0 else DEFAULT_TOP_K
    return results[:top_k]
