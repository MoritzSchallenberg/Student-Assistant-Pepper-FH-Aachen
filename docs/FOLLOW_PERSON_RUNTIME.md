# FollowPerson-Laufzeit

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 8/11.
Implementierung: `ihk_pepper_navigation/person_approach_node.py`
(`_execute_follow()`), `authorization_grant_cache.py`,
`follow_person_safety.py`, `approach_pose.py` (`compute_approach_pose`,
`should_replan`).

Standardmäßig deaktiviert (`enable_follow_person:=false`), NUR über
`interaction_full_safe.launch.py mode:=follow_person_dry_run` scharf
zu Testzwecken (weiterhin gegen `mock_nav2_server`, nie echtes Nav2).

## Ablauf einer FollowPerson-Ausführung

1. **Autorisierung validieren**: `authorization_grant_id` aus dem Goal
   wird gegen `AuthorizationGrantCache.validate_and_consume()` geprüft
   (Grant-ID, Track-ID UND Befehl `follow_speaker` müssen exakt
   passen, einmalige Verwendung) -- kein Start ohne gültigen,
   passenden Grant. Siehe `docs/PERSON_ROLES_AND_AUTHORIZATION.md`.
2. **Sicherheit prüfen** (`check_follow_person_safety()`, VOR JEDEM
   einzelnen Fahrsegment, nicht nur einmalig): Autorisierung, Not-Halt,
   Bumper, Ladekabel, `allow_motion`/`allow_person_approach`,
   Lokalisierung, Hindernis-/Tiefendaten, BASE-Lease, Track-Frische,
   Keepout, Menschenmenge-Mehrdeutigkeit (`is_crowd_ambiguous()`),
   Akku-Schwelle.
3. **Zielpose berechnen**: `compute_approach_pose()` (dieselbe
   Geometrie wie `ApproachPerson`, Auftrag 2/AP9) -- NIE die
   Personenposition selbst als Fahrziel, immer eine Position
   `target_distance_m` davor.
4. **Fahren**: über die bestehende `_drive_to_pose()` (BASE-Lease-
   Erwerb/-Erneuerung/-Freigabe unverändert wiederverwendet, kein
   Duplikat).
5. **Neuplanung NUR bei relevanter Bewegung**: ein `monitor()`-Callback
   während der Fahrt prüft Positionsschwelle
   (`follow_person_minimum_goal_shift_m`, über `approach_pose.should_replan()`)
   UND Winkelschwelle (`follow_person_minimum_goal_yaw_change_rad`) --
   bei Überschreitung bricht `_drive_to_pose()` sauber mit
   `"replan_needed"` ab, die äußere Schleife berechnet eine neue Pose
   und fährt weiter, OHNE das als echten Fehler zu werten.
6. **Zeitlimit**: `follow_person_maximum_duration_s` begrenzt die
   Gesamtdauer der gesamten Ausführung.
7. **Trackverlust**: führt zu einem SOFORTIGEN, sauberen Abbruch.
   **Kein Kopf-Suchverhalten, keine automatische Basisrotation** --
   bewusst nicht Teil dieses Auftrags (Section 20: "höchstens den Kopf
   vorsichtig suchen lassen" ist NICHT implementiert, ehrlich offen).

## Warum kein direkter Personenzugriff

Wie bei `ApproachPerson` gilt: `_get_robot_pose_in_frame()` liefert bei
fehlender/veralteter TF IMMER `ok=False`, NIE eine geschätzte Position
-- eine Schätzfahrt ist strukturell unmöglich.

## Ehrlicher Stand

43 Tests (9 `AuthorizationGrantCache`, 17
`follow_person_safety.py`, 17 `_execute_follow()`-Ausführung über
Duck-Typing-Fakes inkl. eines Fake-Nav2-Clients mit verzögerten
Ergebnissen für das Neuplanungsverhalten). Ausschließlich gegen Mocks
getestet -- kein echtes Nav2, kein echter Pepper, keine echte Person in
dieser Session. `enable_follow_person=true` wurde in
`follow_person_dry_run` real gestartet (`ros2 launch`), aber nur als
Software-Verdrahtungsprüfung, nicht als echte Fahrt.
