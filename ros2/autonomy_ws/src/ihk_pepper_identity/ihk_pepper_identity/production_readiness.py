"""
Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20 (Launch-Modi):
Produktionsfreigabe fuer die PERSISTENTE Gesichtszuordnung
(face_identity_node.py). Reine Logik, KEIN ROS -- vom Launch-File
(interaction_full_safe.launch.py) aufrufbar/testbar, ohne dass dafuer
ein Node gestartet werden muss.

Auftrag (Abschnitt 20): "Freigaben fuer die persistente Zuordnung des
Identitaets-Knotens explizit auflisten: lokales Modell vorhanden,
Pruefsumme gueltig, Vorlagenspeicher entschluesselbar, Registry
erreichbar, Einwilligungsinformationen gueltig, Kamerakalibrierung
geladen, Liveness konfiguriert, Hardwarefreigabe gesetzt -- sonst
identity=UNKNOWN, role=STUDENT, persistent_matching=false."

Bewusste, ehrliche Einschraenkungen dieser Umsetzung:
- "Registry erreichbar" wird HIER nur als Datei-Existenzpruefung
  umgesetzt (kein echter Service-Roundtrip innerhalb des Launch-
  Prozesses moeglich -- der ROS-Graph steht zum Zeitpunkt der
  Launch-Beschreibungserzeugung noch nicht). Ein echter
  Erreichbarkeits-Check muesste zur Laufzeit im Node selbst erfolgen
  (siehe face_identity_node.py: baut IdentityRegistryStore bereits
  defensiv mit try/except auf und faellt bei Fehler auf None zurueck).
- "Einwilligungsinformationen gueltig" ist KEIN globales Flag (Consent
  ist immer personenbezogen) -- wird bereits zur Laufzeit PRO PERSON
  durchgesetzt (identity_frame_processor.py::process_frame() prueft
  consent_lookup_fn() unmittelbar vor jeder Verwendung, role_resolution.py
  verlangt consent_granted fuer jede Rollenaufloesung). Dieser Launch-
  Gate deckt daher NUR die sechs statisch pruefbaren Voraussetzungen ab,
  nicht die dynamische Einwilligungspruefung.
- "Liveness konfiguriert" wird als "minimum_liveness_valid_samples > 0"
  geprueft -- 0 wuerde Liveness effektiv abschalten.

Ein NICHT bestandenes Gate blockiert NICHT den gesamten Systemstart --
es zwingt lediglich face_detector_kind/identity_backend_kind auf
"disabled" (identity bleibt UNKNOWN, role bleibt STUDENT, siehe
role_resolution.py), ein normales Gespraech bleibt weiterhin moeglich.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass(frozen=True)
class IdentityProductionGateResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)


def _sha256_of_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def check_identity_production_gates(
    model_path: str,
    model_checksum_sha256: str,
    template_store_path: str,
    registry_db_path: str,
    camera_calibration_path: str,
    minimum_liveness_valid_samples: int,
    hardware_approval_confirmed: bool,
    validate_template_store_fn: Optional[Callable[[], bool]] = None,
) -> IdentityProductionGateResult:
    """validate_template_store_fn: optional, () -> bool (True = ALLE
    Vorlagen entschluesselbar/gueltig, siehe
    identityctl.py::cmd_validate_store fuer dieselbe Pruefung).
    None bedeutet "nicht geprueft" -- zaehlt als NICHT bestanden
    (fail-closed), damit ein Aufrufer diese Pruefung nicht versehentlich
    einfach weglassen kann, ohne dass es auffaellt."""
    reasons: List[str] = []

    if not model_path or not os.path.isfile(model_path):
        reasons.append("lokales_modell_fehlt")
    elif not model_checksum_sha256:
        reasons.append("keine_pruefsumme_hinterlegt")
    else:
        actual = _sha256_of_file(model_path)
        if actual is None:
            reasons.append("modell_nicht_lesbar")
        elif actual.lower() != model_checksum_sha256.lower():
            reasons.append("pruefsumme_ungueltig")

    if not template_store_path or not os.path.isfile(template_store_path):
        reasons.append("vorlagenspeicher_fehlt")
    elif validate_template_store_fn is None:
        reasons.append("vorlagenspeicher_nicht_geprueft")
    elif not validate_template_store_fn():
        reasons.append("vorlagenspeicher_nicht_entschluesselbar")

    if not registry_db_path or not os.path.isfile(registry_db_path):
        reasons.append("registry_nicht_erreichbar")

    if not camera_calibration_path or not os.path.isfile(camera_calibration_path):
        reasons.append("kamerakalibrierung_fehlt")

    if minimum_liveness_valid_samples <= 0:
        reasons.append("liveness_nicht_konfiguriert")

    if not hardware_approval_confirmed:
        reasons.append("hardwarefreigabe_fehlt")

    return IdentityProductionGateResult(ok=(len(reasons) == 0), reasons=reasons)
