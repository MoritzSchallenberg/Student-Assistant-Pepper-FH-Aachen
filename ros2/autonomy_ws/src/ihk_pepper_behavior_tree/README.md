# ihk_pepper_behavior_tree

Top-Level-Verhaltensbaum für Pepper, als echter
[BehaviorTree.CPP](https://www.behaviortree.dev/) 4.x-Baum, den du in
[Groot2](https://www.behaviortree.dev/groot/) öffnen, bearbeiten und
(sobald der Executor läuft) live beobachten kannst.

**Status (Entwicklungsauftrag 1, AP2+AP6): erfolgreich gegen
`behaviortree_cpp` 4.9.0 gebaut, lokal gestartet und sauber
heruntergefahren** -- `colcon build --packages-select
ihk_pepper_behavior_tree` läuft ohne Fehler/Warnungen durch,
`colcon test` (cppcheck/cpplint-Kernprüfungen/flake8/lint_cmake/pep257/
uncrustify/xmllint) ist grün. Details, exakt welcher Compile-Fehler dabei
gefunden und behoben wurde, siehe `docs/DEVELOPMENT_ORDER_01_REPORT.md`.

**Nicht getestet**: der Baum wurde nicht gegen einen echten Pepper oder
eine echte RealSense laufen gelassen (beides in dieser Session nicht
verfügbar) -- alle Action-/Service-Aufrufe (`/pepper_bridge/say`,
`/approach_person`, ...) schlagen ohne laufende Gegenstelle einfach mit
`FAILURE` fehl, das ist erwartet und kein Absturz.

## Schritt 1: Den Baum SOFORT öffnen (ohne Installation von irgendetwas)

1. Groot2 herunterladen: <https://www.behaviortree.dev/groot/> (Download-
   Bereich, Linux-AppImage). Kein `sudo` nötig:
   ```bash
   chmod +x Groot2-*.AppImage
   ./Groot2-*.AppImage
   ```
2. In Groot2: **Datei → Open** → `ros2/autonomy_ws/src/ihk_pepper_behavior_tree/trees/pepper_main.xml`
3. Du siehst den kompletten Baum (ReactiveFallback über die 6 Subtrees
   Safety/Battery/Interaction/Presentation/GreetAndApproach/IdleAttract)
   und kannst ihn dort auch bearbeiten/umsortieren -- ohne dass irgendein
   ROS2-Node läuft.

Das ist bereits die Antwort auf "wo kann ich einstellen, was Pepper wann
macht": **Reihenfolge/Bedingungen im Baum ändern = Priorität ändern.**
Kein Python-/C++-Code nötig für einfache Umsortierungen.

## Schritt 2: Bauen + Live-Monitoring/-Steuerung

```bash
sudo apt install ros-jazzy-behaviortree-cpp   # einmalig, falls noch nicht installiert
cd ros2/autonomy_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select ihk_pepper_behavior_tree --symlink-install
source install/setup.bash
```

Danach starten (zusammen mit den anderen Nodes, siehe `ihk_pepper_bringup`):

```bash
ros2 launch ihk_pepper_behavior_tree bt_executor.launch.py
```

und in Groot2: **Connect** → `localhost:1667` (Standard-Port, per
`groot2_port`-Parameter änderbar). Ein nicht verbundenes/fehlendes Groot2
blockiert den Executor NICHT (getestet: zwei gleichzeitig laufende
Executor-Instanzen -- die zweite loggt nur eine Warnung wegen des
belegten Ports und läuft normal weiter, siehe
docs/DEVELOPMENT_ORDER_01_REPORT.md).

`bt_executor_node` reagiert sauber auf SIGINT UND SIGTERM (getestet).

## Was der Baum tut (und was nicht)

| Subtree | Ruft auf | Status |
|---|---|---|
| SafetySubtree | `/cancel_interaction`, Cancel von `/play_presentation` | Gebaut+lokal gestartet, nicht live gegen Pepper getestet |
| BatterySubtree | `/pepper_bridge/say` | dito |
| InteractionSubtree | liest nur `/interaction_state` | dito -- Dialog läuft eigenständig in `ihk_pepper_dialog`, der Baum steuert ihn NICHT aktiv (kein `RunDialogue`-Action-Server implementiert) |
| PresentationSubtree | `/play_presentation` | dito |
| GreetAndApproachSubtree | `/perception_node/person_tracks`, `/wave_gesture_events`, `/pepper_bridge/play_gesture`, `/safety_state`, `/approach_person`, `/set_interaction_state` | **Jetzt funktionsfähig verdrahtet** (Entwicklungsauftrag 1, AP6): `SelectStablePerson` wählt/validiert die Zielperson und befüllt `target_track_id` selbst -- kein toter Blackboard-Eintrag mehr. Ablauf: `IsSystemReady` → `SelectStablePerson` → (`HasGreetingCooldownExpired` → `PlayCatalogGesture`) → `WaitForGestureFromTrack` (nur exakt dieselbe track_id) → `IsApproachAllowed` → `ApproachSelectedPerson` → `SetInteractionState CONVERSATION_READY`. Bei jedem Fehlschlag räumt `ClearSelectedPerson` das Blackboard auf. Root ist jetzt `ReactiveFallback` -- Safety kann eine laufende Annäherung jederzeit präemptieren. |
| IdleAttractSubtree | `/pepper_bridge/play_gesture` | Gebaut+lokal gestartet, nicht live getestet |

Die eigentliche Sicherheitsfreigabe (`motion_capable`, `SafetyGate`) bleibt
unverändert in `ihk_pepper_interaction/supervisor_node.py` -- dieser Baum
kann sie nicht umgehen, er ruft nur die bereits abgesicherten Actions auf.
Kein Test/keine Live-Ausführung hat je `/cmd_vel` direkt veröffentlicht --
`ApproachSelectedPerson` ruft ausschließlich die bereits abgesicherte
`/approach_person`-Action auf, die ihrerseits nur über den Mock-Nav2-Server
(Entwicklungsauftrag 1, AP11) angesprochen wird, solange kein echtes Nav2
läuft.

## Neun neue/überarbeitete BT-Knoten (Entwicklungsauftrag 1, AP6)

`IsSystemReady`, `SelectStablePerson`, `HasGreetingCooldownExpired`,
`PlayCatalogGesture` (verallgemeinert von `WaveGesture` -- jetzt beliebige
Katalog-Gesten über `gesture_name`), `WaitForGestureFromTrack`,
`IsApproachAllowed`, `ApproachSelectedPerson` (umbenannt von
`ApproachTargetPerson`), `SetInteractionState`, `ClearSelectedPerson`.
Alle in `bt_nodes.hpp`/`bt_nodes.cpp`, registriert in `bt_executor_node.cpp`.

## Nächste sinnvolle Schritte

1. Live gegen echten Pepper/RealSense testen, sobald verfügbar (Entwicklungsauftrag 2).
2. `PlayCatalogGesture`s festen `gesture_name="wave_right"` durch eine
   Auswahl ersetzen, die die dem Roboter näher gelegene Hand/Seite
   berücksichtigt (aktuell immer `wave_right`, egal wo die Person steht).
3. Optional: `RunDialogue`-Action-Server in `dialog_manager_node.py`
   nachrüsten, damit `InteractionSubtree` den Dialog auch aktiv anstoßen
   statt nur beobachten kann.
