# Interfaces

{{ documented }}

## Was diese Seite ist

Die vollständige `ihk_pepper_interfaces`-Schnittstellenliste, per
`ros2 interface list | grep ihk_pepper` gegen einen tatsächlich
gebauten Workspace bestätigt (siehe
[Paketaufbau und Interfaces](../ros2/package-layout.md) für Kontext).

## Messages

```{list-table}
:header-rows: 1
:widths: 30 70

* - Name
  - Verwendungskontext
* - `PersonTrack`
  - Ein einzelner Personen-Track -- siehe
    [Personen-Engagement](../perception-interaction/person-engagement.md).
* - `PersonTrackArray`
  - Alle aktuell erkannten Tracks.
* - `WaveGestureEvent`
  - Ein bestätigtes Winkgesten-Ereignis (`track_id`, `side`,
    `gesture_name`, `confidence`, `stable`).
* - `SafetyState`
  - Not-Halt/Bumper/Bewegungsfreigabe-Zustand -- zentral für
    [Systemüberblick](../architecture/system-overview.md#sicherheit-als-querschnittsthema).
* - `DialogueState`
  - Dialog-Zustand (getrennt von `interaction_state.py`s
    `InteractionState` -- Verwechslung war die Ursache des in
    [Gestenkatalog](../gestures-kinematics/gesture-catalog.md) genannten
    `SPEAKING`-Bugs).
* - `SystemHealth`
  - Akku, Erreichbarkeit.
* - `PresentationState`
  - Zustand der Tagesthema/Video/Quiz-Präsentation.
```

## Services

```{list-table}
:header-rows: 1
:widths: 30 70

* - Name
  - Verwendungskontext
* - `SetMotionPermission`
  - Der zweite Schlüssel des Zwei-Schlüssel-Sicherheitssystems -- **kein
    LLM darf diesen Service je aufrufen**.
* - `SetInteractionState`
  - Vom Verhaltensbaum genutzt, `supervisor_node.py` entscheidet über
    Zulässigkeit.
* - `CancelInteraction`
  - Teil von `SafeStopAll`.
* - `LookupPerson`, `SetConsent`, `SetDisplayName`, `DeletePerson`,
    `GetPersonContext`, `WriteMemorySummary`
  - Die sechs Personengedächtnis-Services -- siehe
    [Personengedächtnis](../dialogue-memory/person-memory.md).
* - `ReloadKnowledge`, `SelectDailyTopic`, `SetSystemMode`
  - Präsentations-/Wissensverwaltung.
```

## Actions

```{list-table}
:header-rows: 1
:widths: 30 70

* - Name
  - Verwendungskontext
* - `Say`
  - Sprachausgabe -- vom `ResponsePlanExecutor` und direkt vom
    Verhaltensbaum genutzt.
* - `PlayGesture`
  - Gestenwiedergabe -- siehe
    [Gesten und Kinematik](../gestures-kinematics/index.md).
* - `RunDialogue`
  - Die komplette Drei-LLM-Pipeline als eine Action -- siehe
    [Drei-Stufen-LLM-Pipeline](../dialogue-memory/three-stage-llm-pipeline.md).
* - `ApproachPerson`
  - Sichere Annäherung -- siehe
    [Mapping und Navigation](../mapping-navigation/index.md).
* - `FollowPerson`, `GuidePerson`
  - Weitere Navigationsfähigkeiten (nicht Gegenstand dieses Tutorials in
    derselben Tiefe wie `ApproachPerson`).
* - `PlayPresentation`
  - Tagesthema/Video/Quiz starten.
```

## Selbst nachvollziehen

```bash
source /opt/ros/jazzy/setup.bash
cd ros2/autonomy_ws
source install/setup.bash
ros2 interface list | grep ihk_pepper
ros2 interface show ihk_pepper_interfaces/action/RunDialogue
```

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Diese Liste wurde für dieses Tutorial tatsächlich
per `ros2 interface list` gegen einen frisch gebauten Workspace
abgefragt, nicht aus der Dokumentation abgeschrieben.
