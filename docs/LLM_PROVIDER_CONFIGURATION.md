# LLM-Provider konfigurieren

Stand: 2026-09-04. Entwicklungsauftrag 3, AP2/AP11.
Implementierung: `ros2/autonomy_ws/src/ihk_pepper_llm_contracts/ihk_pepper_llm_contracts/providers.py`,
Node-Parameter in `ihk_pepper_dialog/run_dialogue_action_server.py`.

## Drei unabhängige Stufen

Jede der drei LLM-Rollen (Knowledge Planner, Gesture Planner, Response
Composer) ist über eine **eigene** ROS2-Node-Parameter-Kombination
konfigurierbar -- auch wenn aktuell alle drei auf denselben lokalen
AnythingLLM-Endpunkt zeigen könnten:

| Node-Parameter | Werte | Bedeutung |
|---|---|---|
| `knowledge_llm_provider` | `mock`\|`anythingllm`\|`openai_compatible`\|`offline` | Provider für Stufe 1 |
| `gesture_llm_provider` | dito | Provider für Stufe 2 |
| `response_llm_provider` | dito | Provider für Stufe 3 |

Default für alle drei: **`offline`** (`OfflineFallbackProvider`, wirft
nie, liefert immer einen sicheren "keine verlässliche Information"-Text
-- sicherer Startzustand ohne jede Netzwerkabhängigkeit).

## Umgebungsvariablen je Stufe

`ProviderConfig.from_env(prefix)` liest, exakt wie im Auftrag benannt:

| Präfix | URL | Modell | Workspace | Token |
|---|---|---|---|---|
| Knowledge Planner | `KNOWLEDGE_LLM_URL` | `KNOWLEDGE_LLM_MODEL` | `KNOWLEDGE_LLM_WORKSPACE` | `KNOWLEDGE_LLM_API_TOKEN` |
| Gesture Planner | `GESTURE_LLM_URL` | `GESTURE_LLM_MODEL` | `GESTURE_LLM_WORKSPACE` | `GESTURE_LLM_API_TOKEN` |
| Response Composer | `RESPONSE_LLM_URL` | `RESPONSE_LLM_MODEL` | `RESPONSE_LLM_WORKSPACE` | `RESPONSE_LLM_API_TOKEN` |

Fehlt `<PREFIX>_API_TOKEN`, fällt jede Stufe auf die geteilte
`ANYTHINGLLM_API_TOKEN`-Variable zurück (ein Token für alle drei, falls
gewünscht) -- explizite Pro-Stufe-Token bleiben aber möglich.

## Provider-Implementierungen

- **`MockLLMProvider`**: konfigurierbare feste/regelbasierte Antworten
  (`fixed_response`/`response_fn`), zeichnet jeden Aufruf in `.calls` auf
  -- ausschließlich für Tests/E2E-Treiber. Über die Node-Parameter
  `knowledge_llm_mock_response`/`gesture_llm_mock_response`/
  `response_llm_mock_response` (JSON-Strings) auch am echten Action-
  Server aktivierbar (siehe `manual_dialogue_e2e_check.py`).
- **`OfflineFallbackProvider`**: wirft nie, sicherer Default.
- **`AnythingLLMProvider`**: ruft `apps/web/llm/anythingllm.py` direkt an
  (bewusst NICHT über `ihk_pepper_dialog/anythingllm_client.py`
  importiert, um eine zirkuläre Paketabhängigkeit zu vermeiden -- siehe
  Kommentar in `providers.py`).
- **`OpenAICompatibleProvider`**: generischer `requests.post` gegen
  `{url}/chat/completions`, Bearer-Token aus der Konfiguration.

Jeder Provider: Timeout/Retries mit Backoff, Eingabe-/Ausgabegrößen-
begrenzung (hartes Abschneiden + Fehler-Flag), ein `CircuitBreaker`
(schließt nach `failure_threshold` aufeinanderfolgenden Fehlern für
`cooldown_s`, injizierbare `time_fn` -- unit-testbar ohne echtes
Zeit-Mocking), kein vollständiges Prompt-Logging per Default (nur
Länge/Hash).

## Beispiel-Start

```bash
export KNOWLEDGE_LLM_URL=http://localhost:3001/api
export KNOWLEDGE_LLM_MODEL=llama3
export KNOWLEDGE_LLM_WORKSPACE=pepper-faq
export ANYTHINGLLM_API_TOKEN=...

ros2 run ihk_pepper_dialog run_dialogue_action_server \
  --ros-args \
  -p knowledge_llm_provider:=anythingllm \
  -p gesture_llm_provider:=anythingllm \
  -p response_llm_provider:=anythingllm
```

**Ehrlicher Stand dieser Session**: In dieser Session wurde ausschließlich
gegen `MockLLMProvider`/`OfflineFallbackProvider` getestet (siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md`, AP11 -- `manual_dialogue_e2e_check.py`).
Ob in dieser Umgebung ein echter AnythingLLM-Endpunkt erreichbar ist,
wurde nicht geprüft; `AnythingLLMProvider`/`OpenAICompatibleProvider`
sind gegen keinen echten Endpunkt live getestet.

## ROS2-CLI-Falle: JSON-Parameter

`-p knowledge_llm_mock_response:={"schema_version": 1, ...}` scheitert
mit `Unknown YAML event` -- ROS2s CLI-Parameter-Parser ist YAML-, nicht
JSON-basiert und stolpert über verschachtelte Anführungszeichen/Klammern.
Workaround: Parameter über eine echte `--params-file <datei>.yaml`
übergeben (siehe `manual_dialogue_e2e_check.py` für ein Beispiel mit
`yaml.safe_dump()`).
