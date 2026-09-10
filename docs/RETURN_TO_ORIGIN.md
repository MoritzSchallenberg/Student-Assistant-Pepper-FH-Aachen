# Ursprungspose und Rückkehr

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 9-10/11.
Implementierung: `ihk_pepper_navigation/origin_session.py`,
`return_to_origin_safety.py`, `person_approach_node.py`
(`_on_capture_origin`, `_execute_return_to_origin`),
`ihk_pepper_interfaces/srv/CaptureOrigin.srv`,
`action/ReturnToOrigin.action`, BT-Knoten `CaptureOriginPose`/
`ReturnToOriginViaBT`/`ClearSession` (`ihk_pepper_behavior_tree`).

## Ursprung sichern (`CaptureOrigin.srv`)

Sichert die AKTUELLE Roboterpose (Position + Blickrichtung) im
`map`-Frame als Rückkehrpunkt einer Sitzung -- ausschließlich im
Prozessspeicher (`OriginStore`, kein Persistieren über einen Neustart
hinaus, Auftrag: "Ursprung ist ausschließlich sitzungsgebunden").
Lehnt während laufender Kartierung ab (`"kartierung_aktiv"`) --
eine gerade entstehende Karte macht eine gesicherte Pose unsicher.
Fehlende/veraltete TF führt IMMER zu einem Fehler, NIE zu einer
geschätzten Position. Im Behavior Tree: `CaptureOriginPose`, direkt vor
`ApproachSelectedPerson` in `GreetAndApproachSubtree` eingefügt.

## Ursprungsinvalidierung

Zwei globale Trigger (`OriginStore.invalidate_all()`, verwirft ALLE
gespeicherten Urspünge, nicht nur die der aktuellen Sitzung):

- Kartierung startet (`/mapping_active` False→True).
- Lokalisierung wird neu initialisiert (`SafetyState.localization_valid`
  False→True) -- ein vorheriger Verlust+Wiedergewinn kann bedeuten, dass
  sich das Koordinatensystem verschoben hat.

Zusätzlich prüft `OriginStore.validate()` bei jeder Rückkehranfrage
Sitzungs-Zugehörigkeit und Alter (`max_origin_age_s`).

## Zurückkehren (`ReturnToOrigin.action`)

Fährt AUSSCHLIESSLICH über die bestehende `_drive_to_pose()` (Nav2 →
Velocity Smoother → Collision Monitor → Twist Mux → Motion Guard →
`/cmd_vel`, kein direkter Zugriff) -- validiert Ursprung + Sicherheit
(`return_to_origin_safety.py`: Autorisierung, Not-Halt, Bumper,
Ladekabel, Kartierung, `allow_motion`, Lokalisierung, Hindernisdaten,
BASE-Lease) VOR und WÄHREND der gesamten Fahrt (über denselben
`monitor()`-Mechanismus wie FollowPerson). `timeout_s` begrenzt die
Gesamtdauer. **Sicheres Fehlverhalten**: bei JEDER Unsicherheit
(unbekannter/fremder/veralteter Ursprung, Sicherheitsbedingung
verletzt, Nav2 nicht erreichbar, Lease abgelehnt, Zeitüberschreitung)
bleibt Pepper stehen und meldet einen präzisen Fehlergrund -- NIE eine
Näherungs-/Schätzfahrt zu einer vermuteten Pose.

## Einbettung im Behavior Tree (`EndInteractionSubtree`)

Nach einem erfolgreich beendeten Gespräch:
Verabschiedungsgeste (`goodbye_wave`) → `ReturnToOriginViaBT` →
`ClearSelectedPerson` → `ClearSession` → `SetInteractionState IDLE`.
Der gesamte Block ist in einen Fallback mit `AlwaysSuccessIdle`
gehüllt -- selbst wenn Verabschiedung/Rückkehr fehlschlagen, werden
Aufräumschritte trotzdem ausgeführt, damit `DialogueSubtree` beim
nächsten Tick nicht sofort erneut mit derselben, bereits
verabschiedeten Person ein Gespräch versucht. Details:
`docs/INTERACTION_LIFECYCLE.md`.

## Ehrlicher Stand

56 Tests (9 `OriginStore`, 10 `return_to_origin_safety.py`, 4
Invalidierungs-Trigger, 12 `_execute_return_to_origin`/
`_on_capture_origin` über Duck-Typing-Fakes inkl. eines Fake-TF-
Buffers, plus die BT.CPP-Integration per `colcon test`/manuellem
`bt_executor_node`-Lauf verifiziert). Kein echtes Nav2, keine echte
TF-Kette, kein echter Pepper in dieser Session.
