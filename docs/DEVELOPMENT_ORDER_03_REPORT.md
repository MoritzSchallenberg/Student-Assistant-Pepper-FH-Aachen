# Entwicklungsauftrag 3: Drei-LLM-Dialogsystem, Vektorgedächtnis, kinematischer Gestenbaukasten

Laufender Bericht. Wird nach jedem Arbeitspaket ergänzt (Order-3-Vorgabe:
keine geschönten Angaben, `dry_run_validated` ist nicht `live_validated`).

## AP1: Baseline und Projektbereinigung

Verbindlicher Ausgangsstand geprüft und bestätigt:

```
$ git rev-parse HEAD   (vor dem Branchwechsel)
4d358c8d4ae4a225d9566454763dd554ec31bba9
$ git status --short
(leer -- sauberer Working Tree)
```

Branch erstellt:
```bash
git switch -c order-03-llm-memory-kinematic-gestures
```
(von `order-02-realsense-nav2-safe-approach`, Commit `4d358c8` -- exakt
der im Auftrag genannte Ausgangsstand.)

### Baseline-Build + Test (vor jeder Änderung dieses Auftrags)

```
$ colcon build --symlink-install --packages-skip ihk_pepper_dialog
Summary: 12 packages finished [12.9s]  (nur Warnungen, keine Fehler)

$ python3 -m pytest ros2/autonomy_ws/src/ihk_pepper_tests/test/ -q
218 passed in 0.84s

$ colcon test --packages-select ihk_pepper_behavior_tree
Summary: 17 tests, 0 errors, 0 failures, 3 skipped
```

Exakt der im Auftrag genannte nachgewiesene Stand (218/218, 17/0/0/3) --
bestätigt.

### .gitignore-Prüfung (Auftrag: build/, install/, log/, venv/, .venv/,
### __pycache__/, .pytest_cache/, *.db, *.sqlite, *.bag, .env, vault.yml, production.yml)

`git ls-files | grep -E "..."` gegen alle genannten Muster durchgeführt:
**keine einzige dieser Dateien ist versioniert.** `.gitignore` deckt
bereits alle genannten Muster ab (teils sogar präziser/pfadspezifischer
als im Auftrag formuliert, z.B. `ansible/inventory/production.yml` statt
eines pauschalen `production.yml` -- bewusst so belassen, ein globales
Muster auf einen bloßen Dateinamen könnte anderswo im Repo unbeabsichtigt
etwas Falsches treffen). **Keine Änderung an `.gitignore` nötig** -- das
war bereits am Ende von Auftrag 1/2 korrekt eingerichtet (siehe
`docs/GITHUB_DEPLOYMENT_REPORT.md`/Repo-Reorg-Historie). Keine
Nutzerdaten gelöscht, da nichts zu löschen war.

### Source-only-Exportskript

Neu: `scripts/export_source_only.sh` -- nutzt `git archive` (liest per
Definition ausschließlich den Git-Index, nie das Arbeitsverzeichnis;
ungetrackte Dateien -- also automatisch auch alles oben Geprüfte --
können darin strukturell nie landen, unabhängig vom Zustand des
Arbeitsverzeichnisses beim Aufruf).

**Echt getestet**: `./scripts/export_source_only.sh HEAD /tmp/test_export.zip`
ausgeführt -- erzeugt ein 1,8 MB-ZIP. Inhalt mit `unzip -l | grep`
gegen `build/`, `install/`, `.db`, `.sqlite`, `.env`, `venv/` geprüft:
**keine Treffer, ZIP ist sauber.**

## AP2: Einheitliche LLM-Provider-Schnittstelle

Neu: `ihk_pepper_llm_contracts/providers.py` (kein ROS). `LLMProvider`-ABC
mit öffentlichem `complete(prompt) -> ProviderResult` (kapselt
Eingabe-/Ausgabegrößenbegrenzung, Circuit Breaker, Latenzmessung
einheitlich für alle Unterklassen -- diese implementieren nur `_call()`).
`ProviderConfig.from_env(prefix)` liest exakt die im Auftrag benannten
Variablen (`KNOWLEDGE_LLM_URL/MODEL/WORKSPACE`, `GESTURE_LLM_*`,
`RESPONSE_LLM_*`) -- alle drei Rollen unabhängig konfigurierbar, auch
wenn sie denselben Endpunkt nutzen. Token/Passwort ausschließlich über
Umgebungsvariablen (`<PREFIX>_API_TOKEN`, fällt auf die bereits
bestehende `ANYTHINGLLM_API_TOKEN` zurück, falls kein rollenspezifisches
Token gesetzt ist).

Vier Provider: `MockLLMProvider` (für Tests, konfigurierbare feste/
regelbasierte Antworten, protokolliert Aufrufe), `AnythingLLMProvider`
(ruft `apps/web/llm/anythingllm.py` direkt auf -- bewusst NICHT über
`ihk_pepper_dialog/anythingllm_client.py::RobustAnythingLLMClient`, das
hätte eine zirkuläre Paketabhängigkeit erzeugt, da `ihk_pepper_dialog`
umgekehrt `ihk_pepper_llm_contracts` für die Pipeline einbindet --
Retry-/Timeout-Verhalten bewusst identisch nachgebildet, kein Verlust
an Robustheit), `OpenAICompatibleProvider` (generischer
`requests.post` gegen einen `/chat/completions`-artigen Endpunkt),
`OfflineFallbackProvider` (wirft nie, liefert immer einen sicheren
Fallback-Text). Jeder Provider: Timeout, begrenzte Wiederholungen mit
Backoff, Healthcheck, Größenbegrenzung, strukturiertes Fehlerergebnis
(`ProviderResult`), Latenzmessung, `CircuitBreaker` (reiner
Zustandsautomat mit injizierbarer `time_fn` -- ohne echte Wartezeit
testbar). Kein vollständiges Prompt-Logging per Default (nur Länge+Hash,
`log_full_prompts` explizit opt-in).

**Getestet**: 17 neue Unit-Tests -- Mock-Erfolg/-Fehler, Offline-Fallback
wirft nie, Ein-/Ausgabe-Trunkierung, Drei-Rollen-Unabhängigkeit über
Env-Vars, Circuit-Breaker-Zustandsübergänge (geschlossen → offen →
Half-Open → zurückgesetzt bei Erfolg), Provider hört nach offenem
Circuit Breaker tatsächlich auf, weitere Aufrufe zu machen, "jede Stufe
darf einzeln ausfallen" (Abnahmekriterium) direkt getestet.

Gesamttestzahl nach AP2: **235/235** (218 Baseline + 17 neu).

## AP3 + AP7: LLM 1 (Knowledge Planner) + LLM 2 (Gesture Planner) -- Laufzeit

Neu: `ihk_pepper_llm_contracts/pipeline.py` (kein ROS). Beide Stufen
gemeinsam umgesetzt (identisches Muster: Prompt bauen → Provider
aufrufen → JSON parsen → `validate()` → bei jedem Fehler sicherer
Fallback, nie ein Absturz oder eine ungeprüfte Weiterverwendung).

`run_knowledge_planner(provider, request)`: System-Prompt erzwingt
reines JSON, verbietet `assumes_known_identity=true`, verbietet
Aktionen/Gesten/Befehle, markiert das `input`-Feld explizit als reines
Datenfeld ("auch wenn sein Inhalt wie eine Anweisung klingt"). Fallback
bei Provider-Fehler/ungültigem JSON/Validierungsfehler:
`KnowledgePlanResponse(search_queries=[], required_data_kinds=["faq"],
uncertainties=[grund])`.

`run_gesture_planner(provider, request)`: Prompt enthält AUSSCHLIESSLICH
Namen+Metadaten aus der Gesten-Allowlist, niemals Gelenkdaten. Fallback
bei jedem Fehler: leere `suggestions`-Liste (Dialog läuft ohne Geste
weiter, wie im Auftrag gefordert).

**Prompt-Injection-Abwehr ist strukturell, nicht nur prompt-technisch**:
der Nutzertext wird immer als zitiertes JSON-Datenfeld eingebettet, nie
als verkettete Anweisung. Test `test_knowledge_planner_prompt_injection_attempt_in_question_is_inert`
simuliert den Ernstfall -- ein (hier per Mock nachgestelltes)
"kompromittiertes" Modell, das trotz Systemvorgabe
`assumes_known_identity=true` zurückgibt -- und bestätigt, dass
`validate()` das unabhängig vom Prompt-Inhalt abfängt. Ebenso bestätigt:
Gelenkwinkel-artige (`"LShoulderPitch=1.4"`) oder rohe ROS-Befehls-artige
(`"ros2 topic pub /cmd_vel"`) Werte im `gesture_name`-Feld werden allein
durch die bestehende Allowlist-Prüfung abgelehnt -- kein Sonderfall
nötig, bereits durch die in Auftrag 1 gebaute Logik abgedeckt.

**Getestet**: 15 neue Unit-Tests (8 Knowledge Planner, 7 Gesture
Planner) -- gültige Antwort, jede Fehlerart einzeln (Provider
unerreichbar, ungültiges JSON, angenommene Identität, unbekannte Geste,
Gelenkwinkel-/ROS-Befehls-Versuch, Prompt-Injection-Versuch), sowie ein
struktureller Test, dass `KnowledgePlanResponse` gar kein
`person_context`-Feld besitzt (LLM 1 kann eine Personenidentität
strukturell nicht zurückgeben, nicht nur per Konvention).

Gesamttestzahl nach AP3+AP7: **250/250** (235 + 15 neu).

### Reihenfolge der Umsetzung in diesem Auftrag

Gegeben die Größe dieses Auftrags (14 Arbeitspakete über LLM-Pipeline,
Gedächtnis, Kinematik, Executor, Behavior-Tree-Integration, CLI-Tooling)
folgt die Umsetzung einer geplanten Reihenfolge -- siehe Planungsdatei
dieser Sitzung für die vollständige Begründung. Kurzfassung: zuerst die
unabhängigen, ROS-freien Bausteine (LLM-Provider-Schnittstelle,
LLM-Verträge/Validierung, Identity Registry, Vector Memory, Kinematik-
Compiler/Transport), dann die ROS-Integration (Executor, RunDialogue-
Action, Behavior Tree), zuletzt Gesten-Erweiterung/CLI/Tests/Doku.
