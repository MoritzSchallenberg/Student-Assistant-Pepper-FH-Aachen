# AP8-Laufzeit-Performance: Baseline, Kandidaten, Ergebnisse

Stand: 2026-09-13. Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 8/9.
Optimierungen wurden ERST nach den geschlossenen Sicherheitsregressionen
(siehe `docs/AP8_R3_RUNTIME_HARDENING.md`) begonnen, wie vom Auftrag
verlangt. Reproduktion: `python3 scripts/benchmark_ap8_runtime.py`
(ausschließlich offline, temporäre SQLite-Datei, `MockLLMProvider`-
Muster, keine echte Hardware, kein externer LLM-Aufruf).

## Umgebung dieser Messung

- Betriebssystem: Linux (Entwicklungsrechner dieser Session)
- Python: 3.12.3
- ROS2: Jazzy (nicht für die hier gemessenen Pfade nötig -- reines
  Python, kein `rclpy.init()`)
- Backend: `DifflibFallbackBackend` (sentence-transformers NICHT
  verfügbar in dieser Umgebung -- `numpy`/`scipy`-Versionskonflikt,
  bereits an anderer Stelle im Projekt dokumentiert). **Wichtig für die
  Einordnung der Zahlen**: mit einem echten Sentence-Transformer-Backend
  wäre die Embedding-Kodierung (nicht die hier optimierte SQL-/JSON-Last)
  voraussichtlich der dominante Kostenfaktor -- diese Messung isoliert
  bewusst NUR den lokalen Orchestrierungsaufwand, keine NUC-Hardware-
  leistung wird daraus abgeleitet oder behauptet.
- Kein NUC in dieser Session verfügbar -- alle Zahlen stammen von diesem
  Entwicklungsrechner, keine Übertragung auf andere Hardware.

## Katalog

Der tatsächliche, unveränderte 24-Gesten-Katalog
(`src/ihk_pepper_bridge/config/gestures/`). Eine größere synthetische
Datenmenge ist NICHT Teil dieses Laufs -- optional, als eigens
gekennzeichneter Skalierungstest, für später vorgesehen.

## Kandidat A: Gestenindex-Snapshot (umgesetzt)

**Bestätigter Befund** (Abschnitt 9 des Auftrags): `GestureIndexStore.search()`
lud bei JEDER Anfrage sämtliche Zeilen aus SQLite neu und deserialisierte
deren JSON-Felder (`allowed_interaction_states`/`semantic_tags`/
`embedding`) erneut -- unabhängig davon, ob sich der Index seit der
letzten Anfrage überhaupt verändert hatte.

**Umsetzung**: ein unveränderlicher, unter `_snapshot_lock` geschützter
Snapshot (`_cached_entries`) wird genau einmal geladen und bis zum
nächsten TATSÄCHLICHEN `reindex()` wiederverwendet -- der frühe
"unchanged"-Rückgabepfad (Fingerprint identisch, Daten unverändert)
invalidiert den Snapshot bewusst NICHT. Invalidierung erfolgt ERST NACH
erfolgreichem `commit()` (kein teilweise aufgebauter Index wird je
sichtbar). Harte Filter (`passes_hard_filters()`) laufen weiterhin bei
JEDER Anfrage frisch gegen den aktuellen Request -- gecacht wird
ausschließlich das teure SQL-Laden/Deserialisieren, NIE eine fertige
Auswahl-/Autorisierungsentscheidung. Threadsicher (`threading.Lock`).

### Gemessenes Ergebnis (p50/p95, 200 Durchläufe nach 5 Warm-up-Läufen, Katalog 24 Gesten)

| Szenario | ohne Cache (Baseline, 50 Läufe) | mit Cache (Standard jetzt) | Effekt |
|---|---|---|---|
| Suche ohne Suchtext | p50 0.218ms / p95 0.281ms | p50 0.016ms / p95 0.017ms | **~13.6x schneller** (p50) -- kein Ranking-Aufwand, die SQL-/JSON-Last dominierte hier vollständig |
| Suche mit wiederholtem Suchtext | -- (siehe wechselnder Suchtext, identischer Codepfad) | p50 2.05ms / p95 2.92ms | -- |
| Suche mit wechselndem Suchtext | p50 2.78ms / p95 4.31ms | p50 2.49ms / p95 3.62ms | **~10% schneller** (p50) -- die Difflib-Embedding-Kodierung dominiert hier, nicht das SQL-Laden |

**Ehrliche Einordnung**: der Snapshot-Cache bringt einen GROSSEN,
messbaren Vorteil für die Suche ohne Suchtext (kein Ranking-Aufwand, das
SQL-Laden macht praktisch die gesamte Laufzeit aus) und einen KLEINEN,
aber real messbaren Vorteil bei Suchtext-Anfragen (dort dominiert die
Embedding-Kodierung selbst -- mit dem hier verfügbaren Difflib-Fallback
UND voraussichtlich erst recht mit einem echten Sentence-Transformer-
Backend). Kein pauschaler Prozentsatz wird über beide Fälle hinweg
behauptet.

**Entscheidung**: umgesetzt (siehe `gesture_index_db.py`), da in BEIDEN
gemessenen Fällen ein echter, nie negativer Effekt vorliegt, keine
Verletzung der Invalidierungs-/Thread-Sicherheits-/Determinismus-
Anforderungen aus Abschnitt 9, und bestehende Tests (43 in
`ihk_pepper_gesture_memory`-Umfeld) unverändert grün bleiben.

## Kandidat B: Warte-/Callback-Pfade (bewusst NICHT umgesetzt)

Geprüft: die bestehenden Warteschleifen in
`run_dialogue_action_server.py` (`_wait_for_question()`,
`_acknowledge_and_run_pipeline()`s Pipeline-Wartezyklus,
`_execute()`s Exec-Wartezyklus) pollen bereits in kurzen, begrenzten
Intervallen (0.05s-0.1s) statt unbegrenzt zu blockieren -- sie sind
bereits das Ergebnis der AP8.8/AP8.9/AP8-R3-Regressionsarbeit an genau
diesen Stellen (kontinuierliche Sicherheitsüberwachung über
`_dialogue_abort_requested()`, siehe `docs/AP8_R3_RUNTIME_HARDENING.md`).

Eine Umstellung auf echte Future-/Event-basierte Weckung (statt
Polling) wurde bewusst NICHT umgesetzt: der erwartete Gewinn (Wegfall
der Polling-Overhead-Latenz von maximal 50-100ms) ist gegenüber dem
Risiko einer solchen Umstellung (mehrere ineinander verschachtelte
`threading.Event`/ROS2-Future-Objekte über drei Wartephasen hinweg neu
zu verdrahten, ohne die gerade erst geschlossenen Abbruch-/Freshness-
Garantien aus AP8-R3 versehentlich wieder aufzuweichen) in der
verbleibenden Zeit dieses Auftrags nicht zu rechtfertigen. Das ist eine
bewusste "kein Vorteil, der das Risiko rechtfertigt"-Entscheidung im
Sinne von Abschnitt 9 ("Wenn ein Kandidat keinen belastbaren Vorteil
bietet, dokumentiere das und lasse ihn unverändert"), keine vergessene
Arbeit. Bleibt unverändert.

## Zusätzliche Messungen (Kontext, keine Optimierung)

- **Cancel bis zur beobachteten Reaktion** (`ResponsePlanExecutor`s
  unterbrechbare Nachlaufpause, AP8.9): bei `post_speech_pause_s=2.0`
  und einem nach 0.05s ausgelösten `cancel()` kehrt `execute()` bei
  p50 nach 50.75ms zurück (p95 51.47ms) -- die Pause reagiert also
  effektiv INNERHALB von unter 1ms auf das Cancel-Signal, statt die
  vollen 2000ms zu blockieren (das war genau der AP8.9-Fund/Fix).
- **Wiederholte Sitzung und Cleanup**: 500 aufeinanderfolgende
  `ResponsePlanExecutor`-Erzeugungen/-Ausführungen zeigen **keinen**
  messbaren RSS-Zuwachs (527336 KiB durchgehend, `rss_growth_kb: 0`) --
  kein Hinweis auf unbegrenzt wachsende registrierte Arbeit über viele
  Runden hinweg.

## Nicht gemessen / außerhalb dieses Laufs

- Service-Rundlauf über echte ROS2-Kommunikation (bereits durch
  `test_run_dialogue_real_ros2_integration.py` funktional, aber nicht
  performance-mäßig vermessen -- kein dedizierter Latenz-Benchmark in
  diesem Lauf).
- Ein echtes Sentence-Transformer-Embedding-Backend (in dieser Umgebung
  wegen eines bestehenden `numpy`/`scipy`-Versionskonflikts nicht
  verfügbar, siehe `_KNOWLEDGE_MOCK`-Warnung in mehreren Testläufen) --
  die gemessenen Such-Latenzen mit Suchtext gelten NUR für den
  Difflib-Fallback.
- Skalierungstest mit einer synthetisch vergrößerten Gestenmenge
  (optional, nicht Teil dieses Laufs).
