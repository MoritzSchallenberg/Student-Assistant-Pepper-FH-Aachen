# Paketaufbau und Interfaces

{{ foundation }}

## Die elf Pakete

Alle unter `ros2/autonomy_ws/src/`. Reihenfolge grob nach Datenfluss
(Wahrnehmung → Entscheidung → Aktion), nicht alphabetisch.

```{list-table}
:header-rows: 1
:widths: 24 76

* - Paket
  - Rolle
* - `ihk_pepper_interfaces`
  - Alle Messages/Services/Actions -- keine Laufzeitlogik, nur Schema.
* - `ihk_pepper_perception`
  - Personen-Tracking, Interessens-Score, Winkgesten-Erkennung (YOLOv8-Pose).
* - `ihk_pepper_interaction`
  - Interaktions-Zustandsautomat, Sicherheits-Supervisor, Motion Guard.
* - `ihk_pepper_navigation`
  - RealSense-Diagnose, RTAB-Map-Anbindung, Annäherungsgeometrie.
* - `ihk_pepper_llm_contracts`
  - Drei-LLM-Pipeline (Verträge + Laufzeit), deterministischer Retriever,
    `ResponsePlanValidator`. Kein ROS2-Node -- reine Python-Bibliothek,
    von `ihk_pepper_dialog` importiert.
* - `ihk_pepper_person_memory`
  - Identity Registry + Vector Memory (SQLite), sechs ROS2-Services.
* - `ihk_pepper_dialog`
  - Dialog-FSM, FAQ-Cache, `ResponsePlanExecutor`,
    `RunDialogue`-Action-Server. Einziges Paket mit eigenem venv
    (`venv_dialog`, wegen `sentence-transformers`).
* - `ihk_pepper_bridge`
  - Pepper-Steuerung als ROS2-Actions (`Say`, `PlayGesture`),
    Gestenkatalog, kinematischer Compiler, Motion-Transport-Abstraktion,
    `gesturectl`-CLI.
* - `ihk_pepper_presentation`
  - Tagesthema/Video/Quiz.
* - `ihk_pepper_behavior_tree`
  - BehaviorTree.CPP-Baum (C++), einziges nicht-Python-Paket.
* - `ihk_pepper_bringup`
  - Start-Launch-Dateien für alle Modi.
* - `ihk_pepper_tests`
  - 384 pytest-Tests + committete manuelle Integrationstest-Skripte
    (`manual_*.py`, bewusst nicht von pytest eingesammelt).
```

## Reale Interfaces (`ihk_pepper_interfaces`)

Per `ros2 interface list | grep ihk_pepper` bestätigt, nach dieser
Anleitung selbst gebaut und geprüft (nicht nur aus der Dokumentation
übernommen):

```{list-table}
:header-rows: 1
:widths: 20 80

* - Typ
  - Namen
* - Messages
  - `DialogueState`, `PersonTrack`, `PersonTrackArray`,
    `PresentationState`, `SafetyState`, `SystemHealth`, `WaveGestureEvent`
* - Services
  - `CancelInteraction`, `DeletePerson`, `GetPersonContext`,
    `LookupPerson`, `ReloadKnowledge`, `SelectDailyTopic`, `SetConsent`,
    `SetDisplayName`, `SetInteractionState`, `SetMotionPermission`,
    `SetSystemMode`, `WriteMemorySummary`
* - Actions
  - `ApproachPerson`, `FollowPerson`, `GuidePerson`, `PlayGesture`,
    `PlayPresentation`, `RunDialogue`, `Say`
```

`SetMotionPermission` ist bewusst zentral hervorzuheben: das ist der
zweite Schlüssel des Zwei-Schlüssel-Sicherheitssystems (neben dem
`motion_capable`-Launch-Parameter) — siehe
[Systemüberblick](../architecture/system-overview.md#sicherheit-als-querschnittsthema).
Kein LLM darf diesen Service je aufrufen — strukturell erzwungen, siehe
[Dialog und Gedächtnis](../dialogue-memory/index.md).

## Warum `ihk_pepper_dialog` beim Standard-Build übersprungen wird

`ihk_pepper_dialog` nutzt `sentence-transformers` für semantische
FAQ-Suche, ein deutlich größeres Dependency-Set als die übrigen Pakete.
Es lebt deshalb in einem eigenen venv (`venv_dialog`) statt im
System-`site-packages`-Pfad, den `colcon build` standardmäßig nutzt --
`--packages-skip ihk_pepper_dialog` überspringt es beim
Haupt-Build-Lauf; es wird separat in seinem venv gebaut (siehe
`docs/INSTALL.md` im Repository-Wurzelverzeichnis für die genaue
Reihenfolge).

## Nächster Schritt

[Pepper-Plattform und Sicherheit](../pepper-platform/index.md).
