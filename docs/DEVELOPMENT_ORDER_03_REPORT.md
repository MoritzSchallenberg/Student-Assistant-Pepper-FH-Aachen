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

## AP4: Deterministischer Wissensabruf

`knowledge_planner.py::KnowledgePlanResponse` um `normalized_intent` und
`use_person_memory` ergänzt (im Auftrag-Beispiel-JSON vorhanden, in der
Auftrag-1-Fassung noch gefehlt) -- `from_dict()` bleibt abwärtskompatibel
(`.get(..., default)`), keine bestehenden Tests gebrochen.

Neu: `ihk_pepper_llm_contracts/retriever.py` (kein ROS, kein LLM-Aufruf).
`run_retrieval()` -- Reihenfolge exakt wie im Auftrag: exakter FAQ-Treffer
→ semantischer FAQ-Treffer → freigegebenes Personengedächtnis (NUR bei
`use_person_memory` UND `person_context["known"]`, sonst niemals
aufgerufen -- Test bestätigt beide Bedingungen unabhängig) → RAG →
sichere Antwort ohne Information. Callback-basiertes Design
(`faq_lookup_fn`/`person_memory_fn`/`rag_fn` injiziert) hält das Modul
frei von ROS-/SQLite-Importen. `source_id` nach festem Schema
(`faq:<id>`, `memory:topic:<slug>`, `rag:<chunk_id>`) -- niemals erfunden,
immer aus der jeweiligen Quelle abgeleitet.

**Getestet**: 11 neue Unit-Tests -- Reihenfolge (exakt schlägt semantisch
schlägt Gedächtnis), Consent-/Flag-Gate für Personengedächtnis (beide
Bedingungen einzeln getestet), RAG als letzte Instanz vor dem sicheren
Fallback, RAG-Fehlschlag fällt sauber durch, keine Quelle konfiguriert →
sichere "keine verlässliche Information"-Antwort, `source_id`s werden
nur generiert, nie erfunden.

Gesamttestzahl nach AP4: **261/261** (250 + 11 neu).

## AP5 + AP6: Persistente Identity Registry + Vector Memory

Neu: `ihk_pepper_person_memory/identity_registry_db.py` --
`IdentityRegistryStore` (SQLite, Schema-/Verbindungsmuster wie
`ihk_pepper_dialog/faq_cache.py`). Tabelle `identities` (`person_id`
PRIMARY KEY, `display_name`, `consent_status`, `created_at`,
`last_seen_at`, `last_recognition_confidence`, `retention_deadline`)
+ append-only `identity_audit_log` (jede Schreiboperation braucht
einen Pflicht-`reason`-String, sonst `ValueError`). `person_id` wird
NIE aus einer ByteTrack-`track_id` abgeleitet -- die Klasse kennt
`track_id` überhaupt nicht (strukturell erzwungen, per Test bestätigt:
`create_or_touch()`s Signatur hat kein `track_id`-Argument).
`delete()` löscht die Zeile ECHT (kein bloßes Flag). `get_context()`
liefert `known=False`, sobald keine `granted`-Einwilligung vorliegt --
auch wenn ein Datensatz existiert.

Neu: `ihk_pepper_person_memory/vector_memory_db.py` +
`embedding_backend.py` (bewusst eigenständige Kopie des
`EmbeddingBackend`/`SentenceTransformerBackend`/`DifflibFallbackBackend`-
Musters aus `faq_cache.py`, NICHT importiert -- vermeidet dieselbe
zirkuläre-Abhängigkeit-Problematik wie bei `providers.py`s
`AnythingLLMProvider`, siehe AP2). `VectorMemoryStore.write_validated_summary()`
ruft zuerst die bestehende `validate_memory_write()` (Auftrag 1) auf,
schreibt NUR bei `errors == []`. `query_by_topic()`/`query_semantic()`
geben nie Ergebnisse einer fremden `person_id` zurück (Test bestätigt).
`MemoryEntry` um `session_id`/`sources` ergänzt (Auftrag-Beispielschema),
abwärtskompatibel. Strukturell bestätigt: `MemoryEntry` besitzt kein
Feld für rohe Prompts/Chain-of-Thought -- `text_summary` ist die einzige
Textquelle.

Neu: `ihk_pepper_person_memory/affect_observation.py` --
`IdentityObservation` (reiner Datencontainer, nie eine automatische
Zuordnung), `AffectObservation` (verallgemeinert `mood_signal.py::MoodObservation`
auf beliebige Quellen, `is_reliable_fact()` immer `False`), `PersonContext`
(interne, ausführlichere Sicht -- nicht zu verwechseln mit der schlanken
Pipeline-`PersonContext` in `knowledge_planner.py`, die unverändert bleibt).

5 neue `.srv`-Dateien in `ihk_pepper_interfaces`
(`LookupPerson`/`SetConsent`/`SetDisplayName`/`DeletePerson`/
`GetPersonContext`) + neuer Node `person_memory_node.py` (dünner
ROS-Wrapper, `rclpy`-Depend neu in `package.xml`). DB-Pfade
konfigurierbar, Default `~/.ihk_pepper_memory/{identity,vector_memory}.db`
-- außerhalb jedes Git-/Colcon-Baums (gleiches Prinzip wie
`~/.ihk_pepper_maps/` aus Auftrag 2). Bewusste Design-Entscheidung: kein
eigener "Person anlegen"-Service (Auftrag: kein LLM darf eine Person
anlegen) -- die erste `SetConsent`-Anfrage für eine unbekannte `person_id`
legt den Datensatz implizit an, ausschließlich über diesen von einem
Menschen/`RunDialogue` ausgelösten Weg.

**Echt getestet** (voller Service-Lebenszyklus, nicht nur Unit-Tests):
Node gestartet, `set_consent` (neue Person, `granted`) →
`set_display_name` → `lookup_person` (bestätigt `known=true,
consent_status=granted, display_name=Max`) → `get_person_context`
(bestätigt `known=true`) → `delete_person` (meldet
`identity_geloescht=True, memory_eintraege_geloescht=0`) →
`lookup_person` erneut (bestätigt wieder `known=false`) -- kompletter
Lebenszyklus über echte `ros2 service call`-Aufrufe live verifiziert.

**Getestet**: 18 neue Unit-Tests (Identity Registry: unbekannte Person,
Erstanlage, Consent-Übergänge inkl. ungültiger Werte, Löschung,
Audit-Pflicht, Kontext nur mit Einwilligung, keine Cross-Person-Leckage,
Persistenz nach Neustart, keine implizite Track-ID-Nutzung) + 13 neue
Unit-Tests (Vector Memory: Schreiben nur mit Consent, Themen-/
Semantiksuche, keine Cross-Person-Leckage, abgelaufene Einträge nicht
zurückgegeben, Löschung, Persistenz nach Neustart, strukturell kein
Rohdaten-Feld) + 6 neue Unit-Tests (Affect/Identity-Beobachtungen, immer
`is_reliable_fact()==False`).

Gesamttestzahl nach AP5+AP6: **298/298** (261 + 37 neu).

### Reihenfolge der Umsetzung in diesem Auftrag

Gegeben die Größe dieses Auftrags (14 Arbeitspakete über LLM-Pipeline,
Gedächtnis, Kinematik, Executor, Behavior-Tree-Integration, CLI-Tooling)
folgt die Umsetzung einer geplanten Reihenfolge -- siehe Planungsdatei
dieser Sitzung für die vollständige Begründung. Kurzfassung: zuerst die
unabhängigen, ROS-freien Bausteine (LLM-Provider-Schnittstelle,
LLM-Verträge/Validierung, Identity Registry, Vector Memory, Kinematik-
Compiler/Transport), dann die ROS-Integration (Executor, RunDialogue-
Action, Behavior Tree), zuletzt Gesten-Erweiterung/CLI/Tests/Doku.
