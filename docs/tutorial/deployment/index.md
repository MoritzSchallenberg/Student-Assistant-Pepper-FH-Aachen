# Deployment

## Überblick und Ziel des Themas

Wie dieses Projekt heute entwickelt wird (auf einem allgemeinen
Entwicklungsrechner, nicht auf dedizierter Pepper-Hardware) und der
vorbereitete, versionierte Ansible-Weg zu einem dedizierten Pepper-NUC.

## Position in der Pepper-Gesamtarchitektur

Der letzte Schritt: alles aus den vorherigen Themen läuft am Ende auf
genau diesem Weg produktiv.

## Lernziele

Nach diesem Thema kannst du:

1. den Unterschied zwischen der heutigen Entwicklungsumgebung und dem
   vorbereiteten NUC-Ziel benennen;
2. die 14 Deployment-Schritte grob nachvollziehen und wissen, wann
   `current` tatsächlich umgeschaltet wird;
3. erklären, warum ein Deployment nie einfach den aktiven Ordner
   überschreibt.

## Voraussetzungen

[Integration und Tests](../integration-testing/index.md).

## Pepper-spezifische Verwendung

{{ pepper }} Der NUC-Bootstrap installiert explizit **kein**
Desktop/RViz — das läuft auf dem Entwicklungsrechner, der NUC selbst
läuft headless gegen den echten Pepper.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Entwicklung auf dem allgemeinen NUC
:link: development-nuc
:link-type: doc

{{ documented }} Der heutige Entwicklungsstand und der vorbereitete
Ansible-Weg zu einem dedizierten Pepper-NUC.
:::

::::

## Praktische Übungen

{{ offlineexercise }} `cd ansible && ansible-galaxy collection install -r
requirements.yml` und `ansible-playbook ... --syntax-check` sind risikofrei
ohne echtes Zielsystem ausführbar — siehe
[Entwicklung auf dem allgemeinen NUC](development-nuc.md).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ documented }} Die Ansible-Rollen sind real vorhanden und
dokumentiert; ein tatsächliches Deployment auf einen dedizierten
Pepper-NUC ist für dieses Tutorial **nicht** durchgeführt worden --
{{ hwverificationrequired }}.

## Weiterführende Inhalte und nächste Schritte

[Referenz](../reference/index.md) für Interfaces und die vollständige
Status-Legende.

```{toctree}
:maxdepth: 1
:hidden:

development-nuc
```
