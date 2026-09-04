# Architektur: RealSense-Wahrnehmung + Behavior Tree

Stand: 2026-09-04. Überblick über Entwicklungsauftrag 1 als Ganzes --
Details in den referenzierten Einzeldokumenten.

## Datenfluss (Ziel dieses Auftrags)

```
RealSense (Farbe+Tiefe+CameraInfo, aligned_depth)
  │  message_filters.ApproximateTimeSynchronizer (sync_slop_s)
  ▼
perception_node.py
  │  YOLOv8-Pose + ByteTrack (unveraendert) → deprojection.py (Median-Patch,
  │  NaN/Inf/0/zu nah/zu fern verworfen) → tf2 (optisches Frame → base_link,
  │  fehlende/veraltete TF → has_3d_position=False, NIE eine Fantasieposition)
  │  + wave_detector.py (arm_raised → wave_candidate → wave_confirmed)
  ▼
/perception_node/person_tracks (PersonTrackArray)      /wave_gesture_events (WaveGestureEvent)
  │                                                       │
  ▼                                                       │
bt_executor_node (BehaviorTree.CPP 4.9, trees/pepper_main.xml)
  SelectStablePerson → HasGreetingCooldownExpired → PlayCatalogGesture
  → WaitForGestureFromTrack ─────────────────────────────┘
  → IsApproachAllowed → ApproachSelectedPerson → SetInteractionState
  ▼
/approach_person (ApproachPerson.action, ihk_pepper_navigation)
  │  Nav2s NavigateToPose -- in dieser Runde AUSSCHLIESSLICH gegen
  │  mock_nav2_server (published NIEMALS /cmd_vel)
  ▼
CONVERSATION_READY (/interaction_state, /interaction_state_name)
```

## Warum RealSense statt Peppers Kopfkamera

Pepper-Kopfkamera bleibt als **Fallback** nutzbar (`depth_topic` leer →
2D-only, `has_3d_position` bleibt `False`) -- für den 3D-Pfad wird eine
externe RealSense parametrisiert eingebunden
(`ihk_pepper_navigation/launch/realsense_bringup.launch.py`), siehe
`docs/REALSENSE_CALIBRATION.md` für die Kameramontage-TF-Kette.

## Behavior-Tree-Struktur

`trees/pepper_main.xml`, Root `ReactiveFallback` (nicht ein einfacher
Fallback!) über sechs Subtrees:

**Safety > Battery > GreetAndApproach > Interaction > Presentation > IdleAttract**

`ReactiveFallback` prüft `SafetySubtree` **jeden Tick neu**, auch während
eine niedriger priorisierte Aktion `RUNNING` ist -- löst Safety aus,
präemptiert das die laufende Aktion (`onHalted()` bricht die ROS2-Action
wirklich ab, siehe `StatefulActionNode`-Pattern).

**Wichtiger Architekturfund** (per E2E-Test gefunden, siehe
`docs/DEVELOPMENT_ORDER_01_REPORT.md` Punkt AP12): `GreetAndApproach`
steht bewusst **vor** `Interaction`, weil `IsPersonEngaged` bereits allein
durch einen hohen `interest_score` wahr wird (unabhängig von einem
tatsächlichen Winken) -- stünde `Interaction` davor, würde eine
interessierte, aber nie begrüßte Person das Fallback sofort gewinnen und
`GreetAndApproachSubtree` niemals ticken.

### Neun BT-Knoten (Entwicklungsauftrag 1, AP6)

Siehe `ros2/autonomy_ws/src/ihk_pepper_behavior_tree/README.md` für die
vollständige Tabelle. Kurzfassung: `IsSystemReady`, `SelectStablePerson`
(wählt+validiert die Zielperson, befüllt `target_track_id` im
Blackboard -- **niemand anderes tat das vorher**), `HasGreetingCooldownExpired`,
`PlayCatalogGesture`, `WaitForGestureFromTrack` (nur exakte `track_id`),
`IsApproachAllowed`, `ApproachSelectedPerson`, `SetInteractionState`,
`ClearSelectedPerson`.

## Designentscheidung: Wink-Erkennung als Modul, nicht als eigener Node

`wave_detector.py` läuft **innerhalb** von `perception_node.py`, nicht
als eigener ROS2-Prozess -- es braucht dieselben rohen YOLO-Keypoints,
die dort schon pro Frame vorliegen. Ein zweiter Prozess müsste diese
erst über ein neues, bandbreitenintensives Topic duplizieren. "Getrennte
Gestenbeobachtung" (Auftrag Abschnitt 5) ist hier als eigenständiges,
ROS-freies **Logikmodul** umgesetzt (wie `interest_scoring.py`), nicht
als eigener Betriebssystemprozess.

## Zwei-Schlüssel-Sicherheitsfreigabe

`SafetyGate.evaluate()` braucht **beides**: `motion_capable=true`
(Launch-Parameter, Kill-Switch) **UND** eine explizite
`/set_motion_permission`-Anfrage (Service, standardmäßig nie gestellt).
Fünf `SafetyInputs`-Felder (`localization_valid`, `obstacle_data_valid`,
`person_depth_valid`, `charging_cable_connected`, `compute_power_valid`)
haben sichere Defaults und sind gleichzeitig per Topic überschreibbar
(`/localization_valid` usw., Entwicklungsauftrag 1 AP10+AP12) -- für
echte Sensor-Wiring (Entwicklungsauftrag 2) oder kontrollierte Tests.

## Mock-Grenzen dieser Runde

- `mock_nav2_server.py` simuliert `NavigateToPose`, published **niemals**
  `/cmd_vel` -- echt getestet (Ziel gesendet, Feedback, SUCCEEDED).
- `bridge_node`s `dry_run`-Parameter lässt `Say`/`PlayGesture` sofort
  erfolgreich melden, ohne SSH-Verbindung zu Pepper.
- Beides zusammen ermöglicht den vollautomatisierten Offline-E2E-Test
  (`manual_e2e_offline_check.py`) -- 3/3 Läufe erreichen
  `CONVERSATION_READY` in ~5s, kein `/cmd_vel` in keinem Lauf.

## Was NICHT Teil dieser Runde ist

Echte RealSense-Hardware, echter Pepper, echte Nav2-Lokalisierung/
Hinderniserkennung, echte Annäherungs-Zielpose-Geometrie (aktuell fährt
`_drive_to_person()` strukturell auf die Personenposition selbst zu,
nicht auf eine Position davor -- bekannter, dokumentierter Mangel für
Entwicklungsauftrag 2), Live-Wiring von `nav2_moving`/`mapping_active`
in `bridge_node`s tatsächlichen `PlayGesture`-Aufruf.
