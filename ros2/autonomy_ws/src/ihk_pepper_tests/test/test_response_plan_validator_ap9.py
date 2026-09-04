from ihk_pepper_llm_contracts.response_plan import (
    PlanContext,
    ResponsePlan,
    ResponsePlanValidator,
    ResponseSegment,
)


def _context(**overrides):
    defaults = dict(
        allowed_gesture_names=["open_arms", "wave_right"],
        current_interaction_state="CONVERSATION_READY",
        allowed_interaction_states_for_gestures={},
        safety_ok=True,
        known_source_ids=["faq:42"],
    )
    defaults.update(overrides)
    return PlanContext(**defaults)


def test_missing_segment_id_rejected():
    plan = ResponsePlan(segments=[ResponseSegment(text="Hallo.")])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("segment_id fehlt" in e for e in result.errors)


def test_duplicate_segment_ids_rejected():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Erstens."),
        ResponseSegment(segment_id="a", text="Zweitens."),
    ])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("nicht eindeutig" in e for e in result.errors)


def test_unique_segment_ids_pass():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Erstens."),
        ResponseSegment(segment_id="b", text="Zweitens."),
    ])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is True


def test_total_duration_exceeding_limit_rejected():
    long_text = "x" * 2000  # bei 15 Zeichen/s deutlich ueber 90s
    plan = ResponsePlan(segments=[ResponseSegment(segment_id="a", text=long_text)])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("Gesamtdauer" in e for e in result.errors)


def test_tts_unavailable_rejects_whole_plan():
    plan = ResponsePlan(segments=[ResponseSegment(segment_id="a", text="Hallo.")])
    result = ResponsePlanValidator().validate(plan, _context(tts_available=False))
    assert result.valid is False
    assert any("TTS nicht verfuegbar" in e for e in result.errors)


def test_nav2_moving_blocks_gesture_segment_but_plan_structure_still_checked():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Hallo.", gesture_name="open_arms",
                         gesture_relation="with_segment_start"),
    ])
    result = ResponsePlanValidator().validate(plan, _context(nav2_moving=True))
    assert result.valid is False
    assert any("Nav2-Bewegung gesperrt" in e for e in result.errors)


def test_nav2_moving_does_not_block_speech_only_segment():
    plan = ResponsePlan(segments=[ResponseSegment(segment_id="a", text="Nur Sprache.")])
    result = ResponsePlanValidator().validate(plan, _context(nav2_moving=True))
    assert result.valid is True  # Fallback-Prinzip: Sprache laeuft trotz Nav2-Bewegung weiter


def test_mapping_active_blocks_only_head_gestures():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Hallo.", gesture_name="open_arms",
                         gesture_relation="with_segment_start"),
    ])
    result = ResponsePlanValidator().validate(
        plan, _context(mapping_active=True, head_gesture_names=["nod_once"]))
    assert result.valid is True  # open_arms bewegt keinen Kopf


def test_mapping_active_blocks_configured_head_gesture():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Hallo.", gesture_name="open_arms",
                         gesture_relation="with_segment_start"),
    ])
    result = ResponsePlanValidator().validate(
        plan, _context(mapping_active=True, head_gesture_names=["open_arms"]))
    assert result.valid is False
    assert any("Kopfgeste waehrend Mapping gesperrt" in e for e in result.errors)


def test_gesture_in_progress_blocks_new_gesture_no_double_start():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Hallo.", gesture_name="open_arms",
                         gesture_relation="with_segment_start"),
    ])
    result = ResponsePlanValidator().validate(plan, _context(gesture_in_progress=True))
    assert result.valid is False
    assert any("Doppelstart" in e for e in result.errors)


def test_pepper_unreachable_blocks_gesture_segment():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="a", text="Hallo.", gesture_name="open_arms",
                         gesture_relation="with_segment_start"),
    ])
    result = ResponsePlanValidator().validate(plan, _context(pepper_reachable=False))
    assert result.valid is False
    assert any("nicht erreichbar" in e for e in result.errors)


def test_estimated_duration_helper_on_segment():
    segment = ResponseSegment(segment_id="a", text="x" * 15)
    assert segment.estimated_duration_s() == 1.0
