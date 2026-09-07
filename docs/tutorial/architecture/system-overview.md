# Systemüberblick

{{ documented }}

## Was diese Seite ist

Der vollständige, reale Datenfluss vom Kamerabild bis zur Roboteraktion,
Stand Entwicklungsauftrag 3. Jede hier genannte Komponente existiert als
echter Code in `ros2/autonomy_ws/src/`; wo eine Verbindung nur
vorbereitet, aber nicht live verdrahtet ist, steht das explizit dabei.

## Die elf Pakete und ihre Rollen

```{figure} ../_static/images/pepper-system-architecture.svg
:alt: Datenfluss vom RealSense-/Pepper-Kamerabild über Perception (Personen-Tracking, Winkgeste), den Verhaltensbaum, Dialog/LLM-Pipeline und Gestenkatalog bis zu Pepper-Bridge und Motion Guard, mit dem separaten RealSense-only-Navigationspfad daneben.
:width: 100%

Perception, Verhaltensbaum, Dialog/Gedächtnis, Gesten und Navigation als
getrennte Pakete mit klaren Schnittstellen -- kein Modul ruft ein
anderes direkt auf, alles läuft über ROS2-Topics/Services/Actions.
```

| Paket | Rolle |
|---|---|
| `ihk_pepper_interfaces` | Alle Messages/Services/Actions -- die einzige gemeinsame Sprache zwischen den übrigen Paketen |
| `ihk_pepper_perception` | Personen-Tracking (YOLOv8-Pose), Interessens-Score, Winkgesten-Erkennung -- siehe [Wahrnehmung und Interaktion](../perception-interaction/index.md) |
| `ihk_pepper_behavior_tree` | BehaviorTree.CPP-Baum, entscheidet PRO TICK, welches Teilsystem gerade das Sagen hat -- siehe [Entscheidungsfindung](../decision-making/index.md) |
| `ihk_pepper_interaction` | Interaktions-Zustandsautomat, Sicherheits-Supervisor, **Motion Guard** (letzte Instanz vor jeder Bewegung) |
| `ihk_pepper_navigation` | RealSense-Diagnose, RTAB-Map-Anbindung (Odometrie/Mapping/Lokalisierung), Annäherungsgeometrie -- siehe [Mapping und Navigation](../mapping-navigation/index.md) |
| `ihk_pepper_llm_contracts` | Die drei LLM-Stufen (Verträge + Laufzeit) + deterministischer Retriever + `ResponsePlanValidator` -- siehe [Dialog und Gedächtnis](../dialogue-memory/index.md) |
| `ihk_pepper_person_memory` | Identity Registry + Vector Memory (SQLite), einwilligungsgebunden |
| `ihk_pepper_dialog` | Dialog-FSM, FAQ-Cache, `ResponsePlanExecutor`, `RunDialogue`-Action-Server |
| `ihk_pepper_bridge` | Pepper-Steuerung als ROS2-Actions (`Say`, `PlayGesture`), Gestenkatalog, kinematischer Compiler, Motion Transport -- siehe [Gesten und Kinematik](../gestures-kinematics/index.md) |
| `ihk_pepper_presentation` | Tagesthema/Video/Quiz-Präsentationen |
| `ihk_pepper_bringup` | Start-Launch-Dateien für alle Modi (`offline_test`, `realsense_test`, `navigation_dry_run`, `navigation_live`, u.a.) |

## Der zentrale Ablauf: Verhaltensbaum-Priorität

Der Verhaltensbaum (`ros2/autonomy_ws/src/ihk_pepper_behavior_tree/trees/pepper_main.xml`)
ist ein `ReactiveFallback` mit fester Priorität, JEDEN Tick neu geprüft:

```text
Safety > Battery > GreetAndApproach > Dialogue > Interaction >
Presentation > IdleAttract
```

`ReactiveFallback` (nicht ein einfacher `Fallback`) bedeutet: löst
`SafetySubtree` in einem Tick aus, während z.B. gerade ein Dialog läuft,
**bricht** der Fallback die laufende Aktion aktiv ab (ruft `onHalted()`
auf, das die laufende ROS2-Action wirklich abbricht), statt sie zu Ende
laufen zu lassen. Details und der vollständige Baum:
[Interaktions-Verhaltensbaum](../decision-making/interaction-behavior-tree.md).

## Zwei weitgehend unabhängige Datenpfade

**Wahrnehmung → Interaktion** (Kamerabild bis Dialog/Geste):

```text
RealSense-/Pepper-Kamerabild
  → ihk_pepper_perception (YOLOv8-Pose: Personen-Tracking, Interessens-
    Score, Winkgesten-Erkennung)
  → Verhaltensbaum (wählt stabilste Person, entscheidet Priorität)
  → RunDialogueViaBT → Drei-LLM-Pipeline → ResponsePlanExecutor
  → ihk_pepper_bridge (Say-/PlayGesture-Actions)
```

**Navigation** (RealSense-only, komplett getrennt von Peppers eigener
Odometrie -- siehe [Mapping und Navigation](../mapping-navigation/index.md)):

```text
RealSense → statische Kopf-/Kamera-TF → RTAB-Map (Odometrie/SLAM/
Lokalisierung) → Nav2 (Controller/Planner/BT-Navigator) →
Velocity Smoother → Collision Monitor → Motion Guard → /cmd_vel →
naoqi_driver2 → Pepper
```

Beide Pfade laufen über denselben **Motion Guard** als letzte Instanz,
bevor irgendein Bewegungsbefehl den Roboter tatsächlich erreicht -- siehe
unten.

## Sicherheit als Querschnittsthema

Drei unabhängige, sich überlappende Schichten, keine ersetzt die andere:

1. **`SafetyGate`** (Entwicklungsauftrag 1): aggregiert Bumper/Not-Halt/
   Sicherheitszustand für den Verhaltensbaum.
2. **`Motion Guard`** (Entwicklungsauftrag 2, `ihk_pepper_interaction/
   motion_guard.py`): letzte Instanz direkt vor `/cmd_vel`, prüft
   sequenziell Bumper, Not-Halt, expliziten Livebewegungsmodus
   (`enable_live_motion`, Standard `false`), RealSense-Diagnose,
   Odometrie-/Lokalisierungs-Gültigkeit, Hindernisdaten, Kopf-
   Navigationspose, aktive Geste, Befehlsalter -- **jeder einzelne**
   Grund blockiert sofort und unabhängig von allen anderen. Bei
   Blockade: fortlaufend (10 Hz) Nullgeschwindigkeit, kein einmaliger
   Stopp.
3. **Zwei-Schlüssel-System für Bewegungsfreigabe**: `motion_capable`
   (Launch-Parameter) UND eine explizite `/set_motion_permission`-Anfrage
   müssen beide zutreffen -- Standard für beide ist überall `false`.

`navigation_live.launch.py` ist technisch vorbereitet, wurde aber in
keiner bisherigen Entwicklungssitzung tatsächlich gestartet — siehe
{ref}`Live navigation gesperrt <warum-livenavigation-gesperrt-bleibt>`.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ documented }} Diese Seite beschreibt Architektur/Code-Struktur, keine
Live-Ausführung. Jede einzelne Komponente hat ihren eigenen, genaueren
Verifikationsstand auf ihrer eigenen Themenseite — siehe dort, nicht
hier pauschal annehmen.

## Weiterführende Inhalte und nächste Schritte

- [ROS 2](../ros2/index.md) für den Paketaufbau im Detail.
- [Entscheidungsfindung](../decision-making/index.md) für den
  vollständigen Verhaltensbaum.
- [Dialog und Gedächtnis](../dialogue-memory/index.md) für die
  LLM-Pipeline.
- `docs/DEVELOPMENT_ORDER_01_REPORT.md`,
  `docs/DEVELOPMENT_ORDER_02_REPORT.md`,
  `docs/DEVELOPMENT_ORDER_03_REPORT.md` im Repository-Wurzelverzeichnis
  für die vollständige, chronologische Entwicklungsgeschichte.
