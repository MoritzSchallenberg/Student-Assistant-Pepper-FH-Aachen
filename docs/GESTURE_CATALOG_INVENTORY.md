# Gesten-Katalog-Inventar

**Automatisch erzeugt -- NICHT manuell bearbeiten.** Erzeugt aus dem echten YAML-Gestenkatalog ueber dieselbe validierte `GestureCatalog`/`Gesture`-Klasse und denselben Renderer wie `gesturectl audit` (siehe `gesture_catalog_audit.py`).

Reproduktionsbefehl:

```bash
python3 scripts/generate_gesture_inventory.py
```

Gesamt: 24 Gesten (5 Systemgesten, 19 LLM-auswaehlbar).

## Statusverteilung

| tested_status | Anzahl |
| --- | --- |
| draft | 17 |
| dry_run_validated | 6 |
| live_validated | 1 |

**Historischer Sonderfall `t_pose`**: `tested_status: live_validated` bezieht sich NUR auf den historischen v1-Hardwaretest der Bewegung selbst -- v1 bleibt strukturell aus `production` gesperrt (siehe `gesture_execution_policy.py`), dieser Status umgeht KEINES der AP8-R1-/AP8-R2-Sicherheitsgates. `t_pose` ist zusaetzlich `system_only`.

**Platzhalter `look_at_person`**: berechnet KEINE echte Blickrichtung zu einer konkreten Person -- eine feste, sichere Neutralstellung. `system_only`, nicht LLM-auswaehlbar.

## Gesten

| Name | Schema | tested_status | system_only | selectable_by_llm | semantic_tags | max_duration_s |
| --- | --- | --- | --- | --- | --- | --- |
| acknowledge_nod_small | v2 | draft | True | False | -- | 1.2 |
| agree_nod | v2 | draft | False | True | agreement, affirmation, nodding | 2.0 |
| celebrate_small | v2 | draft | False | True | celebration, joy, excitement | 2.8 |
| disagree_head | v2 | draft | False | True | disagreement, negation, uncertainty | 2.0 |
| explain_left | v2 | draft | False | True | explanation, gesture_left, reference_pointing | 2.0 |
| explain_right | v2 | draft | False | True | explanation, gesture_right, reference_pointing | 2.0 |
| explain_small | v2 | draft | False | True | explanation, small_gesture, neutral | 2.0 |
| goodbye_wave | v2 | dry_run_validated | False | True | farewell, goodbye, waving | 2.5 |
| greet_open | v2 | draft | False | True | greeting, welcoming, open_arms | 2.5 |
| look_at_person | v2 | draft | True | False | -- | 1.5 |
| neutral_stand | v2 | dry_run_validated | True | False | -- | 3.1 |
| nod_once | v2 | draft | False | True | acknowledgment, nodding, agreement | 1.5 |
| open_arms | v2 | dry_run_validated | False | True | welcoming, open_gesture, invitation | 3.4 |
| point_to_self | v2 | draft | False | True | self_reference, symbolic_gesture | 2.7 |
| point_to_tablet | v2 | draft | False | True | tablet_reference, symbolic_gesture, presenting | 3.1 |
| present_information | v2 | draft | False | True | presentation, explanation, information | 3.7 |
| raise_both_arms | v2 | dry_run_validated | False | True | celebration, arms_raised, enthusiasm | 3.4 |
| self_hug_symbolic | v2 | draft | False | True | comfort, self_soothing, symbolic_gesture | 4.1 |
| small_bow | v2 | draft | False | True | politeness, bow, respect | 3.6 |
| t_pose | v1 | live_validated | True | False | -- | 15.0 |
| thinking_loop_subtle | v2 | draft | True | False | -- | 1.9 |
| thinking_symbolic | v2 | draft | False | True | thinking, pondering, symbolic_gesture | 2.5 |
| wave_left | v2 | dry_run_validated | False | True | greeting, waving, farewell | 3.5 |
| wave_right | v2 | dry_run_validated | False | True | greeting, waving, farewell | 3.5 |

## Audit-Hinweise

- **t_pose** [warning]: v1-Gesteneintrag (sequenzielles Format) -- bleibt strukturell aus 'production' gesperrt, siehe gesture_execution_policy.py.

