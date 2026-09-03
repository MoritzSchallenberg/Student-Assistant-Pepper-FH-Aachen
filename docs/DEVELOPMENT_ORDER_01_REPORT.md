# Entwicklungsauftrag 1: RealSense-/Behavior-Tree-/Gesten-Grundlage -- Bericht

Stand: 2026-09-03. Branch `order-01-realsense-bt-gestures`, Basis-Commit
`f1221a9`. Geschrieben nach demselben Ehrlichkeitsprinzip wie
`docs/GITHUB_DEPLOYMENT_REPORT.md`/`docs/IMPLEMENTATION_REPORT.md`:
"vorbereitet" wird nie als "funktioniert am echten Pepper" dargestellt.

Dieses Dokument wird während der Umsetzung fortlaufend ergänzt (nicht erst
am Ende geschrieben), damit jeder Zwischenstand nachvollziehbar ist.

## 1. Ausgangsstand (vor jeder Änderung dieses Auftrags)

- `ros-jazzy-behaviortree-cpp` (4.9.0, apt-Installationskandidat) war
  **nicht installiert** -- `ihk_pepper_behavior_tree` konnte nicht gebaut
  werden. `ros-jazzy-realsense2-camera` **war bereits installiert**
  (vom Nutzer vor diesem Auftrag).
- `message_filters`, `tf2_ros`, `tf2_geometry_msgs`, `image_transport`
  bereits systemweit installiert.
- Keine RealSense-Hardware angeschlossen (nur Bluetooth-USB sichtbar via
  `lsusb`), kein `pyrealsense2`.
- Baseline-Build (`colcon build --symlink-install`, 3-Schritte-Split wie
  im Ansible-Deployment, `ihk_pepper_behavior_tree` ausgenommen):
  **8+1+1 Pakete grün**, keine neuen Fehler.
- Baseline-Tests (`python3 -m pytest ros2/autonomy_ws/src/ihk_pepper_tests/test/ -v`):
  **54/54 bestanden**.

### Komponenten-Tabelle

| Komponente | Status vorher | Änderung in diesem Auftrag |
|---|---|---|
| `ihk_pepper_behavior_tree` (C++) | geschrieben, nie kompiliert (`behaviortree_cpp` fehlte) | AP2: bauen, echte Fehler beheben |
| `ihk_pepper_perception` (3D-Position) | `has_3d_position` immer `False`, kein CameraInfo-Sub | AP4: synchronisierte Entprojektion |
| `ihk_pepper_perception` (Winken) | Einzelbild-Heuristik, kein zeitlicher Nachweis | AP5: `wave_detector.py` |
| `ihk_pepper_interaction`/BT-Blackboard | niemand befüllt `target_track_id` | AP6: `SelectStablePerson` |
| `ihk_pepper_bridge` (Gesten) | sequenziell, Gelenk für Gelenk | AP7: Keyframe-Schema v2 |
| RealSense-Bringup | nicht vorhanden | AP3: konfiguriert, ungetestet (keine Hardware) |
| Drei-LLM-Pipeline | nicht vorhanden | AP8: nur Verträge/Validator |
| Personengedächtnis | nicht vorhanden | AP9: nur Verträge |
| Compute-/Akku-Eingänge | nicht vorhanden | AP10: Mock-Eingänge |
| Startmodi | nur `dialog_only`/`full_system` | AP11: 4 neue Modi |

*(wird laufend fortgeführt)*

## 2. Arbeitsprotokoll

- **AP1 abgeschlossen**: Branch erstellt, Baseline-Build+Tests oben
  dokumentiert.
