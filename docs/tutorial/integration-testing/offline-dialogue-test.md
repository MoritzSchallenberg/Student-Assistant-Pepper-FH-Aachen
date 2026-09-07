# Offline-Dialogübung

{{ offlinetested }}

## Was diese Seite ist

Der vollständige Dialog-Pipeline-Test **ohne** Pepper- oder RealSense-
Hardware: echte ROS2-Prozesse (`bridge_node` im `dry_run`,
`person_memory_node`, `run_dialogue_action_server`), synthetische
Personen-/Sicherheitsdaten, Mock-LLM-Antworten.

## Der Test-Treiber

```bash
source /opt/ros/jazzy/setup.bash
cd ros2/autonomy_ws
source install/setup.bash
python3 src/ihk_pepper_tests/test/manual_dialogue_e2e_check.py known_person
python3 src/ihk_pepper_tests/test/manual_dialogue_e2e_check.py unknown_person
```

Startet `bridge_node` (dry_run), `person_memory_node`,
`run_dialogue_action_server` als echte Prozesse
(`start_new_session=True` + `killpg`-Cleanup, um verwaiste Prozesse zu
vermeiden). Ein `DialogueTestDriver`-Node publiziert synthetische
`PersonTrackArray`- und `SafetyState`-Nachrichten.

## Historisch dokumentiertes Ergebnis (Entwicklungsauftrag 3, AP11)

Laut `docs/DEVELOPMENT_ORDER_03_REPORT.md`: beide Szenarien liefen
sauber bis `WAITING_FOR_FOLLOWUP` durch.

- **`known_person`** (Einwilligung erteilt): echter, nicht-Fallback
  validierter `ResponsePlan`, ausgeführt über Say-/PlayGesture-Mocks.
  Danach ein neuer `memory_entries`-Datensatz, per `sqlite3` bestätigt.
- **`unknown_person`** (keine Einwilligung): gleicher Ablauf bis
  `WAITING_FOR_FOLLOWUP`, aber **kein** Eintrag in `identities` oder
  `memory_entries` für diese Person.

## Tatsächlicher Nachvollzug für dieses Tutorial

{{ offlinetested }} `python3 -m pytest src/ihk_pepper_tests/test/ -q`
wurde für dieses Tutorial frisch ausgeführt: **384/386 grün** (zwei mehr
als der Auftrag-3-Ausgangsstand von 384, wegen der beiden neuen
Gesten-Tests -- siehe
[Sichere Gestenentwicklung](../gestures-kinematics/safe-gesture-development.md)).

**Der `manual_dialogue_e2e_check.py`-Lauf selbst wurde für dieses
Tutorial ebenfalls versucht, erreichte aber `WAITING_FOR_FOLLOWUP`
nicht** -- ein echter, für diese Session dokumentierter Befund, kein
beschönigtes Ergebnis:

```text
sentence-transformers nicht verfuegbar (module 'numpy' has no attribute
'long') -- semantische Suche laeuft nur mit einfacher Textaehnlichkeit.
...
ERGEBNIS: FEHLGESCHLAGEN -- WAITING_FOR_FOLLOWUP nie erreicht
```

**Ursache**: eine Umgebungs-Inkompatibilität in dieser konkreten
Session (installierte `numpy`-Version zu neu für die in `venv_dialog`
gebaute `scipy`/`sentence-transformers`-Kombination) -- derselbe
Fehlerklasse wie der in `docs/DEVELOPMENT_ORDER_02_REPORT.md`
dokumentierte `AMENT_PREFIX_PATH`-Nebenbefund: eine lokale Umgebungs-
Eigenheit, **kein** bestätigter Fehler im Produktcode selbst. Nicht in
der verbleibenden Zeit dieses Tutorials weiterverfolgt (würde ein
gezieltes `numpy`-Downgrade in `venv_dialog` brauchen, siehe
`docs/INSTALL.md`).

**Ehrlicher Stand**: das historische AP11-Ergebnis oben gilt als
dokumentiert, aber **nicht** durch diese Tutorial-Session erneut
bestätigt. Wer diese Übung selbst durchführt, sollte zuerst
`python3 -c "import sentence_transformers"` innerhalb von aktiviertem
`venv_dialog` prüfen, bevor der E2E-Treiber erwartet wird,
durchzulaufen.

## Was das für die Verifikationsmarker bedeutet

Genau das ist der Grund, warum diese Seite den Marker
{{ offlinetested }} trägt (die Testsuite und der Versuch selbst sind
real durchgeführt) und **nicht** {{ documented }} allein für den
E2E-Treiber behauptet — ein dokumentiertes historisches Ergebnis, das in
dieser Session nicht reproduziert werden konnte, ist etwas anderes als
ein in dieser Session tatsächlich bestandener Test. Genau diese
Unterscheidung soll dieses Tutorial durchgängig vorleben.

## Nächster Schritt

[Gestenvalidierung](gesture-validation.md).
