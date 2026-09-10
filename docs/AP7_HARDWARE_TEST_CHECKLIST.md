# AP7-Hardware-Testcheckliste (Rollen/Codewörter/Gruppen/FollowPerson/Rückkehr)

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7. **Keiner** der
folgenden Punkte wurde in dieser Entwicklungssitzung an echter Hardware
nachgewiesen -- ausschließlich gegen Mocks/Duck-Typing-Fakes/synthetische
Daten getestet, siehe `docs/DEVELOPMENT_ORDER_04_B_REPORT.md`,
AP7-Abschnitt "Ehrlicher Stand". Diese Liste entscheidet, wann
`enable_follow_person`/`allow_person_approach`/eine echte
Gesichtserkennungs-Anbindung in Produktion freigegeben werden dürfen.

| # | Kriterium | Status |
|---|---|---|
| 1 | `peoplectl set-role`/`revoke-role`/`delete` gegen eine echte, laufende Identitätsdatenbank geprüft | ⚠️ nur gegen eine temporäre Test-SQLite-Datei, keine echte NUC-Installation |
| 2 | `POLICY_ROLE_ONLY_DEVELOPMENT` bleibt in `production_mode=true` gesperrt | ✅ unit-getestet (`authorization_policy.py`) |
| 3 | Codewort "Eisenbahn"/"Pepper komm mal mit" wird aus echter Sprache erkannt | ⛔ kein echtes Mikrofon in dieser Session, nur Fake-Whisper-Text |
| 4 | Privilegierter Befehl verlangt ALLE sieben Bedingungen (nicht nur Gesichtserkennung) | ✅ unit-getestet (`command_authorization_decision.py`) |
| 5 | `LocalOnnxIdentityBackend` erkennt ein echtes, eingewilligtes Gesicht | ⛔ kein `onnx`-Paket zum Testmodell-Bau, kein echtes Gesicht |
| 6 | Liveness-Prüfung lehnt ein Foto/einen Bildschirm tatsächlich ab | ⛔ nur die Tiefenvarianz-Heuristik selbst unit-getestet, kein echter Spoofing-Versuch |
| 7 | Biometrischer Speicher (0600, verschlüsselt) unter der echten Zielpfad-Konfiguration geprüft | ⚠️ Verschlüsselung/Rechte unit-getestet, nicht unter `/var/lib/ihk-pepper/identity/` selbst |
| 8 | Gruppenverfolgung bildet eine echte, mehrköpfige Gruppe im Raum | ⛔ nur synthetische Personentrack-Daten |
| 9 | Gruppen-Beobachtungspose fährt tatsächlich in den richtigen Abstand | ⛔ kein echtes Nav2, keine echte Gruppe |
| 10 | Aktiver Sprecher wird bei echtem Sprachwechsel korrekt umgeschaltet | ⛔ kein echter ReSpeaker (unverändert seit AP6/AP6.1) |
| 11 | `FollowPerson` fährt tatsächlich hinter einer sich bewegenden Person her | ⛔ kein echtes Nav2, `mock_nav2_server` in `follow_person_dry_run` |
| 12 | `FollowPerson` bricht bei echtem Trackverlust sauber ab (kein Kopf-/Basissuchverhalten) | ⚠️ Abbruchverhalten unit-getestet, kein echter Trackverlust am Roboter |
| 13 | `CaptureOrigin`/`ReturnToOrigin` funktionieren mit echter TF-Kette/echtem Nav2 | ⛔ Fake-TF-Buffer, kein echtes Nav2 |
| 14 | Ursprungsinvalidierung bei echtem Kartenwechsel/echter Neulokalisierung | ⛔ nur simulierte `/mapping_active`-/`SafetyState`-Übergänge |
| 15 | Vier neue Launch-Modi real gegen Hardware gestartet | ⚠️ `ros2 launch` real gestartet (kein Absturz, keine Exceptions), aber ohne echtes Mikrofon/echte Kamera/echtes Nav2 -- reine Software-Verdrahtungsprüfung |
| 16 | `navigation_live.launch.py` in AP7 ausgeführt | ✅ NIE ausgeführt |
| 17 | `/cmd_vel` in AP7 direkt angesprochen | ✅ NIE -- per Grep nach jedem Commit bestätigt |
| 18 | Alle automatisierbaren Tests grün | ✅ 1297/1300 Python-Tests (3 unveränderter Skip), BT.CPP `colcon test` 7/7 |
| 19 | Abschlussbericht mit ehrlichem Stand/nächsten Schritten dokumentiert | ✅ `docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7-Abschnitt |

## Blocker vor echtem Einsatz (aus AP7 bekannt)

- **Kein Identity-Node**: `ihk_pepper_identity` ist ein fertiges,
  getestetes Backend OHNE ROS2-Node, der es tatsächlich instanziiert
  und `PersonIdentityArray` veröffentlicht. Ohne diesen Node bleibt
  JEDE rollenbasierte Autorisierung strukturell auf "keine Identität
  bekannt" (→ STUDENT-Rolle) begrenzt, egal wie gut Backend/Liveness/
  Matching selbst getestet sind.
- **Kein echter ReSpeaker/kein echtes Nav2** (unverändert seit
  AP6/AP6.1/AP2): jede Aussage zu Codewort-Erkennung, Gruppen-
  Sprecherwechsel, FollowPerson- und ReturnToOrigin-Fahrten bleibt bis
  zur ersten echten Hardwaretestphase bei "gegen Mocks getestet,
  nicht hardware-verifiziert" stehen.
- **Biometrischer Speicherpfad** (`/var/lib/ihk-pepper/identity/`)
  wurde in dieser Session nie tatsächlich angelegt/beschrieben --
  Berechtigungen/Verschlüsselung nur an einer temporären Testdatei
  nachgewiesen.

**Fazit**: `enable_follow_person`/eine echte Identitäts-Anbindung
bleiben bis auf Weiteres nur für Dry-Run-Tests (`follow_person_dry_run`
u.ä.) vorgesehen. Vor jeder Freigabe an echter Hardware müssen
mindestens die Punkte 3, 5, 6, 8-14 oben durch echte Tests (nicht nur
Quellcode-Review oder Prozessstart ohne Daten) bestätigt werden.
