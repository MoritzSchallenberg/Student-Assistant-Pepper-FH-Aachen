# ResponsePlanExecutor

Stand: 2026-09-04. Entwicklungsauftrag 3, AP10.
Implementierung: `ihk_pepper_dialog/response_plan_executor.py`.
Siehe auch `docs/LLM_RUNTIME_ARCHITECTURE.md` (Aufrufer),
`docs/LLM_PIPELINE_DESIGN.md` (Vertrag `ResponsePlan`).

## Zweck: der behobene Async-Race-Bug

`dialog_manager_node.py::_on_transcript()` ruft `self._speak(answer)`
auf (nutzt `send_goal_async` + Callback, blockiert nie) und setzt in der
NÄCHSTEN Zeile sofort `WAITING_FOR_FOLLOWUP` -- bevor die Sprachausgabe
tatsächlich fertig ist. `ResponsePlanExecutor` behebt das strukturell:
`execute()` kehrt garantiert **erst zurück, wenn Sprache UND Geste jedes
Segments tatsächlich fertig sind**, nicht nur gestartet. Der Aufrufer
(`run_dialogue_action_server.py`) wechselt den Zustand daher erst NACH
`execute()`s Rückkehr.

## Design: ROS-frei, injizierte Callables

```python
ResponsePlanExecutor(
    say_fn,               # (text: str) -> bool, blockierend
    gesture_fn,           # (name: str, speed: float) -> bool, blockierend
    set_speaking_fn=None, # (bool) -> None, Halbduplex-Sperre
    segment_status_cb=None,   # (segment_id, "done"|"failed") -> None
    post_speech_pause_s=0.3,
    cancel_active_fn=None,    # () -> None, siehe "Cancel-Weiterleitung" (AP5B)
)
```

Kein rclpy-Import, keine ROS2-Action-Clients direkt -- der reale
ROS-Wrapper (`run_dialogue_action_server.py`) liefert `say_fn`/
`gesture_fn` über das bestehende blockierende
`presentation_manager_node.py::_say_and_wait()`-Muster (lokal
reimplementiert, kein Cross-Package-Import). Macht die komplette
Executor-Logik ohne echten ROS2-Node testbar (12 Unit-Tests, siehe
`test_response_plan_executor.py`).

## Ablauf je Segment (`gesture_relation`)

| `gesture_relation` | Ablauf |
|---|---|
| kein `gesture_name` | nur sprechen |
| `before_segment` | Geste vollständig, DANACH sprechen |
| `after_segment` | sprechen, DANACH Geste |
| `with_segment_start` | Geste in eigenem Thread + Sprache im Hauptthread, dann auf BEIDE warten ("nahezu gleichzeitig", explizit KEINE exakte Wort-Synchronisation) |

## Fehlerverhalten (Auftrag-Fallback-Prinzip)

- **Sprachfehler bricht den GESAMTEN Plan ab** (kein "einfach
  weitermachen").
- **Gestenfehler markiert nur dieses Segment als `failed`** -- die
  Sprache läuft weiter ("Fehler im Gestenplayer: Sprache fortsetzen,
  wenn sicher").
- **Doppelstart verhindert**: ein zweiter `execute()`-Aufruf während
  eines laufenden wird sofort mit
  `rejected_reason="bereits_eine_ausfuehrung_aktiv"` abgelehnt, startet
  nichts.
- **`cancel()`** setzt das bestehende Flag (zwischen Segmenten geprüft,
  bricht den restlichen Plan ab) UND ruft seit AP5B sofort zusätzlich
  `cancel_active_fn()` auf -- siehe "Cancel-Weiterleitung" unten.
- **Halbduplex-Sperre** (`set_speaking_fn`) bleibt bis zum
  TATSÄCHLICHEN Ende aktiv -- inklusive der konfigurierbaren
  Nachlaufzeit (`post_speech_pause_s`), erst danach freigegeben
  (`[True, False]`-Reihenfolge testverifiziert).
- Jeder Segmentstatus wird veröffentlicht (`segment_status_cb`).

## Textsanitisierung

`tts_sanitizer.py::prepare_for_speech` wird bewusst NICHT im Executor,
sondern in der realen `say_fn`-Implementierung angewendet -- unmittelbar
vor dem echten Say-Aufruf, der natürlichste Ort dafür.

## Getestet

12 Unit-Tests (`test_response_plan_executor.py`): alle vier
`gesture_relation`-Varianten, Gestenfehler bricht nur das Segment ab,
Sprachfehler bricht den ganzen Plan ab, Cancel zwischen Segmenten,
Halbduplex-Sperre exakt bis zum Ende inkl. Nachlaufzeit, kein
Doppelstart, Segmentstatus für jedes Segment veröffentlicht. Zusätzlich
live-E2E-geprüft über `run_dialogue_action_server.py` (siehe
`docs/DEVELOPMENT_ORDER_03_REPORT.md`, AP11).

## Cancel-Weiterleitung an eine GERADE LAUFENDE Action (Entwicklungsauftrag 04-B, AP5B)

Vor AP5B war `cancel()` rein passiv: es setzte nur ein Flag, das
`execute()` erst an der NÄCHSTEN Segmentgrenze prüft. Ein Cancel, das
eintraf, während `say_fn`/`gesture_fn` gerade blockierend liefen, wurde
schlicht nicht bemerkt, bis die Action von selbst fertig war.

`cancel_active_fn` (optionaler Konstruktorparameter, Standard ein No-Op
-- rückwärtskompatibel) wird von `cancel()` SOFORT zusätzlich zum Flag
aufgerufen. Der reale ROS-Wrapper bindet hier
`run_dialogue_action_server.py::_cancel_active_actions()`: bricht das
gerade aktive Say- ODER Gesture-Ziel (`self._active_say_goal_handle`/
`self._active_gesture_goal_handle`, vom jeweils letzten
`_send_goal_and_wait()`-Aufruf gesetzt) aktiv per `cancel_goal_async()`
ab, statt nur auf dessen natürliches Ende zu warten.

`_send_goal_and_wait()` selbst wurde ebenfalls verschärft: bei EIGENEM
Timeout (die Action braucht länger als der Aufrufer bereit ist zu
warten) ruft es jetzt tatsächlich `cancel_goal_async()` auf und wartet
BEGRENZT (2.0s) auf eine Bestätigung -- vorher wurde nach Ablauf des
Timeouts einfach aufgegeben, ohne die längst laufende Aktion zu stoppen.

Der `executor.execute(response_plan)`-Aufruf innerhalb von
`run_dialogue_action_server.py::_execute()` läuft seit AP5B selbst in
einem Hintergrundthread mit einer begrenzten (0.1s-Intervall)
Cancel-Poll-Schleife: ein RunDialogue-Cancel, das WÄHREND der
Plan-Ausführung eintrifft, ruft `executor.cancel()` auf und wartet bis
zu 5.0s auf eine Bestätigung, statt erst nach dem natürlichen Ende des
Executors bemerkt zu werden. Siehe `docs/ACTION_CANCELLATION.md` für die
vollständige, schichtübergreifende Abbruchkette (Transport -> Bridge ->
Dialog -> Behavior Tree -> Presentation Manager).

## Zusätzlicher Recheck vor `gesture_fn` (Entwicklungsauftrag 04-B, AP5A)

`run_dialogue_action_server.py::_gesture_and_wait()` (die konkrete
`gesture_fn`-Implementierung) ruft vor jedem tatsächlichen
`PlayGesture`-Aufruf `_recheck_before_gesture()` auf -- der Executor
selbst weiß nichts davon (bleibt unverändert ROS-frei und generisch),
die zusätzliche Sicherheitsprüfung sitzt ausschließlich in der
Callback-Implementierung. Schlägt der Recheck fehl, liefert `gesture_fn`
`False` zurück -- der Executor behandelt das identisch zu jedem anderen
Gestenfehler (Segment als `failed` markiert, Sprache läuft weiter, siehe
oben). Siehe `docs/LLM_RUNTIME_ARCHITECTURE.md` für die genauen
Prüfschritte.
