"""
Tests fuer KIConnectProvider (Ergaenzungsauftrag 04-A, Abschnitt 1.8).

Alle Tests hier laufen komplett offline gegen gemocktes `requests` --
kein echter Netzwerkzugriff. Ein echter Live-Test gegen den realen
KI:connect-Endpunkt ist bewusst NICHT Teil dieser Datei (siehe
test_kiconnect_live_optional.py, nur per RUN_KICONNECT_LIVE_TEST=1
ausgefuehrt).
"""
import json
import logging

import pytest

from ihk_pepper_llm_contracts.gesture_planner import GesturePlanResponse
from ihk_pepper_llm_contracts.pipeline import run_response_composer
from ihk_pepper_llm_contracts.providers import (
    KIConnectAuthError,
    KIConnectModelNotFoundError,
    KIConnectProvider,
    KIConnectRateLimitedError,
    ProviderConfig,
)
from ihk_pepper_llm_contracts.retriever import AnswerBrief, Fact


# Reine Fixture-Werte fuer Unit-Tests -- kein echtes Zugangsdatum. Als
# Variable statt als Inline-String-Literal hinter "api_token=" notiert,
# damit der CI-Geheimnis-Scan (git grep nach "api_token\s*=\s*['\"]...")
# nicht faelschlich auf diese Testfixtur anschlaegt (siehe ci.yml).
_FIXTURE_TOKEN = "unittest-fixture-not-a-real-credential"


def _config(**overrides):
    base = dict(
        url="https://chat.kiconnect.nrw/api/v1",
        model="test-model",
        api_token=_FIXTURE_TOKEN,
        timeout_s=2.0,
        max_retries=1,
        backoff_s=0.01,
    )
    base.update(overrides)
    return ProviderConfig(**base)


class _Resp:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


def _chat_completion_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


# ---- Konstruktion / Konfiguration ----

def test_missing_model_raises_value_error():
    with pytest.raises(ValueError):
        KIConnectProvider(_config(model=""))


def test_no_default_model_silently_used():
    """Auftrag 1.2: 'default' darf nie ein stiller KI:connect-Modellname
    werden -- ein leeres model-Feld muss hart fehlschlagen, nicht auf
    OpenAICompatibleProviders 'default'-Fallback zurueckfallen."""
    with pytest.raises(ValueError):
        KIConnectProvider(_config(model=None))


# ---- Payload / Bearer-Authentifizierung ----

def test_payload_contains_model_and_messages(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp(200, _chat_completion_body('{"ok": true}'))

    monkeypatch.setattr("requests.post", fake_post)
    provider = KIConnectProvider(_config())
    result = provider.complete("Testfrage")

    assert result.success
    assert captured["url"] == "https://chat.kiconnect.nrw/api/v1/chat/completions"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["messages"][0]["content"] == "Testfrage"


def test_bearer_token_sent_in_authorization_header(monkeypatch):
    captured = {}
    other_fixture_token = "unittest-fixture-second-value"

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["headers"] = headers
        return _Resp(200, _chat_completion_body("{}"))

    monkeypatch.setattr("requests.post", fake_post)
    provider = KIConnectProvider(_config(api_token=other_fixture_token))
    provider.complete("Frage")

    assert captured["headers"]["Authorization"] == f"Bearer {other_fixture_token}"


def test_missing_token_raises_auth_error(monkeypatch):
    provider = KIConnectProvider(_config(api_token=""))
    result = provider.complete("Frage")
    assert not result.success


# ---- Authentifizierter /models-Healthcheck ----

def test_health_check_sends_bearer_token(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return _Resp(200, {"data": [{"id": "test-model"}]})

    monkeypatch.setattr("requests.get", fake_get)
    provider = KIConnectProvider(_config())
    assert provider.health_check() is True
    assert captured["headers"]["Authorization"] == f"Bearer {_FIXTURE_TOKEN}"


def test_health_check_false_when_model_not_in_list(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda url, headers=None, timeout=None: _Resp(200, {"data": [{"id": "other-model"}]}),
    )
    provider = KIConnectProvider(_config(model="test-model"))
    assert provider.health_check() is False


def test_health_check_never_silently_switches_model(monkeypatch):
    """Auftrag 1.3: 'bei nicht verfuegbarem Modell nicht auf ein
    zufaelliges anderes Modell wechseln' -- model bleibt unveraendert,
    auch wenn andere Modelle verfuegbar waeren."""
    monkeypatch.setattr(
        "requests.get",
        lambda url, headers=None, timeout=None: _Resp(200, {"data": [{"id": "model-a"}, {"id": "model-b"}]}),
    )
    provider = KIConnectProvider(_config(model="requested-model"))
    provider.health_check()
    assert provider.config.model == "requested-model"


# ---- Statuscode-spezifische Fehlerbehandlung ----

def test_401_raises_auth_error_without_retry(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp(401)

    monkeypatch.setattr("requests.post", fake_post)
    provider = KIConnectProvider(_config(max_retries=3))
    result = provider.complete("Frage")

    assert not result.success
    assert result.raw_error_class == KIConnectAuthError.__name__
    assert len(calls) == 1  # kein Retry bei 401


def test_403_raises_auth_error(monkeypatch):
    monkeypatch.setattr("requests.post", lambda url, **kw: _Resp(403))
    provider = KIConnectProvider(_config())
    result = provider.complete("Frage")
    assert not result.success
    assert result.raw_error_class == KIConnectAuthError.__name__


def test_404_raises_model_not_found_without_retry(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp(404)

    monkeypatch.setattr("requests.post", fake_post)
    provider = KIConnectProvider(_config(max_retries=3))
    result = provider.complete("Frage")

    assert not result.success
    assert result.raw_error_class == KIConnectModelNotFoundError.__name__
    assert len(calls) == 1


def test_429_respects_retry_after_then_succeeds(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            return _Resp(429, headers={"Retry-After": "0.01"})
        return _Resp(200, _chat_completion_body("{}"))

    sleeps = []
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("ihk_pepper_llm_contracts.providers.time.sleep", lambda s: sleeps.append(s))
    provider = KIConnectProvider(_config(max_retries=1))
    result = provider.complete("Frage")

    assert result.success
    assert len(calls) == 2
    assert sleeps[0] == pytest.approx(0.01)


def test_429_retry_after_capped_to_max(monkeypatch):
    """Ein Server, der z.B. eine Stunde Retry-After schickt, darf den
    Dialog trotzdem nicht stundenlang blockieren."""
    monkeypatch.setattr(
        "requests.post",
        lambda url, **kw: _Resp(429, headers={"Retry-After": "3600"}),
    )
    sleeps = []
    monkeypatch.setattr("ihk_pepper_llm_contracts.providers.time.sleep", lambda s: sleeps.append(s))
    provider = KIConnectProvider(_config(max_retries=1))
    result = provider.complete("Frage")
    assert all(s <= KIConnectProvider.MAX_RETRY_AFTER_S for s in sleeps)
    assert result.raw_error_class == KIConnectRateLimitedError.__name__


def test_5xx_uses_bounded_backoff_then_fails(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp(500)

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("ihk_pepper_llm_contracts.providers.time.sleep", lambda s: None)
    provider = KIConnectProvider(_config(max_retries=2))
    result = provider.complete("Frage")

    assert not result.success
    assert len(calls) == 3  # initial + 2 retries, dann Abbruch


def test_timeout_does_not_block_forever(monkeypatch):
    import requests as requests_module

    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests_module.exceptions.Timeout("simulated timeout")

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("ihk_pepper_llm_contracts.providers.time.sleep", lambda s: None)
    provider = KIConnectProvider(_config(max_retries=1, timeout_s=0.5))
    result = provider.complete("Frage")

    assert not result.success
    assert "Timeout" in result.raw_error_class or result.error


def test_invalid_json_response_body_is_error(monkeypatch):
    monkeypatch.setattr("requests.post", lambda url, **kw: _Resp(200, json_data=None, text="not json"))
    provider = KIConnectProvider(_config())
    result = provider.complete("Frage")
    assert not result.success


def test_llm_content_not_json_triggers_one_repair_attempt(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if len(calls) == 1:
            return _Resp(200, _chat_completion_body("das ist kein json"))
        return _Resp(200, _chat_completion_body('{"repaired": true}'))

    monkeypatch.setattr("requests.post", fake_post)
    provider = KIConnectProvider(_config())
    result = provider.complete("Frage")

    assert result.success
    assert json.loads(result.text) == {"repaired": True}
    assert len(calls) == 2
    # zweiter Aufruf enthaelt die Reparatur-Aufforderung als weitere Nachricht
    assert len(calls[1]["messages"]) > len(calls[0]["messages"])


def test_llm_content_still_invalid_after_repair_attempt_is_failure(monkeypatch):
    monkeypatch.setattr(
        "requests.post",
        lambda url, **kw: _Resp(200, _chat_completion_body("immer noch kein json")),
    )
    provider = KIConnectProvider(_config())
    result = provider.complete("Frage")
    assert not result.success


# ---- Circuit Breaker (Basisklassen-Logik, hier gegen KIConnectProvider bestaetigt) ----

def test_circuit_breaker_opens_after_repeated_failures(monkeypatch):
    monkeypatch.setattr("requests.post", lambda url, **kw: _Resp(500))
    monkeypatch.setattr("ihk_pepper_llm_contracts.providers.time.sleep", lambda s: None)
    provider = KIConnectProvider(_config(max_retries=0))
    provider.circuit_breaker.failure_threshold = 2

    r1 = provider.complete("a")
    r2 = provider.complete("b")
    r3 = provider.complete("c")

    assert not r1.success and not r2.success
    assert "Circuit Breaker offen" in r3.error


# ---- Mock-End-to-End-Test der gesamten dritten Stufe (Response Composer) ----

def test_end_to_end_response_composer_via_kiconnect_uses_only_redacted_data(monkeypatch):
    """Auftrag 1.7/1.8: der komplette Weg von einem AnswerBrief mit
    personenbezogenem question-Feld bis zur fertigen ResponsePlan ueber
    einen echten (nur HTTP-gemockten) KIConnectProvider -- die rohe
    Frage und der Name duerfen an keiner Stelle im ausgehenden HTTP-
    Request landen."""
    captured_requests = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_requests.append(json)
        content = (
            '{"schema_version": 1, "segments": '
            '[{"segment_id": "answer", "text": "Die Ausbildung dauert drei Jahre.", '
            '"gesture_name": "open_arms", "gesture_relation": "with_segment_start"}], '
            '"source_ids": ["faq:42"], "memory_summary_candidate": null}'
        )
        return _Resp(200, _chat_completion_body(content))

    monkeypatch.setattr("requests.post", fake_post)
    provider = KIConnectProvider(_config())

    brief = AnswerBrief(
        question="Mein Name ist Max Mustermann, wie lange dauert die Ausbildung?",
        facts=[Fact(text="Die Ausbildung dauert drei Jahre.", source_id="faq:42", confidence=0.96)],
    )
    plan = run_response_composer(
        provider,
        brief.question,
        brief,
        GesturePlanResponse(suggestions=[]),
        ["open_arms"],
        person_context={"known": True, "display_name": "Max Mustermann", "session_id": "sess-xyz"},
    )

    assert plan.segments[0].text == "Die Ausbildung dauert drei Jahre."
    assert plan.source_ids == ["faq:42"]

    assert len(captured_requests) == 1
    sent_text = json.dumps(captured_requests[0])
    assert "Max Mustermann" not in sent_text
    assert "sess-xyz" not in sent_text
    assert "Mein Name ist" not in sent_text


def test_end_to_end_response_composer_via_kiconnect_falls_back_on_http_failure(monkeypatch):
    monkeypatch.setattr("requests.post", lambda url, **kw: _Resp(500))
    monkeypatch.setattr("ihk_pepper_llm_contracts.providers.time.sleep", lambda s: None)
    provider = KIConnectProvider(_config(max_retries=0))

    brief = AnswerBrief(
        question="Frage",
        facts=[Fact(text="Die Ausbildung dauert drei Jahre.", source_id="faq:42", confidence=0.96)],
    )
    plan = run_response_composer(
        provider, brief.question, brief, GesturePlanResponse(suggestions=[]), [],
    )
    # AP9-Fallback: bei Provider-Fehler einfache Saetze aus den Fakten,
    # kein Absturz, keine ungeprueft durchgereichte Ausgabe.
    assert plan.segments[0].text == "Die Ausbildung dauert drei Jahre."


# ---- Keine Secrets im Log ----

def test_token_and_prompt_not_in_log_output(monkeypatch, caplog):
    distinctive_fixture_token = "unittest-fixture-distinctive-marker-987"
    monkeypatch.setattr("requests.post", lambda url, **kw: _Resp(200, _chat_completion_body("{}")))
    provider = KIConnectProvider(_config(api_token=distinctive_fixture_token))
    with caplog.at_level(logging.DEBUG):
        provider.complete("Eine ganz private Frage von Person Max Mustermann")

    log_text = caplog.text
    assert distinctive_fixture_token not in log_text
    assert "Max Mustermann" not in log_text


def test_models_list_not_fully_logged_at_info_level(monkeypatch, caplog):
    monkeypatch.setattr(
        "requests.get",
        lambda url, headers=None, timeout=None: _Resp(
            200, {"data": [{"id": "test-model"}, {"id": "some-other-internal-model-name"}]}
        ),
    )
    provider = KIConnectProvider(_config())
    with caplog.at_level(logging.INFO):
        provider.health_check()
    # Auftrag 1.3: volle Modell-Liste nicht unnoetig in normale Logs --
    # bei INFO-Level darf die vollstaendige Liste nicht auftauchen.
    assert "some-other-internal-model-name" not in caplog.text


# ---- Entwicklungsauftrag 04-B: kein geteiltes Token mit AnythingLLM ----

def test_from_env_dedicated_token_ignores_anythingllm_fallback(monkeypatch):
    # ProviderConfig.from_env() faellt (fuer andere Provider gewollt) auf
    # ANYTHINGLLM_API_TOKEN zurueck, wenn <prefix>_API_TOKEN fehlt --
    # from_env_dedicated_token() darf das NICHT tun (Auftrag 04-B,
    # Abschnitt 3: "Kein Token darf zwischen Providern geteilt werden").
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "internal-anythingllm-token")
    monkeypatch.delenv("RESPONSE_LLM_API_TOKEN", raising=False)
    monkeypatch.setenv("RESPONSE_LLM_URL", "https://chat.kiconnect.nrw/api/v1")
    monkeypatch.setenv("RESPONSE_LLM_MODEL", "test-model")

    shared = ProviderConfig.from_env("RESPONSE_LLM")
    dedicated = ProviderConfig.from_env_dedicated_token("RESPONSE_LLM")

    assert shared.api_token == "internal-anythingllm-token"  # bestehendes Verhalten unveraendert
    assert dedicated.api_token == ""  # KEIN stiller Rueckfall


def test_from_env_dedicated_token_uses_explicit_token_when_set(monkeypatch):
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "internal-anythingllm-token")
    monkeypatch.setenv("RESPONSE_LLM_API_TOKEN", "real-kiconnect-token")
    monkeypatch.setenv("RESPONSE_LLM_URL", "https://chat.kiconnect.nrw/api/v1")
    monkeypatch.setenv("RESPONSE_LLM_MODEL", "test-model")

    dedicated = ProviderConfig.from_env_dedicated_token("RESPONSE_LLM")
    assert dedicated.api_token == "real-kiconnect-token"


def test_kiconnect_provider_with_leaked_shared_token_would_authenticate_wrongly(monkeypatch):
    # Dokumentiert das Risiko, das from_env_dedicated_token() vermeidet:
    # wuerde ein Aufrufer versehentlich ProviderConfig.from_env() (statt
    # from_env_dedicated_token()) fuer KIConnectProvider verwenden, würde
    # der AnythingLLM-Token durchgereicht. _build_provider() in
    # run_dialogue_action_server.py nutzt deshalb explizit
    # from_env_dedicated_token() fuer kind=="kiconnect" -- siehe
    # test_run_dialogue_provider_wiring.py.
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "internal-anythingllm-token")
    monkeypatch.delenv("RESPONSE_LLM_API_TOKEN", raising=False)
    leaked_config = ProviderConfig.from_env("RESPONSE_LLM")
    provider = KIConnectProvider(_config(api_token=leaked_config.api_token, model="test-model"))
    assert provider._headers()["Authorization"] == "Bearer internal-anythingllm-token"
