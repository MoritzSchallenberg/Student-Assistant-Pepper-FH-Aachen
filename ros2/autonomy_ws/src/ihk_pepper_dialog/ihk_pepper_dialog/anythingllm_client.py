"""
Robuster Wrapper um apps/web/llm/anythingllm.py (bleibt unveraendert
erhalten, siehe Auftrag 3.1) -- ergaenzt Timeout, Retries mit Backoff,
Fehlerklassen, Antwort-Validierung, Workspace-Auswahl, Health-Check.

Loggt NIEMALS den API-Token (auch nicht bei Fehlern -- die Basisklasse
haelt ihn nur im Authorization-Header, wir geben hier nirgends
self.headers/self.api_token aus).
"""
import os
import sys
import time
import logging

_FLASK_WRAPPER_PATH = os.environ.get(
    "PEPPER_FLASK_WRAPPER_PATH",
    "/home/canvastino/Schreibtisch/Pepper/apps/web",
)
if _FLASK_WRAPPER_PATH not in sys.path:
    sys.path.insert(0, _FLASK_WRAPPER_PATH)

from llm.anythingllm import anything_llm_helper  # noqa: E402
import requests  # noqa: E402

logger = logging.getLogger(__name__)


class AnythingLLMError(Exception):
    pass


class AnythingLLMTimeoutError(AnythingLLMError):
    pass


class AnythingLLMConnectionError(AnythingLLMError):
    pass


class AnythingLLMResponseError(AnythingLLMError):
    pass


class RobustAnythingLLMClient:
    def __init__(self, base_url: str, api_token: str, workspace: str = "",
                 timeout_s: float = 15.0, max_retries: int = 2, backoff_s: float = 1.0):
        self._helper = anything_llm_helper(base_url, api_token)
        self._helper.base_url = base_url
        self.workspace = workspace
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s

    def health_check(self) -> bool:
        """Nicht-blockierender Check, ob die AnythingLLM-Instanz erreichbar
        ist. Wirft nie -- fuer SystemHealth-Reporting gedacht."""
        try:
            resp = requests.get(
                f"{self._helper.base_url}/workspaces",
                headers=self._helper.headers, timeout=3.0,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def ask(self, message: str, mode: str = "chat", workspace: str = None) -> str:
        """Schickt eine Nachricht, mit Retries+Backoff. Wirft eine der
        AnythingLLMError-Unterklassen bei endgueltigem Fehlschlag --
        Aufrufer (DialogManager) faengt das ab und nutzt den Offline-
        Fallback (feste Antwort statt Absturz)."""
        ws = workspace or self.workspace
        if not ws:
            raise AnythingLLMError(
                "Kein AnythingLLM-Workspace konfiguriert "
                "(ANYTHINGLLM_WORKSPACE in .env setzen)"
            )

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                url = f"{self._helper.base_url}/workspace/{ws}/chat"
                headers = self._helper.headers.copy()
                headers["Content-Type"] = "application/json"
                resp = requests.post(
                    url, headers=headers,
                    json={"message": message, "mode": mode},
                    timeout=self.timeout_s,
                )
                if resp.status_code != 200:
                    raise AnythingLLMResponseError(
                        f"AnythingLLM antwortete mit HTTP {resp.status_code}"
                    )
                data = resp.json()
                text = data.get("textResponse")
                if not text:
                    raise AnythingLLMResponseError(
                        f"Unerwartete Antwortstruktur (Felder: {list(data.keys())})"
                    )
                return text
            except requests.Timeout as e:
                last_error = AnythingLLMTimeoutError(str(e))
            except requests.ConnectionError as e:
                last_error = AnythingLLMConnectionError(str(e))
            except AnythingLLMResponseError as e:
                last_error = e
            except Exception as e:
                last_error = AnythingLLMError(str(e))

            if attempt < self.max_retries:
                sleep_s = self.backoff_s * (2 ** attempt)
                logger.warning(
                    f"AnythingLLM-Anfrage fehlgeschlagen (Versuch {attempt + 1}/"
                    f"{self.max_retries + 1}): {last_error} -- retry in {sleep_s:.1f}s"
                )
                time.sleep(sleep_s)

        raise last_error
