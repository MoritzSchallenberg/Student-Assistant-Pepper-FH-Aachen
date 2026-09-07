# ROS 2

## Überblick und Ziel des Themas

Der `ihk_pepper_*`-Paketaufbau im Detail: welches Paket welche
Schnittstellen (Messages/Services/Actions) definiert oder nutzt, und wie
die elf Pakete voneinander abhängen, ohne sich gegenseitig direkt zu
importieren.

## Position in der Pepper-Gesamtarchitektur

Jedes andere Thema auf dieser Seite beschreibt ein oder mehrere dieser
Pakete inhaltlich vertieft — dieses Thema ist die strukturelle Landkarte
dazu.

## Lernziele

Nach diesem Thema kannst du:

1. für ein gegebenes ROS2-Interface (Topic/Service/Action) angeben,
   welches Paket es definiert und welche es nutzen;
2. erklären, warum `ihk_pepper_dialog` ein eigenes venv braucht und beim
   Standard-Build übersprungen wird;
3. die "reine Logik von ROS trennen"-Konvention wiedererkennen, die
   sich durch praktisch jedes Paket zieht (z.B. `motion_guard.py` kennt
   kein `rclpy`, ein dünner `motion_guard_node.py` wrappt es).

## Voraussetzungen

[Erste Schritte](../getting-started/index.md) abgeschlossen.

## Pepper-spezifische Verwendung

{{ pepper }} `ihk_pepper_interfaces` ist die einzige gemeinsame Sprache
zwischen allen anderen Paketen — kein Paket importiert ein anderes
`ihk_pepper_*`-Paket direkt für Laufzeitlogik (Ausnahme: bewusst
begründete Fälle, z.B. `ihk_pepper_dialog` importiert
`ihk_pepper_llm_contracts` für die Pipeline, siehe
[Dialog und Gedächtnis](../dialogue-memory/index.md)).

## Unterthemen und empfohlene Reihenfolge

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} Paketaufbau und Interfaces
:link: package-layout
:link-type: doc

{{ foundation }} Alle elf Pakete, ihre Abhängigkeiten, und wo welche
Schnittstelle definiert ist.
:::

::::

## Praktische Übungen

{{ offlineexercise }} `ros2 pkg list | grep ihk_pepper` nach dem Build
ausführen und mit der Paketliste auf dieser Seite vergleichen;
`ros2 interface list | grep ihk_pepper` für die Schnittstellenliste.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Paketstruktur und Build sind real getestet (siehe
[Erste Schritte](../getting-started/repository-and-environment.md)).
Keine Hardware-Abhängigkeit.

## Weiterführende Inhalte und nächste Schritte

[Pepper-Plattform und Sicherheit](../pepper-platform/index.md) für die
reale Hardware, die diese Pakete am Ende ansteuern.

```{toctree}
:maxdepth: 1
:hidden:

package-layout
```
