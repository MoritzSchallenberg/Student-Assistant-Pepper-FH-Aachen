# Entscheidungsfindung

## Überblick und Ziel des Themas

Der BehaviorTree.CPP-Interaktionsbaum, der pro Tick entscheidet, welches
Teilsystem gerade das Sagen hat — mit einer festen, sicherheitsorientierten
Prioritätsreihenfolge.

## Position in der Pepper-Gesamtarchitektur

Der zentrale Koordinator: konsumiert Werte aus
[Wahrnehmung und Interaktion](../perception-interaction/index.md), stößt
[Dialog und Gedächtnis](../dialogue-memory/index.md) und
[Gesten und Kinematik](../gestures-kinematics/index.md) an, und
präempiert alles bei einem Sicherheitsereignis.

## Lernziele

Nach diesem Thema kannst du:

1. die feste Prioritätsreihenfolge auswendig aufsagen: Safety > Battery
   > GreetAndApproach > Dialogue > Interaction > Presentation >
   IdleAttract;
2. erklären, warum die Wurzel ein `ReactiveFallback` ist, nicht ein
   einfacher `Fallback`, und was das für eine laufende Aktion bedeutet;
3. den vollständigen `GreetAndApproachSubtree`-Ablauf nachvollziehen:
   Person wählen → winken → auf Rückwinken warten → annähern →
   Gesprächsbereitschaft.

## Voraussetzungen

[Wahrnehmung und Interaktion](../perception-interaction/index.md).

## Pepper-spezifische Verwendung

{{ pepper }} Jeder Blattknoten des Baums ruft am Ende eine reale
`ihk_pepper_bridge`- oder `ihk_pepper_navigation`-Aktion auf diesem
konkreten Roboter auf.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Interaktions-Verhaltensbaum
:link: interaction-behavior-tree
:link-type: doc

{{ documented }} Der vollständige Baum, jeder Subtree, jeder
Blattknoten.
:::

::::

## Praktische Übungen

{{ offlineexercise }} `trees/pepper_main.xml` in Groot2 öffnen (auch
ohne laufenden `bt_executor_node` — Groot2 validiert die Struktur allein
über das `<TreeNodesModel>`) — siehe
[Interaktions-Verhaltensbaum](interaction-behavior-tree.md).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Alle neun BT-Knoten sind Ende-zu-Ende gegen einen
Mock-Nav2-Server funktional verifiziert (17 BT-Tests, 0 Fehler, 3
übersprungen). {{ hwverificationrequired }} für die tatsächliche
Ausführung gegen einen echten Pepper.

## Weiterführende Inhalte und nächste Schritte

[Dialog und Gedächtnis](../dialogue-memory/index.md) für
`RunDialogueViaBT`, den neuesten Subtree.

```{toctree}
:maxdepth: 1
:hidden:

interaction-behavior-tree
```
