from ihk_pepper_llm_contracts.gesture_planner import (
    GesturePlanResponse,
    GestureSuggestion,
)
from ihk_pepper_llm_contracts.knowledge_planner import KnowledgePlanResponse
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


def test_valid_response_plan_passes():
    plan = ResponsePlan(
        segments=[
            ResponseSegment(
                segment_id="greeting",
                text="Guten Tag. Schoen, Sie zu sehen.",
                gesture_name="open_arms",
                gesture_relation="with_segment_start",
            )
        ],
        source_ids=[],
    )
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is True
    assert result.errors == []


def test_unknown_gesture_name_rejected():
    plan = ResponsePlan(segments=[
        ResponseSegment(text="Hallo!", gesture_name="does_not_exist", gesture_relation="after_segment"),
    ])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("nicht in der Allowlist" in e for e in result.errors)


def test_raw_ros_or_shell_instruction_in_text_rejected():
    plan = ResponsePlan(segments=[
        ResponseSegment(text="Ich fuehre jetzt ros2 topic pub /cmd_vel aus."),
    ])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("verbotene rohe Anweisung" in e for e in result.errors)


def test_joint_angle_style_output_is_not_a_valid_gesture_reference():
    # Ein LLM darf niemals Gelenkwinkel statt eines Katalog-Gestennamens
    # liefern -- so ein "Gestenname" existiert nie in der Allowlist und
    # wird deshalb ganz normal ueber den Allowlist-Check abgelehnt.
    plan = ResponsePlan(segments=[
        ResponseSegment(text="Ich winke.", gesture_name="LShoulderPitch=1.4", gesture_relation="after_segment"),
    ])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("nicht in der Allowlist" in e for e in result.errors)


def test_empty_text_rejected():
    plan = ResponsePlan(segments=[ResponseSegment(text="   ")])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("leerer Text" in e for e in result.errors)


def test_too_long_text_rejected():
    plan = ResponsePlan(segments=[ResponseSegment(text="x" * 1000)])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("zu lang" in e for e in result.errors)


def test_fact_claim_without_sources_rejected():
    plan = ResponsePlan(segments=[
        ResponseSegment(text="Unsere Ausbildung dauert drei Jahre."),
    ], source_ids=[])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("Faktenanspruch" in e for e in result.errors)


def test_fact_claim_with_known_source_passes():
    plan = ResponsePlan(segments=[
        ResponseSegment(segment_id="answer", text="Unsere Ausbildung dauert drei Jahre."),
    ], source_ids=["faq:42"])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is True


def test_unsafe_context_rejects_every_plan():
    plan = ResponsePlan(segments=[ResponseSegment(text="Hallo.")])
    result = ResponsePlanValidator().validate(plan, _context(safety_ok=False))
    assert result.valid is False
    assert any("Safety" in e for e in result.errors)


def test_source_id_not_from_retriever_rejected():
    plan = ResponsePlan(segments=[ResponseSegment(text="Hallo.")], source_ids=["erfunden:1"])
    result = ResponsePlanValidator().validate(plan, _context())
    assert result.valid is False
    assert any("erfunden" in e for e in result.errors) or any("moeglich erfunden" in e for e in result.errors)


def test_knowledge_plan_response_rejects_assumed_identity():
    resp = KnowledgePlanResponse(search_queries=["ausbildung dauer"], assumes_known_identity=True)
    errors = resp.validate()
    assert any("Personenidentitaet" in e for e in errors)


def test_knowledge_plan_response_valid():
    resp = KnowledgePlanResponse(search_queries=["ausbildung dauer"])
    assert resp.validate() == []


def test_gesture_plan_response_rejects_gesture_outside_allowlist():
    resp = GesturePlanResponse(suggestions=[GestureSuggestion(gesture_name="nod_once", relation="after_segment")])
    errors = resp.validate(allowed_gesture_names=["open_arms"])
    assert any("Allowlist" in e for e in errors)


def test_gesture_plan_response_rejects_unknown_relation():
    resp = GesturePlanResponse(suggestions=[GestureSuggestion(gesture_name="open_arms", relation="mid_speech")])
    errors = resp.validate(allowed_gesture_names=["open_arms"])
    assert any("gesture_relation" in e for e in errors)
