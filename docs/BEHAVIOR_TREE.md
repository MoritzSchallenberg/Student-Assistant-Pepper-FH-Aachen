# Behavior Tree: Architektur

Stand: 2026-09-09. Entwicklungsauftrag 1 (Grundgerüst), erweitert über
Entwicklungsauftrag 3 (Dialog/Gedächtnis) und Entwicklungsauftrag 04-B
(Cancel-Propagation, AP5B). Implementierung:
`ros2/autonomy_ws/src/ihk_pepper_behavior_tree/` (`bt_nodes.hpp/.cpp`,
`bt_executor_node.cpp`, `trees/pepper_main.xml`). Für Groot2-Bedienung,
Baumaufbau und Build-Nachweis siehe das ausführlichere
`ihk_pepper_behavior_tree/README.md` -- dieses Dokument beschreibt die
Cancel-/Sicherheitsarchitektur der Custom-Knoten selbst.

## Warum ein echter BT.CPP-Baum, kein eigener Zustandsautomat

`pepper_main.xml` ist ein echter [BehaviorTree.CPP](https://www.behaviortree.dev/)
4.x-Baum, in Groot2 sichtbar/editierbar. Ein `ReactiveFallback` über
mehrere Subtrees (Safety/Battery/Interaction/Presentation/
GreetAndApproach/IdleAttract) tickt bei jedem Durchlauf ALLE Zweige neu
-- ein höher priorisierter Zweig (z.B. Safety) kann einen gerade
laufenden niedriger priorisierten Zweig (z.B. eine laufende
Präsentation) jederzeit unterbrechen (`onHalted()` wird aufgerufen).
Genau dieser Halt-Mechanismus ist der Ansatzpunkt für die
Cancel-Propagation dieses Dokuments.

## Knoten-Katalog (Actions, die eine ROS2-Action aufrufen)

| Knoten | Ruft auf | Hat `onHalted()`-Cancel-Logik |
|---|---|---|
| `SpeakText` | `/pepper_bridge/say` | ja |
| `PlayCatalogGesture` | `/pepper_bridge/play_gesture` | ja |
| `PlayDailyPresentation` | `/play_presentation` | ja |
| `ApproachSelectedPerson` | `/approach_person` | ja |
| `RunDialogueViaBT` | `/run_dialogue` | ja |
| `WaitForGestureFromTrack` | (Topic-Subscription, keine Action) | nein -- kein Goal abzubrechen |
| `SetInteractionState` | `/set_interaction_state` (Service) | nein -- kein Goal abzubrechen |

## `onHalted()`-Cancel-Architektur (Entwicklungsauftrag 04-B, AP5B, Abschnitt 13)

Vor AP5B riefen alle fünf Action-Knoten in `onHalted()` lediglich
`client_->async_cancel_goal(goal_handle_)` auf -- komplett ohne
Feedback oder Bestätigung ("fire-and-forget"). Ein Cancel-Request kann
verloren gehen oder lange unbeantwortet bleiben, ohne dass der Knoten
das je bemerkt.

Neue, ROS-unabhängige (per `std::future` isoliert testbare)
Hilfsfunktion in `bt_nodes.hpp`:

```cpp
template<typename FutureT>
bool waitForBoundedCancelConfirmation(
    FutureT & cancel_future,
    std::chrono::milliseconds timeout,   // kHaltCancelConfirmTimeout = 250ms
    const rclcpp::Logger & logger,
    const std::string & node_label);
```

Jeder der fünf Knoten ruft sie jetzt in `onHalted()` auf und speichert
das Ergebnis in `last_halt_cancel_confirmed_`
(`lastHaltCancelConfirmed()`-Getter für Tests/Diagnose). 250ms ist
bewusst kurz: der übergebene Future wird bereits fertig, sobald der
Action-Server die Cancel-Anfrage über den `CancelGoal`-Service
ANGENOMMEN hat -- ein schneller, rein lokaler ROS2-Vorgang, keine
Wartezeit auf tatsächliche Hardwarebewegung. `true` bedeutet also NUR
"der Server hat den Abbruch akzeptiert", NICHT "Pepper hat wirklich
gestoppt" (siehe `docs/ACTION_CANCELLATION.md` für die vollständige
Unterscheidung ROS-Cancel vs. Hardware-Stopp).

Bewusst BEGRENZT (nie unbegrenzt) -- ein blockierendes `onHalted()`
würde den gesamten BT-Tick anhalten, der Baum tickt aber typischerweise
mit fester Rate und darf nicht durch einen einzelnen Knoten verzögert
werden.

Die eigentliche "kein unmittelbar danach gestartetes konkurrierendes
Ziel"-Garantie liegt NICHT im BT-Knoten selbst (ein `onHalted()` kann
grundsätzlich nicht garantieren, dass der Baum diesen Knoten nicht in
einem der nächsten Ticks erneut startet), sondern eine Schicht tiefer:
der Aktuator-Arbiter (siehe `docs/ACTUATOR_ARBITER.md`) lehnt eine neue
Lease-Anfrage ab, solange die alte Lease noch nicht freigegeben ist --
ein zu früh erneut gesendetes Ziel würde serverseitig ohnehin
abgelehnt.

## Getestet

Neues `test/test_bt_cancel_confirmation.cpp` (gtest, 3 Tests, über
`ament_add_gtest` verdrahtet -- ROS-unabhängig, testet
`waitForBoundedCancelConfirmation()` direkt per `std::promise`/
`std::future`, ohne echten Action-Server): Bestätigung bereits
eingetroffen, Timeout ohne Bestätigung (begrenzte Laufzeit verifiziert),
Bestätigung trifft knapp innerhalb des Fensters ein. `colcon test
--packages-select ihk_pepper_behavior_tree`: **23 Tests, 0 Fehler, 0
Fehlschläge, 4 übersprungen** (vorher 17/0/0/3 -- 6 neue, ausschließlich
funktionale gtest-Tests, keine Regression in den bestehenden
Lint-/Stil-Prüfungen).

**Nicht getestet**: ein vollständiger End-zu-Ende-Halt-Test mit einem
echten Action-Server (statt eines isolierten `std::future`) wurde nicht
gebaut -- dafür bräuchte es einen Mock-Action-Server-Testharness, den
dieses Paket bisher nicht hat (die bestehenden 17 "Tests" sind
Lint-/Stil-Prüfungen, kein gtest-Harness mit echtem `rclcpp_action`).
Kein echter Pepper/keine echte RealSense in dieser Session erreichbar
-- alle Action-Aufrufe schlagen ohne laufende Gegenstelle mit `FAILURE`
fehl (erwartet, siehe `ihk_pepper_behavior_tree/README.md`).
