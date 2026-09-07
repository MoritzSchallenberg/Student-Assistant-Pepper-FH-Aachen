# Dialog und Gedächtnis

## Überblick und Ziel des Themas

Die dreistufige LLM-Pipeline (Entwicklungsauftrag 3), die strukturell
verhindert, dass ein LLM je eine Bewegung auslöst oder eine Person
erfindet, plus das einwilligungsgebundene Personengedächtnis, das dahinter
steht.

## Position in der Pepper-Gesamtarchitektur

Wird vom [Verhaltensbaum](../decision-making/index.md)s
`DialogueSubtree` über `RunDialogueViaBT` gestartet; das Ergebnis geht an
[Gesten und Kinematik](../gestures-kinematics/index.md) (Gestennamen)
und `ihk_pepper_bridge`s `Say`-Action (Text).

## Lernziele

Nach diesem Thema kannst du:

1. erklären, warum drei getrennte LLM-Stufen statt einem großen
   LLM-Aufruf verwendet werden;
2. für jede Stufe angeben, was sie **nicht** ausgeben kann (strukturell,
   nicht nur per Prompt);
3. den Retriever-Reihenfolge-Vertrag benennen: exakter FAQ-Treffer →
   semantischer FAQ-Treffer → Personengedächtnis (nur mit Einwilligung)
   → RAG → sichere Antwort ohne Information;
4. erklären, warum eine `track_id` niemals automatisch zu einer
   `person_id` wird.

## Voraussetzungen

[Entscheidungsfindung](../decision-making/index.md) und
[Wahrnehmung und Interaktion](../perception-interaction/index.md).

## Pepper-spezifische Verwendung

{{ pepper }} Die Pipeline spricht über `ihk_pepper_bridge`s `Say`-Action
und triggert Gesten über dieselbe `PlayGesture`-Action, die auch der
Verhaltensbaum direkt nutzt — kein Sonderweg für LLM-ausgelöste
Aktionen.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Drei-Stufen-LLM-Pipeline
:link: three-stage-llm-pipeline
:link-type: doc

{{ documented }} Alle drei Stufen, der Retriever, der Validator, der
Executor.
:::

:::{grid-item-card} Personengedächtnis
:link: person-memory
:link-type: doc

{{ documented }} Identity Registry, Vector Memory, Einwilligung,
Löschung.
:::

::::

## Praktische Übungen

Siehe [Offline-Dialogübung](../integration-testing/offline-dialogue-test.md)
für den vollständigen, tatsächlich durchgeführten End-zu-End-Test.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Die gesamte Pipeline ist mit `MockLLMProvider` real
Ende-zu-Ende getestet worden (zwei Szenarien: bekannte und unbekannte
Person). {{ unverified }} `AnythingLLMProvider`/
`OpenAICompatibleProvider` wurden **nie** gegen einen echten LLM-
Endpunkt getestet — nur ihre HTTP-/Retry-/Circuit-Breaker-Logik selbst
ist unit-getestet.

## Weiterführende Inhalte und nächste Schritte

[Gesten und Kinematik](../gestures-kinematics/index.md) für die
Gesten, die diese Pipeline auslösen kann.

```{toctree}
:maxdepth: 1
:hidden:

three-stage-llm-pipeline
person-memory
```
