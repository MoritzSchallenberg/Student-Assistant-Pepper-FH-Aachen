"""
Tests fuer production_readiness.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 20: Produktionsfreigaben fuer die persistente Gesichtszuordnung).
"""
import hashlib

import pytest

from ihk_pepper_identity.production_readiness import check_identity_production_gates


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path, data: bytes = b"model-bytes"):
    path.write_bytes(data)
    return str(path)


def _all_valid(tmp_path):
    model_path = _write(tmp_path / "model.onnx")
    checksum = _sha256((tmp_path / "model.onnx").read_bytes())
    template_store_path = _write(tmp_path / "templates.db", b"encrypted")
    registry_db_path = _write(tmp_path / "registry.db", b"registry")
    calibration_path = _write(tmp_path / "calibration.yaml", b"calib")
    return dict(
        model_path=model_path,
        model_checksum_sha256=checksum,
        template_store_path=template_store_path,
        registry_db_path=registry_db_path,
        camera_calibration_path=calibration_path,
        minimum_liveness_valid_samples=20,
        hardware_approval_confirmed=True,
        validate_template_store_fn=lambda: True,
    )


def test_all_gates_pass_when_everything_is_valid(tmp_path):
    result = check_identity_production_gates(**_all_valid(tmp_path))
    assert result.ok is True
    assert result.reasons == []


def test_missing_model_file_fails():
    result = check_identity_production_gates(
        model_path="", model_checksum_sha256="", template_store_path="",
        registry_db_path="", camera_calibration_path="",
        minimum_liveness_valid_samples=20, hardware_approval_confirmed=True,
    )
    assert result.ok is False
    assert "lokales_modell_fehlt" in result.reasons


def test_missing_checksum_fails_even_with_a_real_model_file(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["model_checksum_sha256"] = ""
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "keine_pruefsumme_hinterlegt" in result.reasons


def test_wrong_checksum_fails(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["model_checksum_sha256"] = "0" * 64
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "pruefsumme_ungueltig" in result.reasons


def test_missing_template_store_fails(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["template_store_path"] = ""
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "vorlagenspeicher_fehlt" in result.reasons


def test_template_store_without_a_validation_function_fails_closed(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["validate_template_store_fn"] = None
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "vorlagenspeicher_nicht_geprueft" in result.reasons


def test_undecryptable_template_store_fails(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["validate_template_store_fn"] = lambda: False
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "vorlagenspeicher_nicht_entschluesselbar" in result.reasons


def test_missing_registry_db_fails(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["registry_db_path"] = ""
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "registry_nicht_erreichbar" in result.reasons


def test_missing_camera_calibration_fails(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["camera_calibration_path"] = ""
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "kamerakalibrierung_fehlt" in result.reasons


@pytest.mark.parametrize("samples", [0, -1])
def test_non_positive_liveness_samples_fails(tmp_path, samples):
    kwargs = _all_valid(tmp_path)
    kwargs["minimum_liveness_valid_samples"] = samples
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "liveness_nicht_konfiguriert" in result.reasons


def test_missing_hardware_approval_fails(tmp_path):
    kwargs = _all_valid(tmp_path)
    kwargs["hardware_approval_confirmed"] = False
    result = check_identity_production_gates(**kwargs)
    assert result.ok is False
    assert "hardwarefreigabe_fehlt" in result.reasons


def test_multiple_failures_are_all_reported(tmp_path):
    result = check_identity_production_gates(
        model_path="", model_checksum_sha256="", template_store_path="",
        registry_db_path="", camera_calibration_path="",
        minimum_liveness_valid_samples=0, hardware_approval_confirmed=False,
    )
    assert result.ok is False
    assert len(result.reasons) == 6  # eine Ursache je gescheitertem Bereich (Modell+Pruefsumme zaehlt als 1)
