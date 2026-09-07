# Gesten und Kinematik

## Überblick und Ziel des Themas

Der vollständige Weg von einer Gesten-YAML bis zur tatsächlichen
Roboterbewegung: Format, kinematischer Compiler, Motion Transport, und
das beaufsichtigte Live-Test-Verfahren, das eine Geste erst nach echter
menschlicher Prüfung als `live_validated` markiert.

## Position in der Pepper-Gesamtarchitektur

Wird vom [Verhaltensbaum](../decision-making/index.md) direkt
(`PlayCatalogGesture`) und von
[Dialog und Gedächtnis](../dialogue-memory/index.md)s LLM-2-Stufe
(nur über Namen aus einer Allowlist) ausgelöst.

## Lernziele

Nach diesem Thema kannst du:

1. den Unterschied zwischen Schema v1 (sequenziell) und v2 (synchrone
   Keyframes) erklären;
2. die Pipeline `Gesture → KinematicCompiler → TrajectoryPlan →
   MotionTransport → Pepper/Mock` nachvollziehen;
3. den Unterschied zwischen `dry_run_validated` und `live_validated`
   erklären und wissen, was jeweils NICHT dadurch bewiesen ist;
4. eine neue, sichere Geste nach der etablierten Checkliste selbst
   anlegen.

## Voraussetzungen

[Pepper-Plattform und Sicherheit](../pepper-platform/index.md) --
insbesondere die Gelenkgrenzen und die 1-Motor-Hand-Einschränkung.

## Pepper-spezifische Verwendung

{{ pepper }} Jede Geste in diesem Katalog ist gegen Pepper-1.8-
spezifische Gelenkgrenzen (`joint_limits.py`) validiert -- nicht
generisch für einen anderen Roboter übertragbar.

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Gestenformat
:link: gesture-format
:link-type: doc

{{ documented }} Das v2-YAML-Schema, Validierungsregeln, die
kinematische Pipeline.
:::

:::{grid-item-card} Gestenkatalog
:link: gesture-catalog
:link-type: doc

{{ documented }} Alle 22 Katalogeinträge mit Status und Herkunft.
:::

:::{grid-item-card} Sichere Gestenentwicklung
:link: safe-gesture-development
:link-type: doc

{{ documented }} Die Checkliste, zwei neu angelegte Beispielgesten, und
das beaufsichtigte Live-Test-Verfahren.
:::

::::

## Praktische Übungen

Siehe [Sichere Gestenentwicklung](safe-gesture-development.md) für die
zwölf geforderten Kinematikübungen mit Gelenken, Zielwinkeln,
Geschwindigkeit, Grenzen, Abbruchbedingungen und Freigabestufen.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} 20 der 22 Katalogeinträge sind `draft` oder
`dry_run_validated` -- **nur `t_pose`** ist `live_validated`. Kein
Katalogeintrag darf ohne beaufsichtigten Live-Test als
{{ hardwareverified }} gelten.

## Weiterführende Inhalte und nächste Schritte

[Integration und Tests](../integration-testing/index.md) für die
vollständige Gestenvalidierung ohne Hardware.

```{toctree}
:maxdepth: 1
:hidden:

gesture-format
gesture-catalog
safe-gesture-development
```
