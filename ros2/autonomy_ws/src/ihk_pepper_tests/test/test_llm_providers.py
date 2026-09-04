import pytest

from ihk_pepper_llm_contracts.providers import (
    CircuitBreaker,
    LLMProvider,
    MockLLMProvider,
    OfflineFallbackProvider,
    ProviderConfig,
    ProviderResult,
)


def test_mock_provider_returns_success():
    provider = MockLLMProvider(fixed_response='{"ok": true}')
    result = provider.complete("frage?")
    assert result.success is True
    assert result.text == '{"ok": true}'
    assert result.latency_s >= 0.0


def test_mock_provider_records_calls():
    provider = MockLLMProvider(response_fn=lambda p: f"echo:{p}")
    provider.complete("hallo")
    assert provider.calls == ["hallo"]


def test_mock_provider_failure_returns_error_result_not_exception():
    provider = MockLLMProvider(fail=True)
    result = provider.complete("frage?")
    assert result.success is False
    assert result.error
    assert result.raw_error_class == "RuntimeError"


def test_offline_fallback_never_fails():
    provider = OfflineFallbackProvider()
    result = provider.complete("irgendeine frage")
    assert result.success is True
    assert provider.health_check() is True


def test_input_truncated_beyond_max_input_chars():
    config = ProviderConfig(max_input_chars=10)
    provider = MockLLMProvider(config=config, response_fn=lambda p: p)
    result = provider.complete("x" * 100)
    assert result.truncated_input is True
    assert provider.calls[0] == "x" * 10


def test_output_truncated_beyond_max_output_chars():
    config = ProviderConfig(max_output_chars=5)
    provider = MockLLMProvider(config=config, fixed_response="y" * 100)
    result = provider.complete("frage")
    assert result.truncated_output is True
    assert result.text == "y" * 5


def test_provider_config_from_env_reads_prefixed_vars(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_LLM_URL", "http://example.invalid")
    monkeypatch.setenv("KNOWLEDGE_LLM_MODEL", "test-model")
    monkeypatch.setenv("KNOWLEDGE_LLM_WORKSPACE", "test-ws")
    config = ProviderConfig.from_env("KNOWLEDGE_LLM")
    assert config.url == "http://example.invalid"
    assert config.model == "test-model"
    assert config.workspace == "test-ws"


def test_provider_config_from_env_falls_back_to_shared_token(monkeypatch):
    monkeypatch.delenv("RESPONSE_LLM_API_TOKEN", raising=False)
    monkeypatch.setenv("ANYTHINGLLM_API_TOKEN", "shared-token")
    config = ProviderConfig.from_env("RESPONSE_LLM")
    assert config.api_token == "shared-token"


def test_three_stages_are_independently_configurable(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_LLM_WORKSPACE", "ws-knowledge")
    monkeypatch.setenv("GESTURE_LLM_WORKSPACE", "ws-gesture")
    monkeypatch.setenv("RESPONSE_LLM_WORKSPACE", "ws-response")
    knowledge = ProviderConfig.from_env("KNOWLEDGE_LLM")
    gesture = ProviderConfig.from_env("GESTURE_LLM")
    response = ProviderConfig.from_env("RESPONSE_LLM")
    assert knowledge.workspace == "ws-knowledge"
    assert gesture.workspace == "ws-gesture"
    assert response.workspace == "ws-response"


# ---- Circuit Breaker ----

def test_circuit_breaker_starts_closed():
    cb = CircuitBreaker()
    assert cb.allow_request() is True
    assert cb.is_open is False


def test_circuit_breaker_opens_after_threshold_failures():
    fake_time = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=10.0, time_fn=lambda: fake_time["t"])
    cb.record_failure()
    cb.record_failure()
    assert cb.allow_request() is True  # noch unter der Schwelle
    cb.record_failure()
    assert cb.allow_request() is False
    assert cb.is_open is True


def test_circuit_breaker_half_open_after_cooldown():
    fake_time = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=10.0, time_fn=lambda: fake_time["t"])
    cb.record_failure()
    assert cb.allow_request() is False
    fake_time["t"] = 11.0
    assert cb.allow_request() is True  # Half-Open-Testversuch erlaubt


def test_circuit_breaker_resets_on_success():
    fake_time = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=2, cooldown_s=10.0, time_fn=lambda: fake_time["t"])
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.allow_request() is True  # Zaehler wurde zurueckgesetzt


def test_provider_stops_calling_after_circuit_breaker_opens():
    config = ProviderConfig()
    provider = MockLLMProvider(config=config, fail=True)
    provider.circuit_breaker = CircuitBreaker(failure_threshold=2, cooldown_s=999.0)
    provider.complete("a")
    provider.complete("b")
    assert len(provider.calls) == 2
    result = provider.complete("c")
    assert result.success is False
    assert "Circuit Breaker" in result.error
    assert len(provider.calls) == 2  # kein dritter tatsaechlicher Aufruf mehr


def test_each_role_not_reachable_does_not_crash_others():
    """Jede LLM-Stufe darf einzeln nicht erreichbar sein, ohne die
    anderen zu beeintraechtigen (Auftrag: Abnahmekriterium)."""
    knowledge = OfflineFallbackProvider()
    gesture = MockLLMProvider(fail=True)
    response = MockLLMProvider(fixed_response="ok")

    r1 = knowledge.complete("x")
    r2 = gesture.complete("x")
    r3 = response.complete("x")

    assert r1.success is True
    assert r2.success is False
    assert r3.success is True


def test_llm_provider_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider(ProviderConfig())


def test_provider_result_default_fields():
    result = ProviderResult(success=False)
    assert result.text == ""
    assert result.latency_s == 0.0
    assert result.truncated_input is False
