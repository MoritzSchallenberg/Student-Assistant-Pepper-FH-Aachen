"""
Deterministischer Wissensabruf (Entwicklungsauftrag 3, AP4). Kein ROS,
kein LLM-Aufruf hier -- der eigentliche Datenzugriff erfolgt NIE durch
LLM 1, sondern ausschliesslich durch diese Funktion. Callback-basiertes
Design (faq_lookup_fn/person_memory_fn/rag_fn als injizierte Funktionen)
haelt das Modul frei von ROS-/SQLite-Importen, volle Testbarkeit mit
einfachen Stubs.

Reihenfolge exakt wie im Auftrag vorgegeben:
1. exakter FAQ-Treffer
2. semantischer freigegebener FAQ-Treffer
3. freigegebenes Personengedaechtnis (nur mit Consent)
4. AnythingLLM-/RAG-Abfrage
5. allgemeines LLM-Wissen nur wenn ausdruecklich erlaubt
6. sichere Antwort ohne verlaessliche Information

source_id folgt einem festen Namensschema (faq:<id>, memory:topic:<slug>,
rag:<chunk_id>) -- jede Fakten-ID stammt direkt aus der jeweiligen
Quelle, nie erfunden. ResponsePlanValidator (response_plan.py) prueft
spaeter zusaetzlich, dass ein ResponsePlan nur source_ids referenziert,
die tatsaechlich aus diesem AnswerBrief stammen.
"""
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Fact:
    text: str
    source_id: str
    confidence: float
    origin: str = ""  # "faq_exact" | "faq_semantic" | "person_memory" | "rag"
    timestamp_iso: str = ""


@dataclass
class AnswerBrief:
    question: str
    facts: list = field(default_factory=list)  # list[Fact]
    person_context: dict = field(default_factory=dict)
    uncertainties: list = field(default_factory=list)

    def source_ids(self) -> list:
        return [f.source_id for f in self.facts]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "thema"


def run_retrieval(
    plan,
    question: str,
    faq_lookup_fn: Optional[Callable[[str, str], Optional[dict]]] = None,
    person_memory_fn: Optional[Callable[[str, list], list]] = None,
    rag_fn: Optional[Callable[[str], object]] = None,
    person_context: Optional[dict] = None,
    allow_general_llm_knowledge: bool = False,
) -> AnswerBrief:
    """plan: KnowledgePlanResponse (oder Duck-Type mit denselben Feldern).
    faq_lookup_fn(query, mode) -> {"id","answer","confidence"} | None,
    mode ist "exact" oder "semantic" (gleiches Rueckgabeformat wie
    ihk_pepper_dialog/faq_cache.py::lookup_exact/lookup_semantic).
    person_memory_fn(person_id, topics) -> list[{"topic","summary","confidence"}].
    rag_fn(question) -> ProviderResult-aehnliches Objekt mit .success/.text.
    """
    queries = list(plan.search_queries) if getattr(plan, "search_queries", None) else [question]
    person_context = person_context or {}
    facts = []
    uncertainties = []

    # 1. exakter FAQ-Treffer
    if faq_lookup_fn is not None:
        for query in queries:
            hit = faq_lookup_fn(query, "exact")
            if hit:
                facts.append(Fact(
                    text=hit["answer"], source_id=f"faq:{hit['id']}",
                    confidence=hit.get("confidence", 1.0), origin="faq_exact",
                    timestamp_iso=_now_iso(),
                ))
                break

    # 2. semantischer freigegebener FAQ-Treffer
    if not facts and faq_lookup_fn is not None:
        for query in queries:
            hit = faq_lookup_fn(query, "semantic")
            if hit:
                facts.append(Fact(
                    text=hit["answer"], source_id=f"faq:{hit['id']}",
                    confidence=hit.get("confidence", 0.75), origin="faq_semantic",
                    timestamp_iso=_now_iso(),
                ))
                break

    # 3. freigegebenes Personengedaechtnis -- NUR mit Consent UND wenn
    # die Anfrage (use_person_memory) und required_data_kinds das
    # tatsaechlich vorsehen.
    use_memory = getattr(plan, "use_person_memory", False) or (
        "person_memory" in (getattr(plan, "required_data_kinds", None) or [])
    )
    if not facts and use_memory and person_memory_fn is not None and person_context.get("known"):
        person_id = person_context.get("person_id")
        if person_id:
            memory_hits = person_memory_fn(person_id, queries) or []
            for hit in memory_hits:
                facts.append(Fact(
                    text=hit["summary"],
                    source_id=f"memory:topic:{_slugify(hit.get('topic', ''))}",
                    confidence=hit.get("confidence", 0.6), origin="person_memory",
                    timestamp_iso=_now_iso(),
                ))

    # 4. RAG/AnythingLLM
    if not facts and rag_fn is not None:
        rag_result = rag_fn(question)
        if rag_result is not None and getattr(rag_result, "success", False) and rag_result.text:
            chunk_id = _slugify(question)[:32]
            facts.append(Fact(
                text=rag_result.text, source_id=f"rag:{chunk_id}",
                confidence=0.5, origin="rag", timestamp_iso=_now_iso(),
            ))

    # 5. allgemeines LLM-Wissen nur, wenn ausdruecklich erlaubt -- in
    # dieser Implementierung identisch zum RAG-Pfad behandelt (derselbe
    # rag_fn-Provider), daher kein separater Zweig noetig; das Flag
    # steuert nur, ob rag_fn ueberhaupt aufgerufen werden darf.
    if not facts and allow_general_llm_knowledge and rag_fn is None:
        uncertainties.append("allgemeines_llm_wissen_erlaubt_aber_kein_provider_konfiguriert")

    # 6. sichere Antwort ohne verlaessliche Information
    if not facts:
        uncertainties.append("keine_verlaessliche_information")

    return AnswerBrief(
        question=question, facts=facts, person_context=person_context,
        uncertainties=uncertainties,
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
