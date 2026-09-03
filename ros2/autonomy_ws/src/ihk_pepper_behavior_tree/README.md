# ihk_pepper_behavior_tree

Top-Level-Verhaltensbaum für Pepper (Entwicklungsauftrag Abschnitt 39),
als echter [BehaviorTree.CPP](https://www.behaviortree.dev/) 4.x-Baum,
den du in [Groot2](https://www.behaviortree.dev/groot/) öffnen, bearbeiten
und (sobald der Executor läuft) live beobachten kannst.

**Ehrlicher Status (siehe `docs/IMPLEMENTATION_REPORT.md`): der C++-Teil dieses
Pakets ist geschrieben, aber NICHT kompiliert/getestet**, weil
`behaviortree_cpp` auf dem Entwicklungsrechner dieser Session nicht
installiert war (kein sudo-Zugriff). Der Baum selbst (`trees/pepper_main.xml`)
ist reines XML und funktioniert schon jetzt in Groot2, unabhängig vom
C++-Code.

## Schritt 1: Den Baum SOFORT öffnen (ohne Installation von irgendetwas)

1. Groot2 herunterladen: <https://www.behaviortree.dev/groot/> (Download-
   Bereich, Linux-AppImage). Kein `sudo` nötig:
   ```bash
   chmod +x Groot2-*.AppImage
   ./Groot2-*.AppImage
   ```
2. In Groot2: **Datei → Open** → `ros2/autonomy_ws/src/ihk_pepper_behavior_tree/trees/pepper_main.xml`
3. Du siehst den kompletten Baum (Fallback über die 6 Subtrees Safety/
   Battery/Interaction/Presentation/Navigation/IdleAttract) und kannst ihn
   dort auch bearbeiten/umsortieren — ohne dass irgendein ROS2-Node läuft.

Das ist bereits die Antwort auf "wo kann ich einstellen, was Pepper wann
macht": **Reihenfolge/Bedingungen im Baum ändern = Priorität ändern.**
Kein Python-/C++-Code nötig für einfache Umsortierungen.

## Schritt 2: Live-Monitoring/-Steuerung (braucht behaviortree_cpp)

Damit Groot2 zusätzlich **live** anzeigt, welcher Knoten gerade läuft
(grün/rot eingefärbt, während Pepper tatsächlich etwas tut), muss der
C++-Executor-Node laufen. Dafür fehlt noch ein System-Paket:

```bash
sudo apt install ros-jazzy-behaviortree-cpp
cd ros2/autonomy_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
colcon build --packages-select ihk_pepper_behavior_tree --symlink-install
source install/setup.bash
```

**Dieser Build wurde in dieser Session nicht durchgeführt** (fehlendes
Paket) — es ist möglich, dass beim ersten echten Build noch kleinere
Kompilierfehler auftauchen (API-Details von `behaviortree_cpp` 4.9, die
ich nicht gegenprüfen konnte). Falls das passiert: Fehlermeldung zeigen,
lässt sich in der Regel schnell fixen.

Danach starten (zusammen mit den anderen Nodes, siehe `ihk_pepper_bringup`):

```bash
ros2 launch ihk_pepper_behavior_tree bt_executor.launch.py
```

und in Groot2: **Connect** → `localhost:1667` (Standard-Port, per
`groot2_port`-Parameter änderbar).

## Was der Baum tut (und was nicht)

| Subtree | Ruft auf | Status |
|---|---|---|
| SafetySubtree | `/cancel_interaction`, Cancel von `/play_presentation` | Logik gegen echte Topics/Services geschrieben, ungetestet (s.o.) |
| BatterySubtree | `/pepper_bridge/say` | dito |
| InteractionSubtree | liest nur `/interaction_state` | dito -- Dialog läuft eigenständig in `ihk_pepper_dialog`, der Baum steuert ihn NICHT aktiv (kein `RunDialogue`-Action-Server implementiert) |
| PresentationSubtree | `/play_presentation` | dito |
| NavigationSubtree | `/approach_person` | **Strukturell vorbereitet, aber praktisch inaktiv**: niemand befüllt aktuell das Blackboard-Feld `target_track_id` -- dafür fehlt noch ein Knoten, der aus `/perception_node/person_tracks` eine Zielperson auswählt |
| IdleAttractSubtree | `/pepper_bridge/play_gesture` | dito |

Die eigentliche Sicherheitsfreigabe (`motion_capable`, `SafetyGate`) bleibt
unverändert in `ihk_pepper_interaction/supervisor_node.py` -- dieser Baum
kann sie nicht umgehen, er ruft nur die bereits abgesicherten Actions auf.

## Nächste sinnvolle Schritte (nicht Teil dieser Session)

1. `sudo apt install ros-jazzy-behaviortree-cpp` + `colcon build` +
   entstehende Kompilierfehler fixen.
2. Einen `SelectTargetPerson`-BT-Knoten schreiben, der aus
   `/perception_node/person_tracks` per `interest_score` die beste Person
   wählt und `target_track_id` ins Blackboard schreibt -- erst dann ist
   `NavigationSubtree` tatsächlich nutzbar.
3. Optional: `RunDialogue`-Action-Server in `dialog_manager_node.py`
   nachrüsten, damit `InteractionSubtree` den Dialog auch aktiv anstoßen
   statt nur beobachten kann.
