from ihk_pepper_interaction.safety_gate import SafetyGate, SafetyInputs


def test_motion_capable_false_blocks_everything():
    gate = SafetyGate(motion_capable=False)
    gate.request_motion_permission(True, True)
    result = gate.evaluate(SafetyInputs(
        localization_valid=True, obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, data_age_s=0.0,
    ))
    assert result["allow_motion"] is False
    assert "motion_capable_flag_not_set" in result["reason"]


def test_motion_capable_true_and_all_clear_allows_motion():
    gate = SafetyGate(motion_capable=True)
    gate.request_motion_permission(True, True)
    result = gate.evaluate(SafetyInputs(
        localization_valid=True, obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, data_age_s=0.0,
    ))
    assert result["allow_motion"] is True
    assert result["allow_person_approach"] is True
    assert result["reason"] == "ok"


def test_bumper_blocks_even_when_motion_capable():
    gate = SafetyGate(motion_capable=True)
    gate.request_motion_permission(True, True)
    result = gate.evaluate(SafetyInputs(
        bumper_active=True, localization_valid=True, obstacle_data_valid=True,
        person_depth_valid=True, charging_cable_connected=False, data_age_s=0.0,
    ))
    assert result["allow_motion"] is False
    assert result["emergency_stop"] is True
    assert "bumper_active" in result["reason"]


def test_person_approach_requires_motion_and_own_request():
    gate = SafetyGate(motion_capable=True)
    gate.request_motion_permission(True, False)  # Bewegung ja, Personenannaeherung nein
    result = gate.evaluate(SafetyInputs(
        localization_valid=True, obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, data_age_s=0.0,
    ))
    assert result["allow_motion"] is True
    assert result["allow_person_approach"] is False


def test_compute_power_invalid_blocks_motion():
    gate = SafetyGate(motion_capable=True)
    gate.request_motion_permission(True, True)
    result = gate.evaluate(SafetyInputs(
        localization_valid=True, obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, data_age_s=0.0, compute_power_valid=False,
    ))
    assert result["allow_motion"] is False
    assert "compute_power_invalid" in result["reason"]


def test_stale_data_blocks_motion():
    gate = SafetyGate(motion_capable=True)
    gate.request_motion_permission(True, True)
    result = gate.evaluate(SafetyInputs(
        localization_valid=True, obstacle_data_valid=True, person_depth_valid=True,
        charging_cable_connected=False, data_age_s=10.0, max_data_age_s=2.0,
    ))
    assert result["allow_motion"] is False
    assert "stale_sensor_data" in result["reason"]
