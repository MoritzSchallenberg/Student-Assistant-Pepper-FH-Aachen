# AP7.1-Hardware-Testcheckliste (Identity-Laufzeit, Rollenautorisierung, Interaktionsorchestrierung)

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7.1. **Keiner** der
folgenden Punkte wurde in dieser Entwicklungssitzung an echter Hardware
nachgewiesen -- ausschließlich gegen Mocks/Duck-Typing-Fakes/synthetische
Daten getestet, siehe `docs/DEVELOPMENT_ORDER_04_B_REPORT.md`,
AP7.1-Abschnitt "Abschlussmeldung". Kein Ergebnis dieser Liste ersetzt
`docs/AP7_HARDWARE_TEST_CHECKLIST.md` (AP7) -- beide bleiben zusammen
gültig, diese Liste ergänzt nur die in AP7.1 neu hinzugekommenen Teile.
Kein Punkt hier gilt als bestanden, ohne dass er tatsächlich an
Hardware durchgeführt wurde -- ein Prozessstart ohne echte Daten zählt
NICHT als Nachweis.

## Zehn Hardware-Testphasen (jede unten einzeln, keine als bestanden markiert)

### Phase 1 -- RealSense-Anbindung von `face_identity_node`

`hwverificationrequired`. Farb-/Tiefenbild/CameraInfo real
synchronisiert, `sync_slop_s` gegen echte Timestamps geprüft, keine
Kombination unterschiedlicher Aufnahmezeitpunkte.

### Phase 2 -- `LocalOnnxFaceDetector`/`LocalOnnxIdentityBackend` gegen ein echtes Modell

`hwverificationrequired`. Kein `onnx`-Paket/kein Modell in dieser
Session verfügbar -- nur der fail-closed-Konstruktionspfad (fehlendes
Modell blockiert den Node nicht) ist getestet.

### Phase 3 -- Liveness gegen einen echten Spoofing-Versuch (Foto/Bildschirm)

`hwverificationrequired`. Nur die Tiefenvarianz-Heuristik selbst
unit-getestet (`minimum_liveness_depth_std_m`), kein echter Täuschungsversuch.

### Phase 4 -- Enrollment/Revoke/Delete an einer echten Person MIT dokumentierter Einwilligung

`hwverificationrequired`. **Keine reale Person darf ohne dokumentierte
Einwilligung zur biometrischen Datenbank hinzugefügt werden** (Auftrag
Abschnitt 19) -- in dieser Sitzung nur gegen eine temporäre
Test-SQLite-Datei mit synthetischen Embeddings geprüft.

### Phase 5 -- Tablet-Bestätigungsseite gegen einen echten Browser/echtes Tablet

`hwverificationrequired`. `apps/web/tablet/ros_bridge.py`s
Anfrage-/Entscheidungs-Weiterleitung ist unit-getestet
(`test_tablet_ros_bridge.py`), aber nie in einem echten Browser
gegen einen echten laufenden `command_router_node` geöffnet.

### Phase 6 -- "Pepper, komm mal mit" mit einer echten, sich bewegenden Person

`hwverificationrequired`. Kein echtes Nav2 in dieser Sitzung --
`FollowCommandSubtree`/`StartAuthorizedFollow` nur gegen
`mock_nav2_server` (`follow_person_dry_run`/`command_follow_dry_run`)
geprüft.

### Phase 7 -- Codewort "Eisenbahn" während eines echten, laufenden Gesprächs

`hwverificationrequired`. Kein echtes Mikrofon -- Erkennung nur über
synthetische `InteractionCommand`-Nachrichten geprüft
(`test_ap7_1_e2e_scenarios.py`, Szenario C).

### Phase 8 -- Gruppengespräch mit echten Personen (Positionierung + Sprecherwechsel)

`hwverificationrequired`. `PositionForGroup` nur gegen
`mock_nav2_server`, `ActiveSpeakerSelector` nur gegen synthetische
DoA-Werte geprüft -- kein echter ReSpeaker, keine echte Gruppe im Raum.

### Phase 9 -- Origin-Invalidierung bei echtem Kartenwechsel/echter Neulokalisierung MIT interaction_id-Bindung

`hwverificationrequired`. Nur simulierte `/mapping_active`-/
`SafetyState`-Übergänge, keine echte RTAB-Map-Neukartierung.

### Phase 10 -- Alle vier neuen AP7.1-Launch-Modi real gegen Hardware gestartet

`hwverificationrequired` für Kamera/Mikrofon/Nav2 -- `ros2 launch` real
gestartet (kein Absturz, keine Exceptions) für `identity_offline_test`
und `authorization_tablet_test` (siehe Commit 9/10), aber ausschließlich
mit Mock-Kamera/ohne echtes Mikrofon (`PortAudio library not found` in
dieser Sitzung).

## Ergänzende, bereits automatisiert prüfbare Punkte

| # | Kriterium | Status |
|---|---|---|
| 11 | `navigation_live.launch.py` in AP7.1 ausgeführt | ✅ NIE ausgeführt |
| 12 | `/cmd_vel` in AP7.1 direkt angesprochen | ✅ NIE -- per Grep nach jedem Commit bestätigt |
| 13 | Produktionsfreigaben (`production_readiness.py`) unit-getestet | ✅ 13 Tests, alle sieben Gates einzeln |
| 14 | Alte globale Bool-Bestätigung vollständig entfernt | ✅ `test_no_global_bool_confirmation_attribute_exists_anymore` |
| 15 | Alle automatisierbaren Tests grün | ✅ 1454/1457 Python-Tests (3 unveränderter Skip), BT.CPP `colcon test` 23/0/0/4 |
| 16 | Abschlussbericht mit ehrlichem Stand/nächsten Schritten dokumentiert | ✅ `docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7.1-Abschnitt |

## Blocker vor echtem Einsatz (aus AP7.1)

- **Kein echtes ONNX-Modell/keine echte biometrische Datenbank** in
  dieser Sitzung -- jede Aussage zur echten Gesichtserkennung bleibt
  bei "Backend fail-closed getestet, nicht gegen ein echtes Modell
  verifiziert" stehen.
- **Kein echtes Mikrofon/kein echtes Nav2** (unverändert seit
  AP6/AP6.1/AP7) -- Codewort-Erkennung, Gruppen-Sprecherwechsel,
  FollowPerson- und Positionierungsfahrten bleiben bis zur ersten
  echten Hardwaretestphase bei "gegen Mocks getestet" stehen.
- **Keine reale Person wurde zur biometrischen Datenbank hinzugefügt**
  -- weder mit noch ohne Einwilligung, da in dieser Sitzung keine
  echte Kamera verfügbar war.

**Fazit**: Persistente Gesichtszuordnung/`enable_follow_person`/
Gruppenpositionierung bleiben bis auf Weiteres nur für Dry-Run-/
Offline-Test-Modi vorgesehen. Vor jeder Freigabe an echter Hardware
müssen alle zehn Phasen oben durch echte Tests (nicht nur
Quellcode-Review oder Prozessstart ohne Daten) bestätigt werden --
insbesondere darf Phase 4 (Enrollment) NIEMALS ohne vorher
dokumentierte Einwilligung der betroffenen Person stattfinden.
