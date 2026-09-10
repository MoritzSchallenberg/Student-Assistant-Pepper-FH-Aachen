"""
Tests fuer role_resolution.py (Entwicklungsauftrag 04-B, AP7.1,
Abschnitt 8).
"""
from ihk_pepper_interaction.role_resolution import resolve_role
from ihk_pepper_interaction.roles import ROLE_ADMIN, ROLE_STUDENT


def _registry_fn(role="employee"):
    def fn(person_id, now):
        return role
    return fn


def test_unknown_person_is_always_student():
    calls = []
    fn = lambda pid, now: calls.append(pid) or "admin"
    role = resolve_role(known=False, consent_granted=True, person_id="p1", get_effective_role_fn=fn)
    assert role == ROLE_STUDENT
    assert calls == []  # Registry wird gar nicht erst abgefragt


def test_revoked_consent_is_always_student():
    calls = []
    fn = lambda pid, now: calls.append(pid) or "admin"
    role = resolve_role(known=True, consent_granted=False, person_id="p1", get_effective_role_fn=fn)
    assert role == ROLE_STUDENT
    assert calls == []


def test_empty_person_id_is_always_student():
    role = resolve_role(known=True, consent_granted=True, person_id="", get_effective_role_fn=_registry_fn())
    assert role == ROLE_STUDENT


def test_registry_failure_falls_back_to_student():
    def raising(pid, now):
        raise RuntimeError("registry nicht erreichbar")
    role = resolve_role(known=True, consent_granted=True, person_id="p1", get_effective_role_fn=raising)
    assert role == ROLE_STUDENT


def test_valid_known_consented_person_gets_the_registry_role():
    role = resolve_role(
        known=True, consent_granted=True, person_id="p1",
        get_effective_role_fn=_registry_fn(ROLE_ADMIN))
    assert role == ROLE_ADMIN


def test_the_identity_role_field_is_never_consulted():
    # resolve_role() hat gar keinen Parameter fuer PersonIdentity.role --
    # struktureller Nachweis, dass dieses Feld hier nicht existieren
    # KANN (siehe command_router_node.py-Aenderung, die es nicht mehr
    # liest).
    import inspect
    params = inspect.signature(resolve_role).parameters
    assert "role" not in params
    assert "identity_role" not in params
