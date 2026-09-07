"""
Optionaler LIVE-Test gegen den echten KI:connect-Endpunkt
(Ergaenzungsauftrag 04-A, Abschnitt 1.8: "ein Testfall, der NUR bei
gesetzter Umgebungsvariable ausgefuehrt wird").

Dieser Test ist standardmaessig uebersprungen -- er lief in dieser
Session KEIN einziges Mal gegen den echten Endpunkt, da kein echter
RESPONSE_LLM_API_TOKEN vorliegt (siehe DEVELOPMENT_ORDER_04_REPORT.md).
Aktivierung NUR durch einen Menschen mit echtem Token:

    export RUN_KICONNECT_LIVE_TEST=1
    export RESPONSE_LLM_URL=https://chat.kiconnect.nrw/api/v1
    export RESPONSE_LLM_MODEL=<echter, per GET /models ermittelter Modellname>
    export RESPONSE_LLM_API_TOKEN=<echter Token, NIEMALS hier einchecken>
    python3 -m pytest ros2/autonomy_ws/src/ihk_pepper_tests/test/test_kiconnect_live_optional.py -q

Sendet ausschliesslich synthetische, nicht personenbezogene Testdaten --
niemals echte Namen, echte Personendaten oder echte Interaktionsdaten.
"""
import json
import os

import pytest

from ihk_pepper_llm_contracts.providers import KIConnectProvider, ProviderConfig

_LIVE_ENABLED = os.environ.get("RUN_KICONNECT_LIVE_TEST", "") == "1"

pytestmark = pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason=(
        "RUN_KICONNECT_LIVE_TEST!=1 -- Live-Test gegen den echten "
        "KI:connect-Endpunkt ist bewusst opt-in (Auftrag 1.8) und laeuft "
        "hier standardmaessig nicht."
    ),
)


def _live_config() -> ProviderConfig:
    config = ProviderConfig.from_env("RESPONSE_LLM")
    if not config.url or not config.model or not config.api_token:
        pytest.skip(
            "RUN_KICONNECT_LIVE_TEST=1 gesetzt, aber RESPONSE_LLM_URL/"
            "_MODEL/_API_TOKEN fehlen -- kein echter Live-Test ohne "
            "vollstaendige echte Konfiguration."
        )
    return config


def test_live_model_is_available():
    provider = KIConnectProvider(_live_config())
    assert provider.model_is_available() is True, (
        f"konfiguriertes Modell '{provider.config.model}' nicht in der "
        "echten /models-Liste von KI:connect gefunden"
    )


def test_live_health_check():
    provider = KIConnectProvider(_live_config())
    assert provider.health_check() is True


def test_live_chat_completion_with_synthetic_prompt():
    """Nur synthetischer, nicht personenbezogener Testinhalt -- keine
    echte Interaktion, kein echter Personenbezug."""
    provider = KIConnectProvider(_live_config())
    prompt = (
        "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt exakt in diesem "
        "Schema: {\"schema_version\": 1, \"segments\": "
        "[{\"segment_id\": \"test\", \"text\": \"...\", "
        "\"gesture_name\": null, \"gesture_relation\": null}], "
        "\"source_ids\": [], \"memory_summary_candidate\": null}\n"
        "input: {\"answer_facts\": [\"Dies ist ein synthetischer Testfakt "
        "ohne Personenbezug.\"], \"source_ids\": [], \"allowed_gestures\": [], "
        "\"interaction_context\": {\"person_known\": false, "
        "\"preferred_form_of_address\": \"neutral\"}}"
    )
    result = provider.complete(prompt)
    assert result.success, f"echter KI:connect-Aufruf fehlgeschlagen: {result.error}"
    data = json.loads(result.text)
    assert data.get("schema_version") == 1
    assert isinstance(data.get("segments"), list)
