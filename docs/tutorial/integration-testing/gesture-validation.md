# Gestenvalidierung

{{ offlinetested }}

## Was diese Seite ist

Wie sich der gesamte Gestenkatalog vollständig ohne Pepper-Hardware
prüfen lässt — Laden, Validieren, Kinematik-Kompilieren, Dry-Run.

## Tatsächlich für dieses Tutorial ausgeführt

```bash
source /opt/ros/jazzy/setup.bash
cd ros2/autonomy_ws
source install/setup.bash
ros2 run ihk_pepper_bridge gesturectl list
```

**Ergebnis**: alle 22 Katalogeinträge korrekt gelistet (20 aus
vorherigen Sessions + `point_to_self`/`small_bow`, neu für dieses
Tutorial) — siehe [Gestenkatalog](../gestures-kinematics/gesture-catalog.md)
für die vollständige Tabelle.

```bash
ros2 run ihk_pepper_bridge gesturectl validate point_to_self
ros2 run ihk_pepper_bridge gesturectl validate small_bow
```

**Tatsächliches Ergebnis**:

```text
'point_to_self': Katalog-Validierung OK (schema_version 2, tested_status=draft).
  Kinematik-Compiler OK: 5 Gelenke, Endzeit 2.60s.
'small_bow': Katalog-Validierung OK (schema_version 2, tested_status=draft).
  Kinematik-Compiler OK: 2 Gelenke, Endzeit 3.50s.
```

```bash
ros2 run ihk_pepper_bridge gesturectl dry-run point_to_self
ros2 run ihk_pepper_bridge gesturectl dry-run small_bow
```

**Tatsächliches Ergebnis** (Auszug):

```text
[dry-run] Geste 'point_to_self': 5 Gelenke, Endzeit 2.60s -- {'HeadPitch': [-0.05, -0.05], 'LElbowRoll': [-0.02, -0.7], 'LElbowYaw': [0.0, -0.3], 'LShoulderPitch': [0.0, 0.6], 'LShoulderRoll': [0.15, 0.2]}
[dry-run] 'point_to_self' waere jetzt gesendet worden (keine Hardwareaktion).
[dry-run] Wiederherstellung waere jetzt gesendet worden (keine Hardwareaktion).
Status: done
```

Beide Läufe rühren garantiert nie eine Hardware-Methode an --
`DryRunMotionTransport` (siehe
[Gestenformat](../gestures-kinematics/gesture-format.md)) protokolliert
nur.

## Vollständiger Katalog-Selbsttest

```bash
python3 -m pytest src/ihk_pepper_tests/test/test_gesture_catalog.py -v \
  -k "test_every_v2_gesture_compiles_without_error"
```

Dieser einzelne parametrisierte Test kompiliert **jede** v2-Geste im
Katalog einzeln über den `KinematicCompiler` — inklusive der beiden
neuen. Tatsächlich ausgeführt für dieses Tutorial:
**386/386 der Gesamtsuite grün** (siehe
[Erste Schritte](../getting-started/repository-and-environment.md)).

## `preview`: die RViz-Vorschau als Sicherheitsschritt

`gesturectl preview <name>` spielt eine Geste über das bestehende
`pepper_description`-URDF/RViz-System ab -- **kein neues
Simulationssystem**. Für v1-Gesten repräsentativ, für v2-Gesten nur eine
**sequenzielle Annäherung** (nicht das echte synchrone Timing) --
explizit nur zur visuellen Winkelkontrolle gedacht, nicht als
Zeitverhalten-Nachweis. Genau dieser Schritt ist für `small_bow`
(ungeprüfte `HipPitch`-Vorzeichenrichtung) besonders wichtig — siehe
{ref}`Sichere Gestenentwicklung <beispiel-2-small_bow>`.

**Für dieses Tutorial nicht ausgeführt** (bräuchte einen separat
laufenden `display_scripted.launch.py`-Prozess mit RViz-Fenster) --
offen als nächster, empfohlener Schritt dokumentiert, nicht als erledigt
behauptet.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Katalog-Laden, Validierung, Kinematik-Kompilierung
und Dry-Run sind für dieses Tutorial tatsächlich neu ausgeführt worden,
nicht nur aus einem Bericht übernommen. {{ hwverificationrequired }}
für jede tatsächliche Bewegung.

## Nächster Schritt

[Deployment](../deployment/index.md).
