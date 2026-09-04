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
            log_full_prompts=os.environ.get(f"{prefix}_LOG_FULL_PROMPTS", "false").lower() == "true",
        )


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
            flask_wrapper_path = os.environ.get(
                "PEPPER_FLASK_WRAPPER_PATH",
                "/home/canvastino/Schreibtisch/Pepper/apps/web",
            )
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
        import requests
        try:
            resp = requests.get(f"{self.config.url.rstrip('/')}/models", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False
