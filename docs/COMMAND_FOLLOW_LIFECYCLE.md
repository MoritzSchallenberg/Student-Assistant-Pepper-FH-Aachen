# "Pepper, komm mal mit" -- Command-Follow Lifecycle (AP7.1)

Verbindet den in AP7 entwickelten, sicherheitsgeprüften
`command_router_node.py`/`person_approach_node.py`-Pfad erstmals mit dem
Behavior Tree (AP7.1.7/Commit 6/10). Ergänzt
`docs/FOLLOW_PERSON_RUNTIME.md` (AP7, FollowPerson-Action selbst) und
`docs/RETURN_TO_ORIGIN.md`.

## Aktivierungsbedingungen

Alle müssen gleichzeitig gelten (technisch über die Kombination aus
`command_router_node.py::decide_command_authorization()` und
`WaitForAuthorizedFollowCommand`s Grant-Abgleich erzwungen):
`recognized_command == follow_speaker`, Identität mit ausreichender
Konfidenz, Rolle erlaubt (Standard: nur EMPLOYEE/ADMIN, siehe
`docs/PERSON_ROLES_AND_AUTHORIZATION.md`), sekundäre Bestätigung
gültig, dieselbe Person weiterhin präsent (Track-ID-Bindung),
Tiefendaten/Lokalisierung/Hindernisdaten gültig, `allow_motion`,
Ladekabel nicht angeschlossen, BASE-Lease verfügbar. Ein STUDENT erhält
eine freundliche Ablehnung ohne jede Bewegungsfreigabe (kein
`AuthorizationGrant`).

## Ablauf (13 Schritte, wie im Auftrag verlangt)

1. Wakeword + Befehl erkennen (`sound_direction_transform_node.py`).
2. Sprecher einem sichtbaren Track zuordnen
   (`audiovisual_association_node.py`, AP7).
3. Persistente Identität bestätigen (`face_identity_node.py`).
4. Rolle aus der Registry lesen (`GetEffectiveRole`, NIE aus
   `PersonIdentity.role`).
5. Sekundäre Bestätigung anfragen (`scoped_authorization.py`, siehe
   `SCOPED_AUTHORIZATION.md`).
6. Ursprungspose sitzungs- **und interaktionsgebunden** sichern
   (`CaptureOriginPose`, `interaction_id="authorized_follow"`, AP7.1
   Commit 8/10).
7. Gültigen `AuthorizationGrant` erzeugen
   (`command_router_node.py::_issue_grant`).
8. FollowPerson starten (`StartAuthorizedFollow` → `/follow_person`).
9. Grant während der Fahrt erneut prüfen (`person_approach_node.py`
   validiert unabhängig über eine eigene `AuthorizationGrantCache`).
10. Navigation bei Abbruch stoppen (`onHalted()` wartet auf
    Cancel-Bestätigung, siehe `docs/ACTION_CANCELLATION.md`).
11. Verabschiedungs-/Abbruchmeldung sprechen.
12. Sicher zur Ursprungspose zurückkehren
    (`ReturnToOriginViaBT`, `interaction_id="authorized_follow"`).
13. Sitzung/Grants vollständig aufräumen (`ClearSession`).

Sprecher und sichtbare Zielperson müssen zweifelsfrei dieselbe Person
sein, sonst startet **keine** Fahrt (`WaitForAuthorizedFollowCommand`
verlangt einen Grant für exakt denselben `track_id`+`command`).

## Behavior-Tree-Umsetzung

`FollowCommandSubtree` (`pepper_main.xml`):
`WaitForAuthorizedFollowCommand` → `CaptureOriginPose` →
`StartAuthorizedFollow` → `Fallback(ReturnToOriginViaBT,
PublishInteractionLifecycleState(ERROR)+AlwaysSuccessIdle)` →
`ClearSession`. Reuse-first: `CaptureOriginPose`/`ReturnToOriginViaBT`/
`ClearSession` sind dieselben, bereits in AP7 Commit 9/10 getesteten
Knoten -- **keine** Duplizierung der Ursprungs-/Rückkehrlogik in
`person_approach_node.py`. Das Feld
`FollowPerson.Goal.return_to_origin_after_end` bleibt deshalb bewusst
vom Node selbst unausgewertet; die Rückkehr wird ausschließlich
baumseitig erzwungen.

Priorität im Root-`ReactiveFallback`: Safety > Battery >
CodewordInterrupt > **FollowCommand** > PersonInteractionLifecycle >
GroupConversation > Interaction > Presentation > IdleAttract -- ein
bereits autorisierter Follow-Befehl hat Vorrang vor einem neuen
Gesprächsversuch, steht aber unter dem Codewort.

## Fehlerbehandlung bei der Rückkehr

Siehe `INTERACTION_LIFECYCLE.md` (Abschnitt "Sichtbarer Fehlerzustand")
-- ein fehlgeschlagenes `ReturnToOriginViaBT` wird seit AP7.1 Commit
8/10 über `PublishInteractionLifecycleState(state_name="ERROR")`
sichtbar gemacht, nicht mehr stillschweigend absorbiert.

## Ehrlich offen

Kein echter Follow-Testlauf mit Pepper (`hwverificationrequired`) --
ausschließlich gegen `mock_nav2_server` verifiziert. "Sprecher == sichtbare
Zielperson" wird über die bestehende Track-ID-Bindung sichergestellt,
keine zusätzliche, unabhängige Re-Verifikation auf BT-Ebene.

## Verwandte Dokumente

`SCOPED_AUTHORIZATION.md`, `docs/FOLLOW_PERSON_RUNTIME.md`,
`docs/RETURN_TO_ORIGIN.md`, `INTERACTION_LIFECYCLE.md`.
