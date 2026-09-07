(point_to_self)=
# Gestenkatalog

{{ documented }}

## Was diese Seite ist

Alle 22 realen Katalogeinträge unter
`ros2/autonomy_ws/src/ihk_pepper_bridge/config/gestures/`, mit Status
und Herkunft der Winkelwerte. Zwei Einträge (`point_to_self`,
`small_bow`) wurden für dieses Tutorial neu angelegt, nach genau der
Checkliste aus [Sichere Gestenentwicklung](safe-gesture-development.md)
— beide über `gesturectl validate`/`dry-run` real geprüft, nicht nur
behauptet.

## Vollständige Tabelle

```{list-table}
:header-rows: 1
:widths: 22 18 60

* - Name
  - Status
  - Herkunft der Winkelwerte
* - `t_pose`
  - {{ hardwareverified }}
  - v1, aus Entwicklungsauftrag 1 live getestet -- **einzige** Geste im
    ganzen Katalog mit diesem Status.
* - `wave_right` / `wave_left`
  - {{ offlinetested }}
  - identisch zur live getesteten v1-Sequenz, nur als v2-Keyframes.
* - `raise_both_arms`
  - {{ offlinetested }}
  - `ShoulderPitch` von der live getesteten `wave_*`-Sequenz übernommen.
* - `open_arms`
  - {{ offlinetested }}
  - `ShoulderPitch` von `t_pose` übernommen, `ShoulderRoll`
    konservativer.
* - `neutral_stand`
  - {{ offlinetested }}
  - identisch zur `NEUTRAL_STAND_POSE`-Konstante im Compiler.
* - `greet_open`
  - {{ offlinetested }}
  - konservativer Bruchteil von `open_arms`.
* - `goodbye_wave`
  - {{ offlinetested }}
  - identisch zur live getesteten `wave_right`-Sequenz, nur kürzer.
* - `self_hug_symbolic`
  - {{ unverified }} (draft)
  - keine Live-Referenz, bewusst konservative Winkel. **Kontaktlos** --
    siehe [Sichere Gestenentwicklung](safe-gesture-development.md#kontaktloses-prinzip).
* - `nod_once`
  - {{ unverified }} (draft)
  - keine Live-Referenz für Kopfgesten vorhanden.
* - `look_at_person`
  - {{ unverified }} (draft)
  - reine Neutralstellung -- **Platzhalter**, berechnet noch keine echte
    Blickrichtung.
* - `explain_small` / `explain_left` / `explain_right`
  - {{ unverified }} (draft)
  - zwischen `greet_open`/`open_arms` interpoliert bzw. gespiegelt.
* - `point_to_tablet`
  - {{ unverified }} (draft)
  - Kopf+Arm-Kombination, **keine verifizierte Tablet-Ausschlusszone**
    (keine Vorwärtskinematik verfügbar) -- besonders vorsichtig gebaut.
* - `agree_nod`
  - {{ unverified }} (draft)
  - Doppel-Nicken, Amplitude von `nod_once` übernommen.
* - `disagree_head`
  - {{ unverified }} (draft)
  - `HeadYaw`-Oszillation, Geschwindigkeit unter der `wave_right`-Referenz.
* - `celebrate_small`
  - {{ unverified }} (draft)
  - neue symmetrische Bewegung, **keine** Oszillation (kein Ruck).
* - `present_information`
  - {{ unverified }} (draft)
  - von `explain_right` abgeleitet, längere Haltezeit.
* - `thinking_symbolic`
  - {{ unverified }} (draft)
  - Kopf+Arm, Hand bewusst auf Brusthöhe gehalten (nie im
    Gesichtsbereich).
* - `point_to_self` **(neu, dieses Tutorial)**
  - {{ offlinetested }} (draft, `gesturectl validate`+`dry-run` bestanden)
  - aus `thinking_symbolic`/`self_hug_symbolic` interpoliert -- siehe
    {ref}`Sichere Gestenentwicklung <beispiel-1-point_to_self>`.
* - `small_bow` **(neu, dieses Tutorial)**
  - {{ offlinetested }} (draft, `gesturectl validate`+`dry-run` bestanden)
  - **keine** Live-Referenz für `HipPitch` im ganzen Projekt --
    Vorzeichenrichtung ungeprüft, siehe
    {ref}`Sichere Gestenentwicklung <beispiel-2-small_bow>`.
```

`self_hug_symbolic` ist **kontaktlos/symbolisch** — Pepper darf keine
Person berühren, keine echte Umarmung ausführen (explizit
ausgeschlossen). `celebrate_small` ist ebenfalls bewusst **nicht** als
Umarmungs-Andeutung gebaut (Arme bleiben seitlich, nicht zueinander
geführt).

## Ein bereits behobener Bug, zur Einordnung

`look_at_person`, `nod_once`, `open_arms`, `self_hug_symbolic`
referenzierten in `allowed_interaction_states` ursprünglich den Wert
`SPEAKING` — kein gültiger `InteractionState`-Wert (existierte nur in
`DialogueState.msg`, komplett getrennt) und blockierte faktisch jede
Gestenfreigabe während eines echten Gesprächs. Entfernt — alle vier
Gesten waren bereits zusätzlich für `CONVERSATION_READY` freigegeben.

## Selbst nachvollziehen

```bash
ros2 run ihk_pepper_bridge gesturectl list
ros2 run ihk_pepper_bridge gesturectl show point_to_self
ros2 run ihk_pepper_bridge gesturectl dry-run small_bow
```

## Verifikationsstand, Sicherheit und Einschränkungen

{{ offlinetested }} Alle 22 Einträge kompilieren fehlerfrei
(`GestureCatalog.reload()`, `errors == []`). {{ hardwareverified }} gilt
**ausschließlich** für `t_pose`. Jeder andere Eintrag bleibt `draft`
oder `dry_run_validated`, bis ein Mensch ihn per beaufsichtigtem
`gesturectl live-test` geprüft und **manuell** auf `live_validated`
gehoben hat.

## Nächster Schritt

[Sichere Gestenentwicklung](safe-gesture-development.md).
