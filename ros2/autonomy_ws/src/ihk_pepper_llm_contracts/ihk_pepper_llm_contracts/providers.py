"""
Austauschbare LLM-Provider-Schnittstelle fuer alle drei Pipeline-Stufen
(Entwicklungsauftrag 3, AP2). Kein ROS -- reine Python-Klassen, injizierbar
in pipeline.py. Jede der drei Rollen (Knowledge/Gesture/Response) bekommt
ihre EIGENE Provider-Instanz, auch wenn alle auf denselben Endpunkt
zeigen (Auftrag: "muessen aber technisch getrennt konfigurierbar bleiben").

Wiederverwendet ihk_pepper_dialog/anythingllm_client.py::RobustAnythingLLMClient
als Transport fuer AnythingLLMProvider, statt die Retry-/Timeout-/
Fehlerbehandlungslogik zu duplizieren.
"""
import hashlib
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_S = 1.0
DEFAULT_MAX_INPUT_CHARS = 8000
DEFAULT_MAX_OUTPUT_CHARS = 4000


@dataclass
class ProviderResult:
    success: bool
    text: str = ""
    error: str = ""
    latency_s: float = 0.0
    raw_error_class: str = ""
    truncated_input: bool = False
    truncated_output: bool = False


@dataclass
class ProviderConfig:
    """Konfiguration einer einzelnen LLM-Rolle (Knowledge/Gesture/Response).
    Token/Passwort NUR ueber Umgebungsvariablen -- niemals hier als
    Default-Wert hartcodiert."""

    url: str = ""
    model: str = ""
    workspace: str = ""
    api_token: str = ""
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_s: float = DEFAULT_BACKOFF_S
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    log_full_prompts: bool = False  # bewusst opt-in, siehe Moduldocstring

    @classmethod
    def from_env(cls, prefix: str) -> "ProviderConfig":
        """prefix z.B. 'KNOWLEDGE_LLM' liest KNOWLEDGE_LLM_URL/_MODEL/
        _WORKSPACE (Auftrag-Vorgabe, exakte Namen). Token bewusst NICHT
        Teil des benannten Schemas im Auftrag -- gelesen aus
        '<prefix>_API_TOKEN', faellt sonst auf die geteilte
        ANYTHINGLLM_API_TOKEN zurueck (ein Token fuer alle drei Stufen,
        solange sie denselben Endpunkt nutzen)."""
        return cls(
            url=os.environ.get(f"{prefix}_URL", ""),
            model=os.environ.get(f"{prefix}_MODEL", ""),
            workspace=os.environ.get(f"{prefix}_WORKSPACE", ""),
            api_token=os.environ.get(
                f"{prefix}_API_TOKEN", os.environ.get("ANYTHINGLLM_API_TOKEN", "")
            ),
            timeout_s=float(os.environ.get(f"{prefix}_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
            max_retries=int(os.environ.get(f"{prefix}_MAX_RETRIES", DEFAULT_MAX_RETRIES)),
            # Ergaenzungsauftrag 04-A, Abschnitt 1.2: RESPONSE_LLM_MAX_INPUT_CHARS/
            # RESPONSE_LLM_MAX_OUTPUT_CHARS explizit konfigurierbar --
            # vorher nur als Dataclass-Default moeglich, nicht aus der
            # Umgebung lesbar.
            max_input_chars=int(os.environ.get(f"{prefix}_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS)),
            max_output_chars=int(os.environ.get(f"{prefix}_MAX_OUTPUT_CHARS", DEFAULT_MAX_OUTPUT_CHARS)),
            log_full_prompts=os.environ.get(f"{prefix}_LOG_FULL_PROMPTS", "false").lower() == "true",
        )

    @classmethod
    def from_env_dedicated_token(cls, prefix: str) -> "ProviderConfig":
        """Wie from_env(), aber OHNE den Rueckfall auf die geteilte
        ANYTHINGLLM_API_TOKEN-Variable (Entwicklungsauftrag 04-B,
        Abschnitt 3: "Kein Token darf zwischen Providern geteilt werden"
        / "Das System darf niemals automatisch ANYTHINGLLM_API_TOKEN an
        KI:connect senden"). Fuer Provider, die ein STRIKT eigenes Token
        brauchen -- aktuell nur KIConnectProvider. Fehlt
        '<prefix>_API_TOKEN', bleibt api_token bewusst leer statt
        irgendeinen anderen Wert zu erraten; der Provider selbst muss das
        dann als Konfigurationsfehler behandeln (siehe
        KIConnectProvider._headers())."""
        config = cls.from_env(prefix)
        config.api_token = os.environ.get(f"{prefix}_API_TOKEN", "")
        return config


class CircuitBreaker:
    """Reiner Zustandsautomat -- schliesst nach `failure_threshold`
    aufeinanderfolgenden Fehlern fuer `cooldown_s`, danach ein einzelner
    Testversuch (Half-Open), der bei Erfolg zuruecksetzt. `time_fn`
    injizierbar, damit Tests keine echte Zeit abwarten muessen."""

    def __init__(self, failure_threshold: int = 3, cooldown_s: float = 30.0,
                 time_fn: Callable[[], float] = time.time):
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._time_fn = time_fn
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None

    def allow_request(self) -> bool:
        if self._opened_at is None:
            return True
        if (self._time_fn() - self._opened_at) >= self.cooldown_s:
            return True  # Half-Open: ein Testversuch wird durchgelassen
        return False

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = self._time_fn()

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None and not self.allow_request()


def _truncate(text: str, max_chars: int):
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _prompt_log_summary(prompt: str, log_full: bool) -> str:
    """Niemals volle personenbezogene Prompts standardmaessig loggen --
    nur Laenge+Hash, ausser explizit per Config opt-in."""
    if log_full:
        return prompt
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    return f"<{len(prompt)} Zeichen, sha256:{digest}>"


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.circuit_breaker = CircuitBreaker()

    def complete(self, prompt: str) -> ProviderResult:
        """Oeffentlicher Einstiegspunkt -- kapselt Groessenbegrenzung,
        Circuit Breaker und Latenzmessung einheitlich fuer alle Provider.
        Unterklassen implementieren nur _call()."""
        truncated_prompt, was_truncated_in = _truncate(prompt, self.config.max_input_chars)

        if not self.circuit_breaker.allow_request():
            return ProviderResult(
                success=False,
                error=f"{self.name}: Circuit Breaker offen (zu viele Fehlschlaege in Folge)",
                truncated_input=was_truncated_in,
            )

        logger.debug(
            f"{self.name}: Anfrage ({_prompt_log_summary(truncated_prompt, self.config.log_full_prompts)})"
        )
        t0 = time.time()
        try:
            result = self._call(truncated_prompt)
        except Exception as e:
            latency = time.time() - t0
            self.circuit_breaker.record_failure()
            return ProviderResult(
                success=False, error=str(e), raw_error_class=type(e).__name__,
                latency_s=latency, truncated_input=was_truncated_in,
            )
        latency = time.time() - t0
        result.latency_s = latency
        result.truncated_input = was_truncated_in or result.truncated_input

        if result.success:
            text, out_truncated = _truncate(result.text, self.config.max_output_chars)
            result.text = text
            result.truncated_output = out_truncated
            self.circuit_breaker.record_success()
        else:
            self.circuit_breaker.record_failure()
        return result

    @abstractmethod
    def _call(self, prompt: str) -> ProviderResult:
        """Fuehrt den eigentlichen Aufruf aus. Darf werfen -- complete()
        faengt das ab. Latenz/Truncation werden von complete() ergaenzt,
        nicht hier."""
        raise NotImplementedError

    def health_check(self) -> bool:
        return False


class MockLLMProvider(LLMProvider):
    """Fuer Tests -- konfigurierbare feste oder regelbasierte Antworten,
    kein Netzwerkzugriff."""

    name = "mock"

    def __init__(self, config: Optional[ProviderConfig] = None,
                 response_fn: Optional[Callable[[str], str]] = None,
                 fixed_response: str = "{}", fail: bool = False,
                 latency_s: float = 0.0):
        super().__init__(config or ProviderConfig())
        self.response_fn = response_fn
        self.fixed_response = fixed_response
        self.fail = fail
        self.simulated_latency_s = latency_s
        self.calls = []  # Aufrufliste fuer Testassertions

    def _call(self, prompt: str) -> ProviderResult:
        self.calls.append(prompt)
        if self.simulated_latency_s:
            time.sleep(self.simulated_latency_s)
        if self.fail:
            raise RuntimeError("MockLLMProvider: simulierter Fehler")
        text = self.response_fn(prompt) if self.response_fn else self.fixed_response
        return ProviderResult(success=True, text=text)

    def health_check(self) -> bool:
        return not self.fail


class OfflineFallbackProvider(LLMProvider):
    """Wirft NIE -- liefert immer einen sicheren, generischen Text-
    Baustein. Letzte Instanz, wenn kein anderer Provider verfuegbar ist."""

    name = "offline_fallback"

    def __init__(self, config: Optional[ProviderConfig] = None):
        super().__init__(config or ProviderConfig())

    def _call(self, prompt: str) -> ProviderResult:
        return ProviderResult(
            success=True,
            text='{"fallback": true, "reason": "offline_no_llm_configured"}',
        )

    def health_check(self) -> bool:
        return True


def _find_flask_wrapper_path() -> str:
    """Siehe ihk_pepper_bridge/pepper_client.py::_find_flask_wrapper_path()
    -- bewusst eigenstaendige Kopie (kein Cross-Import fuer eine kurze
    Pfadsuche, gleiches Prinzip wie embedding_backend.py).
    PEPPER_FLASK_WRAPPER_PATH hat Vorrang, sonst wird 'apps/web' vom
    eigenen Verzeichnis aus nach oben gesucht (Entwicklungsauftrag 04-B,
    AP0: keine absoluten Entwicklerpfade im Laufzeitcode)."""
    env_value = os.environ.get("PEPPER_FLASK_WRAPPER_PATH")
    if env_value:
        return env_value
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(12):
        candidate = os.path.join(current, "apps", "web")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RuntimeError(
        "PEPPER_FLASK_WRAPPER_PATH ist nicht gesetzt und 'apps/web' wurde "
        "beim automatischen Suchen nicht gefunden -- bei getrennter "
        "Installation muss PEPPER_FLASK_WRAPPER_PATH explizit gesetzt werden."
    )


class AnythingLLMProvider(LLMProvider):
    """Ruft AnythingLLM direkt ueber apps/web/llm/anythingllm.py auf --
    NICHT ueber ihk_pepper_dialog/anythingllm_client.py::RobustAnythingLLMClient,
    obwohl dessen Retry-/Timeout-Verhalten hier bewusst identisch
    nachgebildet wird: ein Import von ihk_pepper_llm_contracts (ROS-frei,
    von ihk_pepper_dialog als Bibliothek eingebunden) INS
    ihk_pepper_dialog-Paket wuerde eine zirkulaere Paketabhaengigkeit
    erzeugen (ihk_pepper_dialog importiert bereits ihk_pepper_llm_contracts
    fuer die Pipeline, siehe run_dialogue_action_server.py). Beide Stellen
    nutzen daher unabhaengig voneinander denselben, unveraenderten
    apps/web/llm/anythingllm.py-Helper."""

    name = "anythingllm"

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._helper = None

    def _ensure_helper(self):
        if self._helper is None:
            import sys
            flask_wrapper_path = _find_flask_wrapper_path()
            if flask_wrapper_path not in sys.path:
                sys.path.insert(0, flask_wrapper_path)
            from llm.anythingllm import anything_llm_helper
            self._helper = anything_llm_helper(self.config.url, self.config.api_token)
            self._helper.base_url = self.config.url
        return self._helper

    def _call(self, prompt: str) -> ProviderResult:
        import requests

        if not self.config.workspace:
            raise RuntimeError(
                f"kein Workspace fuer {self.name} konfiguriert (workspace in ProviderConfig)"
            )
        helper = self._ensure_helper()
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                url = f"{helper.base_url}/workspace/{self.config.workspace}/chat"
                headers = helper.headers.copy()
                headers["Content-Type"] = "application/json"
                resp = requests.post(
                    url, headers=headers, json={"message": prompt, "mode": "chat"},
                    timeout=self.config.timeout_s,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                data = resp.json()
                text = data.get("textResponse")
                if not text:
                    raise RuntimeError(f"unerwartete Antwortstruktur (Felder: {list(data.keys())})")
                return ProviderResult(success=True, text=text)
            except Exception as e:
                last_error = e
            if attempt < self.config.max_retries:
                time.sleep(self.config.backoff_s * (2 ** attempt))
        raise last_error

    def health_check(self) -> bool:
        try:
            helper = self._ensure_helper()
            import requests
            resp = requests.get(f"{helper.base_url}/workspaces", headers=helper.headers, timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False


class OpenAICompatibleProvider(LLMProvider):
    """Generischer HTTP-Provider gegen einen OpenAI-kompatiblen
    Chat-Completions-Endpunkt (z.B. lokal gehostetes Modell). Bewusst
    minimal -- kein SDK, nur `requests` (bereits Projektabhaengigkeit)."""

    name = "openai_compatible"

    def _call(self, prompt: str) -> ProviderResult:
        import requests

        if not self.config.url:
            raise RuntimeError("kein url in ProviderConfig gesetzt")

        headers = {"Content-Type": "application/json"}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"

        payload = {
            "model": self.config.model or "default",
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = requests.post(
            f"{self.config.url.rstrip('/')}/chat/completions",
            headers=headers, json=payload, timeout=self.config.timeout_s,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"unerwartete Antwortstruktur (Felder: {list(data.keys())})") from e
        return ProviderResult(success=True, text=text)

    def health_check(self) -> bool:
        # Ergaenzungsauftrag 04-A, Abschnitt 1.3: "auch der Healthcheck
        # muss den Bearer-Token mitsenden" -- die urspruengliche Fassung
        # rief /models komplett unauthentifiziert auf, was gegen jeden
        # Endpunkt fehlschlaegt, der (wie KI:connect) Auth auch fuer
        # /models verlangt.
        import requests
        headers = {}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        try:
            resp = requests.get(
                f"{self.config.url.rstrip('/')}/models", headers=headers, timeout=3.0
            )
            return resp.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------
# KI:connect (FH Aachen) -- Ergaenzungsauftrag 04-A, Abschnitt 1.
# ---------------------------------------------------------------------

class KIConnectAuthError(Exception):
    """401/403 -- Zugang oder Berechtigung falsch. Wird NICHT wiederholt
    versucht (ein falscher Token wird durch Wiederholen nicht richtig)."""


class KIConnectModelNotFoundError(Exception):
    """404, oder das konfigurierte Modell fehlt in /models -- Endpunkt
    oder Modellname falsch. Wird NICHT wiederholt versucht und wechselt
    NIE automatisch auf ein anderes verfuegbares Modell."""


class KIConnectRateLimitedError(Exception):
    """429 nach Ausschoepfen der Retry-After-Wartezeit(en)."""


class KIConnectProvider(OpenAICompatibleProvider):
    """LLM 3 (Response Composer) ueber die FH-Aachen-KI:connect-Plattform
    (https://chat.kiconnect.nrw/api/v1), ein OpenAI-kompatibler
    Chat-Completions-Endpunkt. Baut auf OpenAICompatibleProvider auf,
    kapselt aber KI:connect-spezifische Anforderungen (Auftrag 1.2):
    Pflicht-Modellname (kein stilles 'default'), Status-Code-spezifische
    Fehlerbehandlung (401/403/404/429/5xx unterschiedlich behandelt,
    nicht ein generisches 'HTTP != 200'), Modellverfuegbarkeitspruefung
    gegen /models, und ein einzelner JSON-Reparaturversuch, falls das
    Modell keine native strukturierte Ausgabe liefert.

    Sendet NIEMALS personenbezogene Rohdaten -- der Aufrufer (siehe
    pipeline.py::run_response_composer) muss den Prompt bereits durch
    privacy_filter.redact_for_external_llm() geschickt haben; dieser
    Provider selbst prueft das nicht nochmal (Verantwortung liegt an der
    Aufrufstelle, siehe deren Docstring), loggt aber unter keinen
    Umstaenden den vollen Prompt oder den Token (siehe complete() in der
    Basisklasse: _prompt_log_summary() ist bereits Default)."""

    name = "kiconnect"

    # KI:connect-Antworten, deren Inhalt nicht als JSON geparst werden
    # kann, bekommen GENAU EINEN Reparaturversuch (Auftrag 1.4) -- kein
    # unbegrenztes Nachfragen.
    MAX_JSON_REPAIR_ATTEMPTS = 1
    # Obergrenze fuer eine einzelne Retry-After-Wartezeit (Sekunden) --
    # ein Server, der z.B. "Retry-After: 3600" schickt, soll den Dialog
    # trotzdem nicht stundenlang blockieren (Auftrag: "laufenden Dialog
    # nicht unbegrenzt blockieren").
    MAX_RETRY_AFTER_S = 20.0

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        if not self.config.model:
            # Auftrag 1.2: "Keine Modellnamen hardcodieren und nicht
            # 'default' als stillen KI:connect-Modellnamen verwenden."
            # -- ein leerer Modellname ist ein Konfigurationsfehler,
            # kein Fall fuer einen stillen Fallback.
            raise ValueError(
                "KIConnectProvider: RESPONSE_LLM_MODEL ist nicht gesetzt. "
                "Modellnamen ueber GET /models ermitteln und explizit "
                "eintragen -- kein stiller 'default'-Fallback erlaubt."
            )

    def _headers(self) -> dict:
        if not self.config.api_token:
            raise KIConnectAuthError(
                "KIConnectProvider: kein RESPONSE_LLM_API_TOKEN gesetzt."
            )
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
        }

    def list_models(self) -> list:
        """Rohe Modellliste von /models, authentifiziert. Wirft bei
        Auth-Fehlern eine KIConnectAuthError statt generisch False
        zurueckzugeben -- health_check() faengt das ab, andere
        Aufrufer wollen den Grund kennen."""
        import requests

        resp = requests.get(
            f"{self.config.url.rstrip('/')}/models",
            headers=self._headers(), timeout=self.config.timeout_s,
        )
        if resp.status_code in (401, 403):
            raise KIConnectAuthError(f"KI:connect /models: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise RuntimeError(f"KI:connect /models: HTTP {resp.status_code}")
        data = resp.json()
        # Verschiedene OpenAI-kompatible Server liefern entweder
        # {"data": [{"id": ...}, ...]} oder direkt eine Liste.
        if isinstance(data, dict) and "data" in data:
            return [m.get("id") for m in data["data"] if isinstance(m, dict) and "id" in m]
        if isinstance(data, list):
            return [m.get("id") if isinstance(m, dict) else m for m in data]
        return []

    def model_is_available(self) -> bool:
        """True nur, wenn das konfigurierte Modell tatsaechlich in der
        Liste steht -- niemals 'irgendein Modell war da, also ok'."""
        models = self.list_models()
        available = self.config.model in models
        # Auftrag 1.3: "verfuegbaren Modellnamen nicht vollstaendig in
        # normale Logs schreiben, sofern dies unnoetig ist" -- bei
        # Erfolg reicht eine Ja/Nein-Aussage, die volle Liste nur bei
        # tatsaechlichem Bedarf (DEBUG-Level).
        logger.info(f"{self.name}: Modell '{self.config.model}' verfuegbar: {available}")
        logger.debug(f"{self.name}: vollstaendige /models-Liste: {models}")
        return available

    def health_check(self) -> bool:
        try:
            return self.model_is_available()
        except KIConnectAuthError:
            logger.warning(f"{self.name}: Healthcheck fehlgeschlagen -- Authentifizierung abgelehnt.")
            return False
        except Exception as e:
            logger.warning(f"{self.name}: Healthcheck fehlgeschlagen: {type(e).__name__}")
            return False

    def _post_chat_completion(self, messages: list) -> str:
        """Ein einzelner POST /chat/completions-Versuch mit
        statuscode-spezifischer Behandlung (Auftrag 1.5). Gibt den
        rohen Antworttext zurueck oder wirft eine der KIConnect*-
        Exceptions bzw. eine generische Exception fuer 5xx (von
        complete()s bestehendem Circuit Breaker aufgefangen)."""
        import requests

        last_error: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = requests.post(
                    f"{self.config.url.rstrip('/')}/chat/completions",
                    headers=self._headers(),
                    json={"model": self.config.model, "messages": messages},
                    timeout=self.config.timeout_s,
                )
            except requests.exceptions.Timeout as e:
                last_error = e
                if attempt < self.config.max_retries:
                    time.sleep(self.config.backoff_s * (2 ** attempt))
                    continue
                raise

            if resp.status_code in (401, 403):
                # Auftrag 1.5: "nicht wiederholt probieren" -- ein
                # falscher Token wird durch Warten nicht richtig.
                raise KIConnectAuthError(f"KI:connect: HTTP {resp.status_code} -- Zugang/Berechtigung pruefen.")
            if resp.status_code == 404:
                raise KIConnectModelNotFoundError(
                    f"KI:connect: HTTP 404 -- Modell '{self.config.model}' oder Endpunkt falsch."
                )
            if resp.status_code == 429:
                retry_after = min(
                    float(resp.headers.get("Retry-After", self.config.backoff_s)),
                    self.MAX_RETRY_AFTER_S,
                )
                last_error = KIConnectRateLimitedError(f"KI:connect: HTTP 429, Retry-After={retry_after}s")
                if attempt < self.config.max_retries:
                    time.sleep(retry_after)
                    continue
                raise last_error
            if 500 <= resp.status_code < 600:
                last_error = RuntimeError(f"KI:connect: HTTP {resp.status_code} (Serverfehler)")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.backoff_s * (2 ** attempt))
                    continue
                raise last_error
            if resp.status_code != 200:
                raise RuntimeError(f"KI:connect: HTTP {resp.status_code}: {resp.text[:200]}")

            try:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as e:
                # Ungueltige/unerwartete JSON-Antwort selbst (nicht der
                # LLM-Inhalt) -- kein Wiederholungsversuch sinnvoll,
                # der Server liefert vermutlich strukturell etwas
                # anderes als erwartet.
                raise RuntimeError(f"KI:connect: unerwartete Antwortstruktur ({type(e).__name__})") from e
        raise last_error or RuntimeError("KI:connect: unbekannter Fehler ohne Antwort")

    def _call(self, prompt: str) -> ProviderResult:
        import json as _json

        messages = [{"role": "user", "content": prompt}]
        text = self._post_chat_completion(messages)

        # Auftrag 1.4: "nicht davon ausgehen, dass jedes Modell native
        # JSON-Schemas unterstuetzt" -- lokal parsen, bei Fehler GENAU
        # EINEN begrenzten Reparaturversuch, danach an complete()/die
        # Pipeline den Fallback ueberlassen (raise statt hier selbst
        # einen Fallback-Text zu erfinden -- das bleibt Aufgabe der
        # Pipeline-Stufe, nicht des Providers).
        for _ in range(self.MAX_JSON_REPAIR_ATTEMPTS + 1):
            try:
                _json.loads(text)
                return ProviderResult(success=True, text=text)
            except ValueError:
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": (
                        "Deine letzte Antwort war kein gueltiges JSON. "
                        "Gib AUSSCHLIESSLICH gueltiges JSON zurueck, "
                        "keinen zusaetzlichen Text davor oder danach."
                    )},
                ]
                text = self._post_chat_completion(messages)
        # Nach dem Reparaturversuch immer noch kein gueltiges JSON --
        # als Fehler zurueckgeben, nicht als Erfolg mit kaputtem Text.
        raise RuntimeError("KI:connect: Antwort blieb auch nach einem Reparaturversuch kein gueltiges JSON.")
