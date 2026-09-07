"""
Deterministischer Datenschutzfilter fuer alles, was an einen externen
LLM-Anbieter (KI:connect, oder jeder andere ausserhalb dieses Systems
gehostete Provider) geschickt wird -- Ergaenzungsauftrag 04-A,
Abschnitt 1.7.

Reines, ROS-freies Modul (gleiches Muster wie response_plan.py). Kein
LLM-Aufruf hier -- nur eine reine Funktion, die aus den bereits
vorhandenen Pipeline-Datenstrukturen (AnswerBrief, PersonContext,
Gestenkandidaten) genau die in Auftrag 1.7 erlaubte, pseudonymisierte
Teilmenge herausschneidet. STRUKTURELL ausgeschlossen (nicht nur per
Konvention weggelassen): person_id, track_id, session_id, Vor-/
Nachname, Gesichtsdaten, Roh-Audio, volle Personenakte, interne
Netzwerkadressen, Zugangsdaten, psychologische/medizinische
Vermutungen, ungekuerzte Gespraechshistorie -- das Ausgabeschema
(RedactedAnswerContext) besitzt fuer keinen dieser Punkte ueberhaupt
ein Feld.
"""
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

SCHEMA_VERSION = 1

# Dieselbe Fehlerklasse wie der projektweite Secret-Scan (siehe
# .github/workflows/ci.yml) -- Verteidigung in der Tiefe: selbst ein
# Fakt-Text, der versehentlich eine interne IP oder ein
# zugangsdatenaehnliches Muster enthaelt, wird NIE unveraendert an
# KI:connect weitergereicht.
_INTERNAL_IP_RE = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
_CREDENTIAL_LIKE_RE = re.compile(
    r"(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+", re.IGNORECASE
)


class DisallowedContentError(Exception):
    """Ein Fakt-Text enthaelt ein Muster, das strukturell nie an einen
    externen LLM-Provider gehen darf (interne IP, zugangsdatenaehnliches
    Muster). Der Fakt wird verworfen, NICHT stillschweigend bereinigt
    und weitergeschickt -- ein Aufrufer soll merken, dass hier ein
    Retriever-Ergebnis fehlerhaft war, nicht dass alles normal lief."""


@dataclass
class RedactedInteractionContext:
    person_known: bool = False
    preferred_form_of_address: str = "neutral"


@dataclass
class RedactedAnswerContext:
    """Exakt das Schema aus Auftrag 1.7 -- das einzige, was LLM 3
    (KI:connect) jemals zu sehen bekommt. Kein Feld fuer person_id,
    track_id, session_id, Namen, Gesichtsdaten, Roh-Audio, volle
    Personenakte, interne Netzwerkadressen, Zugangsdaten, psychologische/
    medizinische Vermutungen oder ungekuerzte Gespraechshistorie --
    diese Felder existieren in dieser Klasse schlicht nicht (Struktur-
    Ausschluss, kein Validierungs-Nachtrag)."""

    schema_version: int = SCHEMA_VERSION
    language: str = "de"
    answer_facts: list = field(default_factory=list)  # list[str]
    source_ids: list = field(default_factory=list)  # list[str]
    allowed_gestures: list = field(default_factory=list)  # list[str]
    interaction_context: RedactedInteractionContext = field(
        default_factory=RedactedInteractionContext
    )

    def to_dict(self) -> dict:
        return asdict(self)


def _scan_fact_text(text: str) -> str:
    if _INTERNAL_IP_RE.search(text) or _CREDENTIAL_LIKE_RE.search(text):
        raise DisallowedContentError(
            "Fakt-Text enthaelt ein internes-IP- oder zugangsdatenaehnliches "
            "Muster -- wird NICHT an einen externen LLM-Provider gesendet."
        )
    return text


def redact_for_external_llm(
    answer_brief,
    person_context=None,
    allowed_gesture_names: Optional[list] = None,
    language: str = "de",
    preferred_form_of_address: str = "neutral",
) -> RedactedAnswerContext:
    """Baut aus einem AnswerBrief (siehe retriever.py) + optionalem
    PersonContext (siehe knowledge_planner.py) + einer Gestennamen-
    Allowlist die pseudonymisierte, fuer KI:connect zulaessige
    Teilmenge.

    `answer_brief.question` (die rohe Nutzerfrage, koennte einen vom
    Nutzer selbst genannten Namen enthalten) wird bewusst NICHT
    uebernommen -- nur die bereits durch den deterministischen
    Retriever bestaetigten `facts` (kurze, faktische Texte, keine
    Verbatim-Wiedergabe der Frage).

    `person_context.display_name` und `.session_id` werden NIE
    uebernommen, nur die reine Ja/Nein-Aussage `known` -- als
    `person_known` im Ausgabeschema.
    """
    facts = getattr(answer_brief, "facts", None) or []
    answer_facts = [_scan_fact_text(f.text) for f in facts]
    source_ids = list(
        answer_brief.source_ids() if hasattr(answer_brief, "source_ids") else []
    )

    person_known = False
    if person_context is not None:
        person_known = bool(getattr(person_context, "known", False) if not isinstance(
            person_context, dict) else person_context.get("known", False))

    return RedactedAnswerContext(
        language=language,
        answer_facts=answer_facts,
        source_ids=source_ids,
        allowed_gestures=list(allowed_gesture_names or []),
        interaction_context=RedactedInteractionContext(
            person_known=person_known,
            preferred_form_of_address=preferred_form_of_address,
        ),
    )


def reinsert_display_name(
    text: str, placeholder: str, display_name: Optional[str], consent_granted: bool
) -> str:
    """Gegenstueck zu redact_for_external_llm(): ein Name darf ERST NACH
    der Antworterzeugung wieder eingesetzt werden, und NUR an einer
    zuvor validierten Platzhalterposition, und NUR bei vorliegender
    Einwilligung (Auftrag 1.7, letzter Satz). Kein Freitext-Ersetzen --
    wenn der Platzhalter im Text nicht vorkommt, passiert nichts (kein
    Name wird an einer unerwarteten Stelle eingefuegt)."""
    if not consent_granted or not display_name:
        return text
    if placeholder not in text:
        return text
    return text.replace(placeholder, display_name)
