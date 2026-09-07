(kontaktloses-prinzip)=
# Sichere Gestenentwicklung

{{ documented }}

## Was diese Seite ist

Die reale Checkliste für eine neue Geste, angewandt auf zwölf konkrete
Bewegungen — zehn davon bereits im Katalog vorhanden, zwei
(`point_to_self`, `small_bow`) eigens für dieses Tutorial neu angelegt,
nach genau diesem Verfahren.

## Die Checkliste (aus `docs/GESTURE_AUTHORING.md`)

1. YAML-Datei unter `config/gestures/<name>.yaml`, `name:` muss zum
   Dateinamen passen.
2. `schema_version: 2`, Keyframes mit streng monotonen Zeiten.
3. Winkelwerte aus **vorhandenen getesteten Posen** ableiten, wo möglich
   — keine erfundenen Werte. Wo keine Referenz existiert:
   `tested_status: draft`, kleine/konservative Auslenkung.
4. `allowed_interaction_states`, `requires_stationary`,
   `max_duration_s`, `on_cancel` setzen.
5. `colcon build --packages-select ihk_pepper_bridge` +
   `gesturectl validate`/`dry-run` — Validierung greift beim Laden.
6. Vor `tested_status: live_validated`: einzeln, langsam, unter
   direkter Aufsicht am echten Pepper testen.

## Kontaktloses Prinzip

Eine "Umarmung" darf **ausschließlich** als kontaktlose
Umarmungsandeutung umgesetzt werden. Pepper darf **keine** Person
greifen, festhalten oder unberaufsichtigt berühren — das gilt für
`self_hug_symbolic` genauso wie für jede künftige Geste in diese
Richtung.

## Die zwölf geforderten Bewegungen

Jede Übung unten nennt: beteiligte Gelenke, Zielwinkel, Geschwindigkeit,
Interpolationsdauer, Gelenkgrenzen, erwartete Selbstdistanz,
Abbruchbedingungen, Offline-Validierung, simulierte/trockene
Ausführung, beaufsichtigte Livefreigabe, Rückkehrpose.

---

### 1. Neutrales Stehen -- `neutral_stand`

- **Gelenke**: `HeadYaw`/`HeadPitch`, beide Schultern/Ellbogen, `HipRoll`/
  `HipPitch`/`KneePitch` -- alle 13 Gelenke der Referenzpose.
- **Zielwinkel**: alle nahe 0.0 (`LShoulderRoll: 0.15`,
  `RShoulderRoll: -0.15`, `LElbowRoll: -0.02`, `RElbowRoll: 0.02`, Rest
  exakt 0.0).
- **Geschwindigkeit**: `speed_scale_default: 0.5`.
- **Interpolationsdauer**: 1,5 s (ein Keyframe).
- **Gelenkgrenzen**: alle Winkel weit innerhalb der dokumentierten
  Grenzen (siehe [Gestenformat](gesture-format.md)).
- **Erwartete Selbstdistanz**: keine Selbstberührung -- Referenzpose
  selbst.
- **Abbruchbedingungen**: Standard-Motion-Guard-Bedingungen (Bumper,
  Not-Halt, `enable_live_motion=false`).
- **Offline-Validierung**: {{ offlinetested }} `gesturectl validate
  neutral_stand`.
- **Simulierte/trockene Ausführung**: {{ offlinetested }} `gesturectl
  dry-run neutral_stand`.
- **Beaufsichtigte Livefreigabe**: noch nicht durchgeführt --
  {{ hwverificationrequired }}.
- **Rückkehrpose**: ist selbst die Rückkehrpose -- `restore_after:
  false` (Sonderfall, siehe YAML-Kommentar).

---

### 2. Einhändiges Winken -- `wave_right` / `wave_left`

- **Gelenke**: `RShoulderPitch`/`RElbowRoll`/`RElbowYaw` (bzw. linke
  Entsprechung).
- **Zielwinkel**: `RShoulderPitch: -1.0`, `RElbowRoll: 0.9`, `RElbowYaw`
  oszilliert 0.6 ↔ 1.6.
- **Geschwindigkeit**: `speed_scale_default: 1.0`.
- **Interpolationsdauer**: 2,8 s über sechs Keyframes.
- **Gelenkgrenzen**: `RShoulderRoll`/`RWristYaw` sind live-geprüft;
  die genutzten Gelenke (`ShoulderPitch`/`ElbowRoll`/`ElbowYaw`) selbst
  sind **nicht** live-geprüft, aber die Winkelwerte stammen aus einer
  bereits live getesteten v1-Sequenz.
- **Erwartete Selbstdistanz**: keine Selbstberührung.
- **Abbruchbedingungen**: Standard-Motion-Guard, zusätzlich während
  Nav2-Bewegung gesperrt (`requires_stationary: true`).
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }} -- Winkelwerte
  identisch zu einer live getesteten Sequenz.
- **Beaufsichtigte Livefreigabe**: einzige echte
  Vorgänger-Bewegung (v1) war live getestet; der **neue synchrone
  v2-Transportweg selbst** ist nicht live geprüft.
- **Rückkehrpose**: `restore_after: true` -- vorherige Pose.

---

### 3. Beidhändiges Begrüßen -- `greet_open`

- **Gelenke**: `HeadPitch`, `LShoulderPitch`/`RShoulderPitch`,
  `LShoulderRoll`/`RShoulderRoll`.
- **Zielwinkel**: `ShoulderPitch: 0.1` (beide Seiten),
  `ShoulderRoll: ±0.5` -- konservativ unterhalb des bei `open_arms`
  genutzten Werts (0.9).
- **Geschwindigkeit**: `speed_scale_default: 0.7`.
- **Interpolationsdauer**: 2,5 s über zwei Keyframes.
- **Gelenkgrenzen**: `RShoulderRoll` ist live-geprüft; Werte deutlich
  innerhalb der Grenze.
- **Erwartete Selbstdistanz**: keine Selbstberührung, moderate Öffnung.
- **Abbruchbedingungen**: Standard-Motion-Guard.
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }} -- Winkel als
  konservativer Bruchteil einer bereits `dry_run_validated` Geste
  gewählt.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }}.
- **Rückkehrpose**: `restore_after: true`.

---

### 4. Beide Arme anheben -- `raise_both_arms`

- **Gelenke**: `LShoulderPitch`/`RShoulderPitch`.
- **Zielwinkel**: beide `-1.0` -- identisch zum live getesteten
  `wave_*`-Vorbereitungswinkel, symmetrisch übertragen.
- **Geschwindigkeit**: `speed_scale_default: 0.6`.
- **Interpolationsdauer**: 3,0 s (ein Keyframe).
- **Gelenkgrenzen**: Wert stammt aus einer live getesteten Sequenz für
  ein einzelnes Gelenk; die **bilaterale Gleichzeitigkeit** selbst ist
  nicht live geprüft.
- **Erwartete Selbstdistanz**: keine Selbstberührung, Arme frei
  seitlich/nach vorne.
- **Abbruchbedingungen**: Standard-Motion-Guard.
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }}.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }}.
- **Rückkehrpose**: `restore_after: true`.

---

(beispiel-1-point_to_self)=
### 5. Auf sich selbst zeigen -- `point_to_self` (neu)

**Existierte vor diesem Tutorial nicht im Katalog.** Neu angelegt nach
der Checkliste oben — ein reales Beispiel für "eine Geste ohne direkte
Live-Referenz anlegen".

- **Warum keine echte Zeige-Geste**: Peppers Hand hat nur 1 Motor
  (auf/zu) — Fingerzeigen ist strukturell unmöglich (siehe
  [Gestenformat](gesture-format.md)). Umgesetzt als Hand-zur-eigenen-
  Brust-Bewegung.
- **Gelenke**: `HeadPitch`, `LShoulderPitch`, `LShoulderRoll`,
  `LElbowRoll`, `LElbowYaw`.
- **Zielwinkel**: `LShoulderPitch: 0.6` (Arm bleibt tief, gleiche
  Vorzeichenlogik wie `thinking_symbolic`), `LShoulderRoll: 0.2`,
  `LElbowRoll: -0.7` (Ellbogen Richtung Torso, wie `self_hug_symbolic`),
  `LElbowYaw: -0.3`.
- **Geschwindigkeit**: `speed_scale_default: 0.5`.
- **Interpolationsdauer**: 2,5 s über zwei Keyframes.
- **Gelenkgrenzen**: alle Werte deutlich innerhalb der dokumentierten
  Grenzen (siehe [Gestenformat](gesture-format.md)); keines der
  genutzten Gelenke ist live-geprüft.
- **Erwartete Selbstdistanz**: Hand nähert sich der eigenen Brust,
  **berührt sie nicht** -- Ellbogenwinkel bewusst konservativ gewählt,
  um Kontakt zu vermeiden.
- **Abbruchbedingungen**: Standard-Motion-Guard, zusätzlich vor jedem
  weiteren Schritt: `gesturectl preview point_to_self` (RViz) zur
  visuellen Bestätigung, dass die Hand Richtung Brust und **nicht**
  Richtung Gesicht zeigt.
- **Offline-Validierung**: {{ offlinetested }} tatsächlich für dieses
  Tutorial ausgeführt: `gesturectl validate point_to_self` →
  `Kinematik-Compiler OK: 5 Gelenke, Endzeit 2.60s`.
- **Simulierte/trockene Ausführung**: {{ offlinetested }} tatsächlich
  ausgeführt: `gesturectl dry-run point_to_self` → vollständige
  Trajektorie geloggt, keine Hardwareaktion.
- **Beaufsichtigte Livefreigabe**: **nicht durchgeführt** --
  {{ hwverificationrequired }}, `tested_status: draft` bleibt bestehen,
  bis ein Mensch sie unter Aufsicht geprüft und manuell hochgestuft hat.
- **Rückkehrpose**: `restore_after: true`.

---

### 6. Nach links zeigen -- `explain_left`

- **Gelenke**: `LShoulderPitch`, `LShoulderRoll`, `LElbowRoll`.
- **Zielwinkel**: `LShoulderRoll: 0.6` (zwischen `greet_open`s 0.5 und
  `open_arms`s 0.9 interpoliert), `LElbowRoll` nahe Neutralstellung.
- **Geschwindigkeit**: `speed_scale_default: 0.7`.
- **Interpolationsdauer**: 2,0 s über zwei Keyframes.
- **Gelenkgrenzen**: innerhalb der dokumentierten Grenzen, nicht
  live-geprüft.
- **Erwartete Selbstdistanz**: Arm öffnet sich seitlich, keine
  Selbstberührung.
- **Abbruchbedingungen**: Standard-Motion-Guard.
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }}.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }}.
- **Rückkehrpose**: `restore_after: true`.

### 6b. Nach rechts zeigen -- `explain_right`

Spiegelbild von `explain_left` (rechter statt linker Arm, gespiegelte
Vorzeichen) — gleiche Herleitung/Begründung, gleicher
Verifikationsstand.

---

### 7. Erklärende offene Handbewegung -- `explain_small`

- **Gelenke**: `RShoulderPitch`, `RShoulderRoll`, `RElbowRoll`.
- **Zielwinkel**: konservativer als `open_arms`, kleine, einseitige
  Öffnung.
- **Geschwindigkeit**: `speed_scale_default: 0.7`.
- **Interpolationsdauer**: 1,2 s.
- **Gelenkgrenzen**: innerhalb der Grenzen, nicht live-geprüft.
- **Erwartete Selbstdistanz**: keine Selbstberührung.
- **Abbruchbedingungen**: Standard-Motion-Guard.
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }}.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }}.
- **Rückkehrpose**: `restore_after: true`.

---

### 8. Zustimmung -- `agree_nod`

- **Gelenke**: `HeadPitch`.
- **Zielwinkel**: oszilliert 0.25 ↔ 0.0 (Doppel-Nicken, knapp unter der
  in `nod_once` genutzten Amplitude von 0.3).
- **Geschwindigkeit**: `speed_scale_default: 0.8`.
- **Interpolationsdauer**: 2,0 s über vier Keyframes.
- **Gelenkgrenzen**: `HeadPitch` konservativ innerhalb `[-0.7068,
  0.4451]`, nicht live-geprüft (keine Live-Referenz für Kopfgesten
  überhaupt im Projekt vorhanden).
- **Erwartete Selbstdistanz**: keine -- reine Kopfbewegung.
- **Abbruchbedingungen**: Standard-Motion-Guard, zusätzlich während
  `mapping_active` gesperrt (bewegt `HeadPitch`).
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }}.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }}.
- **Rückkehrpose**: `restore_after: true`.

---

### 9. Ablehnung -- `disagree_head`

- **Gelenke**: `HeadYaw`.
- **Zielwinkel**: oszilliert −0.3 ↔ 0.3 rad -- deutlich konservativer
  als die dokumentierte Grenze (±2.0857).
- **Geschwindigkeit**: `speed_scale_default: 0.8` (Spitzenwert 1,5
  rad/s, unter der `wave_right`-Referenz von 2,5 rad/s).
- **Interpolationsdauer**: 2,0 s über vier Keyframes.
- **Gelenkgrenzen**: `HeadYaw` nicht live-geprüft.
- **Erwartete Selbstdistanz**: keine -- reine Kopfbewegung.
- **Abbruchbedingungen**: Standard-Motion-Guard, während
  `mapping_active` gesperrt.
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }}.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }}.
- **Rückkehrpose**: `restore_after: true`.

---

(beispiel-2-small_bow)=
### 10. Kleine Verbeugung -- `small_bow` (neu)

**Existierte vor diesem Tutorial nicht im Katalog.** Das schwierigere
der beiden neuen Beispiele: **kein** bisheriger Katalogeintrag nutzt
`HipPitch` aktiv.

- **Gelenke**: `HipPitch`, `HeadPitch`.
- **Zielwinkel**: `HipPitch: 0.15` (bewusst sehr klein -- unter 15% des
  dokumentierten Bereichs `±1.0385`), `HeadPitch: 0.2` (von `nod_once`
  übernommen).
- **Geschwindigkeit**: `speed_scale_default: 0.4` (langsamste Geste im
  ganzen Katalog).
- **Interpolationsdauer**: 2,0 s über zwei Keyframes.
- **Gelenkgrenzen**: `HipPitch` ist **nicht** live-geprüft, und --
  wichtiger -- **keine** frühere Katalog-Geste liefert eine
  Referenz für die Vorzeichenrichtung. Der gewählte Wert könnte in die
  falsche Richtung neigen.
- **Erwartete Selbstdistanz**: keine Selbstberührung, sehr kleine
  Neigung.
- **Abbruchbedingungen**: Standard-Motion-Guard, zusätzlich zwingend
  **vor jedem weiteren Schritt**: `gesturectl preview small_bow` (RViz)
  zur visuellen Bestätigung der tatsächlichen Neigungsrichtung. Zeigt
  die Vorschau eine Rückwärtsneigung statt einer Verbeugung nach vorn,
  ist das Vorzeichen zu invertieren, **bevor** irgendein weiterer
  Schritt (auch nur `dry-run`) unternommen wird.
- **Offline-Validierung**: {{ offlinetested }} tatsächlich ausgeführt:
  `gesturectl validate small_bow` →
  `Kinematik-Compiler OK: 2 Gelenke, Endzeit 3.50s`.
- **Simulierte/trockene Ausführung**: {{ offlinetested }} tatsächlich
  ausgeführt: `gesturectl dry-run small_bow` → Trajektorie geloggt,
  keine Hardwareaktion. **Die RViz-`preview`-Vorschau selbst wurde für
  dieses Tutorial nicht ausgeführt** — `display_scripted.launch.py`
  müsste dafür separat laufen; das bleibt als offener nächster Schritt
  dokumentiert, nicht als erledigt behauptet.
- **Beaufsichtigte Livefreigabe**: **nicht durchgeführt** --
  {{ hwverificationrequired }}, und zwar mit höherer Priorität als bei
  den übrigen Gesten, da die Bewegungsrichtung selbst ungeprüft ist.
- **Rückkehrpose**: `restore_after: true`.

---

### 11. Vorsichtige Umarmungsandeutung -- `self_hug_symbolic`

- **Gelenke**: `LShoulderPitch`/`RShoulderPitch`,
  `LElbowRoll`/`RElbowRoll`.
- **Zielwinkel**: `ShoulderPitch: 0.5` (beide Seiten), `ElbowRoll: ∓0.6`
  -- Arme leicht Richtung eigenen Oberkörper, **keine** vergleichbare
  bisher getestete Geste als Referenz, deshalb bewusst kleine Winkel.
- **Geschwindigkeit**: `speed_scale_default: 0.5`.
- **Interpolationsdauer**: 3,0 s (ein Keyframe, langsamste Zielzeit im
  Katalog neben `small_bow`).
- **Gelenkgrenzen**: innerhalb der Grenzen, nicht live-geprüft, **noch
  nicht einmal per `dry-run` visuell an einem echten Pepper geprüft**
  (Projektstand, nicht neu für dieses Tutorial).
- **Erwartete Selbstdistanz**: **muss** kontaktlos bleiben -- siehe
  [Kontaktloses Prinzip](#kontaktloses-prinzip). Pepper darf sich
  selbst NICHT berühren und erst recht keine andere Person.
- **Abbruchbedingungen**: Standard-Motion-Guard; wegen fehlender
  Referenz besonders vorsichtig einzeln zu prüfen.
- **Offline-Validierung**: {{ offlinetested }}.
- **Simulierte/trockene Ausführung**: {{ offlinetested }} (Trajektorie),
  aber ausdrücklich noch nicht per RViz visuell kontrolliert.
- **Beaufsichtigte Livefreigabe**: {{ hwverificationrequired }} --
  "vor jeder Live-Nutzung besonders sorgfältig einzeln, langsam und
  unter direkter Aufsicht prüfen" (Originalkommentar der YAML-Datei).
- **Rückkehrpose**: `restore_after: true`.

---

### 12. Rückkehr in die sichere Neutralpose -- `neutral_stand`

Identisch zu Übung 1 — jede Geste mit `restore_after: true` kehrt
ohnehin automatisch zur vorherigen Pose zurück; `neutral_stand` ist die
Geste, die man **explizit** als Abschluss abspielt (z.B. nach einer
Präsentation oder einem Gespräch, bevor Pepper in einen anderen Modus
wechselt).

## Beaufsichtigtes Live-Testen (`gesturectl live-test`)

Das Sicherheits-Gate ist **Code, nicht nur Dokumentation** (siehe
`docs/GESTURE_LIVE_TEST_CHECKLIST.md`):

1. Bricht sofort ab, wenn `pepper_client.is_reachable()` `False` ist
   oder die Geste `schema_version 1` ist.
2. Fragt **vier** Checklistenpunkte einzeln ab: Armraum frei, Bediener
   am Not-Stopp, sichere Aufstellung, vorheriger erfolgreicher
   `dry-run`. **Jede** Antwort ungleich exakt `ja` bricht sofort ab,
   ohne jede Bewegung.
3. Erster Durchgang erzwungen `speed_scale <= 0.4` (nur über
   `--full-speed` umgehbar).
4. Nutzt denselben `QicliTrajectoryTransport` wie der Produktivbetrieb
   -- kein separater "Testmodus"-Codepfad.
5. **Schreibt niemals selbst** `tested_status: live_validated` in eine
   YAML -- druckt stattdessen eine Anleitung für den manuellen Eintrag.
   Kein Tool in diesem Projekt darf eine Geste sich selbst als
   hardwareverifiziert markieren.

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Alle zwölf Übungen sind über echte
`gesturectl validate`/`dry-run`-Aufrufe (für die zehn bestehenden
Katalogeinträge in früheren Sessions, für die zwei neuen in dieser
Tutorial-Session) geprüft. {{ hwverificationrequired }} für jede
einzelne — **keine** von ihnen ist `live_validated`.
{{ supervisedmotion }} gilt für jeden zukünftigen tatsächlichen
Live-Test.

## Nächster Schritt

[Integration und Tests](../integration-testing/index.md).
