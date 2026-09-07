# Interaktions-Verhaltensbaum

{{ documented }}

## Was diese Seite ist

Der vollständige, reale Baum aus
`ros2/autonomy_ws/src/ihk_pepper_behavior_tree/trees/pepper_main.xml`,
Zeile für Zeile erklärt — keine vereinfachte Nacherzählung.

## Die Wurzel: `ReactiveFallback`, nicht `Fallback`

```{figure} ../_static/images/interaction-behavior-tree.svg
:alt: Wurzel ReactiveFallback mit sieben Subtrees in fester Priorität: Safety, Battery, GreetAndApproach, Dialogue, Interaction, Presentation, IdleAttract.
:width: 100%

Jeder Tick prüft von oben nach unten neu -- ein höher priorisierter
Subtree kann eine laufende, niedriger priorisierte Aktion jederzeit
unterbrechen.
```

```xml
<BehaviorTree ID="MainTree">
  <ReactiveFallback name="PepperTopLevel">
    <SubTree ID="SafetySubtree"/>
    <SubTree ID="BatterySubtree"/>
    <SubTree ID="GreetAndApproachSubtree"/>
    <SubTree ID="DialogueSubtree"/>
    <SubTree ID="InteractionSubtree"/>
    <SubTree ID="PresentationSubtree"/>
    <SubTree ID="IdleAttractSubtree"/>
  </ReactiveFallback>
</BehaviorTree>
```

**Warum `ReactiveFallback`**: löst `SafetySubtree` in einem Tick aus,
während eine niedriger priorisierte Aktion gerade `RUNNING` ist,
präempiert `ReactiveFallback` diese Aktion sofort — ruft ihre
`onHalted()`-Methode auf, die bei allen `StatefulActionNode`s die
laufende ROS2-Action wirklich abbricht (nicht nur ignoriert). Ein
einfacher `Fallback` würde die laufende Aktion erst zu Ende laufen
lassen.

## Priorität im Detail

```{list-table}
:header-rows: 1
:widths: 10 25 65

* - #
  - Subtree
  - Bedingung / Zweck
* - 1
  - `SafetySubtree`
  - `IsSafetyTriggered` → `SafeStopAll`. Höchste Priorität.
* - 2
  - `BatterySubtree`
  - `IsBatteryLow(threshold=15.0)` → Warnung sprechen.
* - 3
  - `GreetAndApproachSubtree`
  - Stabile Person wählen, winken, annähern -- siehe unten.
* - 4
  - `DialogueSubtree`
  - `IsConversationReady` → `RunDialogueViaBT` (seit Entwicklungsauftrag 3).
* - 5
  - `InteractionSubtree`
  - Fängt `ENGAGED` allein durch hohen Interessens-Score ab.
* - 6
  - `PresentationSubtree`
  - `ShouldShowPresentation` (Zustand `IDLE`) → Tagesthema.
* - 7
  - `IdleAttractSubtree`
  - Fallback: winken bei Aufmerksamkeit, sonst ruhig stehen bleiben.
```

## `GreetAndApproachSubtree` -- der vollständige Ablauf

```xml
<BehaviorTree ID="GreetAndApproachSubtree">
  <Sequence name="GreetAndApproach">
    <IsSystemReady max_age_s="3.0"/>
    <SelectStablePerson selected_track_id="{target_track_id}"
                         min_interest_score="0.5" max_track_age_s="2.0"/>
    <Fallback name="GreetWaveApproachOrCleanup">
      <Sequence name="GreetWaveApproach">
        <HasGreetingCooldownExpired track_id="{target_track_id}" cooldown_s="60.0"/>
        <PlayCatalogGesture gesture_name="wave_right" speed_scale="1.0"/>
        <WaitForGestureFromTrack track_id="{target_track_id}" timeout_s="8.0"/>
        <IsApproachAllowed/>
        <ApproachSelectedPerson track_id="{target_track_id}" target_distance_m="1.0"/>
        <SetInteractionState state_name="CONVERSATION_READY"/>
      </Sequence>
      <ClearSelectedPerson selected_track_id="{target_track_id}"/>
    </Fallback>
  </Sequence>
</BehaviorTree>
```

Als `Sequence` (nicht reaktiv) merkt sich der Baum den Fortschritt
zwischen Ticks — kein erneutes Winken, keine erneut gesendete Aktion,
solange ein Schritt noch `RUNNING` ist. Schlägt **irgendein** Schritt
fehl (Cooldown nicht abgelaufen, Rückwink-Timeout nach 8s, Annäherung
nicht erlaubt, Annäherungs-Action schlägt fehl, Zustandswechsel
abgelehnt), fängt der äußere `Fallback` das ab und räumt über
`ClearSelectedPerson` das Blackboard auf (**immer** `SUCCESS`) — der
nächste Tick beginnt wieder frisch bei `SelectStablePerson`, **kein**
automatischer Wiederanlauf einer bereits abgebrochenen Annäherung.

**Warum `GreetAndApproach` vor `Interaction` steht**: per
Ende-zu-Ende-Test in Entwicklungsauftrag 1 gefunden --
`IsPersonEngaged` wird bereits allein durch einen hohen Interessens-
Score wahr, **ohne** dass je gewinkt/zurückgewinkt wurde. Stand
`Interaction` vor `GreetAndApproach`, gewann eine interessierte, aber
noch nie begrüßte Person sofort das Fallback, und
`GreetAndApproachSubtree` wurde nie getickt.

## `DialogueSubtree` -- seit Entwicklungsauftrag 3

```xml
<BehaviorTree ID="DialogueSubtree">
  <Sequence name="Dialogue">
    <IsConversationReady/>
    <RunDialogueViaBT session_id="{target_track_id}"/>
  </Sequence>
</BehaviorTree>
```

`RunDialogueViaBT` ist ein `StatefulActionNode`
(`onStart`/`onRunning`/`onHalted` nach demselben Muster wie
`ApproachSelectedPerson`); `onHalted()` ruft `async_cancel_goal()` auf
-- bricht bei Präemption (z.B. durch `SafetySubtree`) die laufende
Dialog-Action wirklich ab. Vor Entwicklungsauftrag 3 endete
`GreetAndApproachSubtree` nach `SetInteractionState
state_name="CONVERSATION_READY"`, ohne dass je etwas darauf reagierte --
diese bestätigte Lücke ist damit geschlossen.

## Der vollständige Knotenkatalog

Alle Blattknoten stammen 1:1 aus dem `<TreeNodesModel>` der Baumdatei
selbst (macht sie in Groot2 sichtbar/validierbar, auch ohne laufenden
Executor):

```{list-table}
:header-rows: 1
:widths: 30 70

* - Knoten
  - Zweck
* - `IsSafetyTriggered`
  - SUCCESS wenn `/safety_state.emergency_stop` oder `.bumper_active`.
* - `SafeStopAll`
  - Ruft `/cancel_interaction` und den Presentation-Cancel-Service auf.
* - `IsBatteryLow`
  - Schwelle als Port (`threshold`, Default 15.0).
* - `SpeakText`
  - Ruft `/pepper_bridge/say`.
* - `IsPersonEngaged`
  - SUCCESS wenn `/interaction_state == ENGAGED`.
* - `ShouldShowPresentation`
  - SUCCESS wenn `/interaction_state == IDLE`.
* - `PlayDailyPresentation`
  - `topic_id` leer = automatische Auswahl.
* - `IsPersonAttracted`
  - SUCCESS wenn `/interaction_state == ATTRACT`.
* - `AlwaysSuccessIdle`
  - No-op -- garantiert, dass der Fallback immer erfolgreich abschließt.
* - `IsSystemReady`
  - SUCCESS wenn `/safety_state` aktuell und weder Not-Halt noch
    Rechenleistungs-Fehler.
* - `IsApproachAllowed`
  - SUCCESS wenn `/safety_state.allow_person_approach`.
* - `SelectStablePerson`
  - Wählt/validiert die stabilste Person mit gültiger 3D-Position.
* - `HasGreetingCooldownExpired`
  - Pro `track_id`, Default 60s.
* - `PlayCatalogGesture`
  - Ruft eine Katalog-Geste über den Namen auf -- siehe
    [Gesten und Kinematik](../gestures-kinematics/index.md).
* - `WaitForGestureFromTrack`
  - `RUNNING` bis `wave_confirmed` für **exakt** diese `track_id`, oder
    Timeout (`FAILURE`).
* - `ApproachSelectedPerson`
  - Startet die `ApproachPerson`-Action.
* - `SetInteractionState`
  - Ruft `/set_interaction_state` -- `supervisor_node.py` entscheidet,
    ob erlaubt.
* - `ClearSelectedPerson`
  - Räumt das Blackboard auf.
* - `IsConversationReady`
  - SUCCESS wenn `/interaction_state == CONVERSATION_READY`.
* - `RunDialogueViaBT`
  - Ruft `/run_dialogue` -- bricht bei Präemption wirklich ab.
```

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Alle neun Knoten aus Entwicklungsauftrag 1 sind
Ende-zu-Ende gegen einen Mock-Nav2-Server funktional verifiziert.
`colcon test --packages-select ihk_pepper_behavior_tree`: 17 Tests, 0
Fehler, 0 Failures, 3 übersprungen -- unverändert seit
Entwicklungsauftrag 1. {{ hwverificationrequired }} für die Ausführung
gegen einen echten Pepper.

## Nächster Schritt

[Dialog und Gedächtnis](../dialogue-memory/index.md).
