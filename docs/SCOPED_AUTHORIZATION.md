# Scoped (Event-Bound) Authorization (AP7.1)

Ersetzt die in AP7 nur vorbereitete, global geteilte
`/authorization/secondary_confirmation`-Bool-Nachricht (bestätigte
Sicherheitslücke, siehe `DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7.1
Commit 1/10, Abschnitt 3.2) durch eine an ein konkretes Ereignis
gebundene Anfrage/Antwort-Autorisierung. Ergänzt
`docs/PERSON_ROLES_AND_AUTHORIZATION.md` (Rollenmodell) und
`docs/PRIVILEGED_VOICE_COMMANDS.md` (Befehlsrouter).

## Interfaces

- `AuthorizationRequest.msg`: `request_id`, `event_id`,
  `interaction_id`, `session_id`, `track_id`, `person_id`, `role`,
  `command`, `requested_capability`, `created_at`, `expires_at`,
  `nonce`, `reason`.
- `AuthorizationDecision.msg`: `request_id`, `confirmed`, `reason`,
  `decided_at`.
- `ConfirmAuthorization.srv`: Request `request_id`/`nonce`/`approve`/
  `confirmed_by`; Response `success`/`reason`.

## Ablauf (`scoped_authorization.py::ScopedAuthorizationStore`)

`command_router_node.py::_on_command()` wertet
`decide_command_authorization()` **zweimal** aus (einmal mit
`secondary_confirmation_valid=False`, einmal mit `True`), um zu
unterscheiden: Policy braucht gar keine Bestätigung (sofort
granted/denied) vs. braucht eine ausstehende Bestätigung. Nur im
zweiten Fall wird `create_request()` aufgerufen und ein
`AuthorizationRequest` veröffentlicht (`authorization_status =
"pending_confirmation"` auf `/interaction/authorized_command`).

`confirm()` prüft in dieser Reihenfolge (jeder Endzustand entfernt die
Anfrage -- **genau einmal verwendbar**):

1. `request_id` bekannt? Sonst `"request_unbekannt_oder_bereits_verwendet"`.
2. `nonce` korrekt? Bei Falscheingabe wird die Anfrage **nicht
   verbraucht** (`"falscher_nonce"`) -- ein einzelner Tippfehler blockiert
   keine echte Bestätigung.
3. Nicht abgelaufen (`"request_abgelaufen"`).
4. Nicht explizit abgelehnt (`"abgelehnt"`).
5. Track/Person/Rolle/Befehl/Session seit Anfrageerstellung
   unverändert (je eigener `"*_hat_sich_geaendert"`-Grund).
6. Aktueller Sicherheitszustand gültig (`"sicherheitszustand_ungueltig"`).

Ein Hintergrund-Timer (`_purge_expired_requests`,
`authorization_request_purge_interval_s`) räumt abgelaufene Anfragen
auf und veröffentlicht eine `AuthorizationDecision(confirmed=false,
reason="request_abgelaufen")`.

## Geprüfte Angriffe/Fehler (`test_scoped_authorization.py`,
`test_command_router_node.py`)

Wiederverwendung einer alten Bestätigung, Bestätigung für einen anderen
Befehl, Bestätigung durch eine andere Person, Bestätigung nach
Track-Wechsel, nach Sitzungsende, verspätete Bestätigung, doppelte
Bestätigung, globales `True` ohne passende Anfrage -- jeder dieser Fälle
ist als eigener Test vorhanden und wird abgelehnt.

## Alter Bool-Pfad

`/authorization/secondary_confirmation` und
`_on_secondary_confirmation`/`_secondary_confirmation_valid` sind
vollständig entfernt (nicht nur deaktiviert) --
`test_no_global_bool_confirmation_attribute_exists_anymore` prüft das
per `assert not hasattr(...)`.

## Deadlock-Fund (relevant für jede künftige Änderung an diesem Node)

`command_router_node.py::main()` verwendet `MultiThreadedExecutor` +
eine gemeinsame `ReentrantCallbackGroup` für `role_lookup_client`,
`confirm_srv` und die `/interaction/command`-Subscription. **Grund**:
`_get_effective_role()` wartet blockierend auf die Antwort eines
eigenen Service-Aufrufs -- unter einem `SingleThreadedExecutor`/der
Default-`MutuallyExclusiveCallbackGroup` würde das den einzigen Thread
belegen, der die Antwort selbst verarbeiten müsste (echter, per
Live-Test gefundener Deadlock, siehe Commit 5/10-Nachricht).

## Tablet-Anbindung

`apps/web/tablet/ros_bridge.py` abonniert `/authorization/requests`/
`/authorization/decisions`, hält NUR die aktuell offene Anfrage
(gelöscht bei passender Entscheidung), filtert abgelaufene Anfragen
selbst heraus. `confirm_authorization()` ruft ausschließlich
`ConfirmAuthorization` -- das Tablet kann keine eigene Rolle setzen und
keinen eigenen `AuthorizationGrant` erzeugen.

## Verwandte Dokumente

`docs/PERSON_ROLES_AND_AUTHORIZATION.md`, `COMMAND_FOLLOW_LIFECYCLE.md`.
