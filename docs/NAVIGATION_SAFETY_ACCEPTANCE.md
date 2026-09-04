# Sicherheits-Abnahme-Checkliste (RealSense-only Navigation)

Stand: 2026-09-04. Entwicklungsauftrag 2, Abschnitt 18. Diese Liste
entscheidet, ob `navigation_live.launch.py` jemals ausgeführt werden
darf -- **keiner** der folgenden Punkte wurde in dieser Entwicklungs-
sitzung an echter Hardware nachgewiesen. Wird laufend aktualisiert; der
finale Stand steht in `docs/DEVELOPMENT_ORDER_02_REPORT.md`.

| # | Kriterium (Auftrag Abschnitt 18) | Status |
|---|---|---|
| 1 | Entwicklungsauftrag 1 vollständig grün | ✅ erfüllt (Commit `abbaf15`) |
| 2 | Gesamter Workspace inkl. Behavior Tree baut | ✅ erfüllt (`colcon build`, 218/218 Tests) |
| 3 | RealSense-Modell und Streams automatisch erkannt | ⛔ nicht geprüft -- keine Hardware angeschlossen |
| 4 | Visual Odometry ohne Pepper-Odometrie funktioniert | ⚠️ strukturell umgesetzt + Prozess live gestartet, **nicht** mit echten RGB-D-Daten geprüft |
| 5 | Mapping/Lokalisierung getrennt startbar | ✅ strukturell + Mutex live verifiziert (kein echter Kartenlauf) |
| 6 | Nav2 nutzt ausschließlich RealSense-Daten | ✅ konfiguriert (Costmap, kein AMCL/EKF mit Pepper-Odom mehr) -- ⛔ kein Nav2-Vollstack installiert, nicht live geprüft |
| 7 | Holonome Befehlskette geprüft und begrenzt | ⚠️ per Quellcode bestätigt (`naoqi_driver2`), **nicht hardwaregetestet** |
| 8 | Annäherungszielpose hält Gesprächsabstand ein | ✅ vollständig unit-getestet (19 Tests, `approach_pose.py`) |
| 9 | Nur bestätigtes Rückwinken derselben Person löst Ablauf aus | ✅ aus Auftrag 1 übernommen, unverändert funktional |
| 10 | Sicherheits-/Datenverlust bricht ab + Nullgeschwindigkeit | ✅ Motion Guard live verifiziert (Block- und Allow-Pfad), Fahrtüberwachung live verifiziert (`manual_approach_monitor_check.py`) |
| 11 | `navigation_dry_run` läuft ohne echtes `/cmd_vel` | ⚠️ strukturell umgesetzt (Sink-Topic), **nicht live getestet** (kein Nav2-Vollstack installiert) |
| 12 | Keine unbeaufsichtigte Livebewegung durchgeführt | ✅ `navigation_live.launch.py` wurde in dieser Sitzung **niemals** ausgeführt |
| 13 | Alle automatisierbaren Tests grün | ✅ 218/218 pytest + BT.CPP `colcon test` (aus Auftrag 1 unverändert grün) |
| 14 | Ansible/rosdep stellen Zustand reproduzierbar her | siehe AP13-Abschnitt in `docs/DEVELOPMENT_ORDER_02_REPORT.md` |
| 15 | Abschlussbericht, offene Hardwaretests, nächste Schritte dokumentiert | ✅ `docs/DEVELOPMENT_ORDER_02_REPORT.md` |

## Zusätzliche, aus dieser Sitzung bekannte Blocker vor echtem Einsatz

- **RealSense-Hardware**: kein Gerät in dieser Session angeschlossen --
  Modell/Firmware/Auflösung/Bildrate nie tatsächlich erfasst (AP2).
- **Nav2-Vollstack nicht installiert** (kein sudo in dieser Session) --
  exakte Installationsbefehle siehe `docs/DEVELOPMENT_ORDER_02_REPORT.md`
  AP13.
- **Kameraextrinsik unvermessen**: `realsense_extrinsics.yaml` bleibt
  vollständig Platzhalter (`is_calibrated: false`).
- **Abdeckungslücke bestätigt, nicht behoben**: `coverage_analysis.py`
  weist nach, dass eine einzelne Kopfkamera strukturell nicht ausreicht
  (273° horizontal unabgedeckt) -- zusätzliche Absicherung (z.B. weitere
  Sensoren) ist ein offener Punkt für einen späteren Auftrag, nicht Teil
  dieses Auftrags.
- **Footprint** weiterhin auf Basis des Hersteller-Datenblatts, nicht aus
  dem URDF verifiziert (Mesh-Kollisionsgeometrie ohne Radius-Primitive).
- **Holonome Fahrfreigabe** beruht auf Quellcode-Review, nicht auf einem
  echten Testfahrt-Ergebnis.

**Fazit**: `navigation_live.launch.py` bleibt bis auf Weiteres gesperrt.
Vor der ersten tatsächlichen Freigabe müssen mindestens die Punkte 3, 4,
6, 7, 11 oben durch echte Hardwaretests (nicht nur Quellcode-Review oder
Prozessstart ohne Daten) bestätigt werden -- siehe Empfehlung für
Entwicklungsauftrag 3 in `docs/DEVELOPMENT_ORDER_02_REPORT.md`.
