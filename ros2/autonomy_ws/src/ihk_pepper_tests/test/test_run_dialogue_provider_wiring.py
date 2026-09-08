"""
Entwicklungsauftrag 04-B: prueft, dass _build_provider() in
run_dialogue_action_server.py fuer kind=="kiconnect" tatsaechlich
ProviderConfig.from_env_dedicated_token() nutzt -- nicht die geteilte
from_env(), die auf ANYTHINGLLM_API_TOKEN zurueckfallen wuerde (siehe
test_kiconnect_provider.py fuer die Provider-/Config-Ebene selbst).
"""
from ihk_pepper_dialog.run_dialogue_action_server import _build_provider
from ihk_pepper_llm_contracts.providers import (
    KIConnectProvider,
    MockLLMProvider,
    OfflineFallbackProvider,
)


def test_kiconnect_provider_never_inherits_anythingllm_token(monkeypatch):
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "internal-anythingllm-token")
    monkeypatch.delenv("RESPONSE_LLM_API_TOKEN", raising=False)
    monkeypatch.setenv("RESPONSE_LLM_URL", "https://chat.kiconnect.nrw/api/v1")
    monkeypatch.setenv("RESPONSE_LLM_MODEL", "test-model")

    provider = _build_provider("kiconnect", "RESPONSE_LLM")

    assert isinstance(provider, KIConnectProvider)
    assert provider.config.api_token == ""  # KEIN stiller Rueckfall auf ANYTHINGLLM_API_TOKEN


def test_kiconnect_provider_uses_its_own_explicit_token(monkeypatch):
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "internal-anythingllm-token")
    monkeypatch.setenv("RESPONSE_LLM_API_TOKEN", "real-kiconnect-token")
    monkeypatch.setenv("RESPONSE_LLM_URL", "https://chat.kiconnect.nrw/api/v1")
    monkeypatch.setenv("RESPONSE_LLM_MODEL", "test-model")

    provider = _build_provider("kiconnect", "RESPONSE_LLM")

    assert provider.config.api_token == "real-kiconnect-token"


def test_other_providers_keep_the_shared_token_fallback_unchanged(monkeypatch):
    # Nur KIConnect bekommt die strengere, token-isolierte Config --
    # andere Provider duerfen weiterhin den geteilten Token nutzen
    # (Auftrag-3-Verhalten bleibt unveraendert, keine Regression).
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "internal-anythingllm-token")
    monkeypatch.delenv("KNOWLEDGE_LLM_API_TOKEN", raising=False)
    monkeypatch.setenv("KNOWLEDGE_LLM_URL", "http://localhost:3001/api")

    provider = _build_provider("openai_compatible", "KNOWLEDGE_LLM")
    assert provider.config.api_token == "internal-anythingllm-token"


def test_mock_and_offline_providers_still_build_correctly():
    assert isinstance(_build_provider("mock", "KNOWLEDGE_LLM", '{"a": 1}'), MockLLMProvider)
    assert isinstance(_build_provider("unknown_kind", "KNOWLEDGE_LLM"), OfflineFallbackProvider)
