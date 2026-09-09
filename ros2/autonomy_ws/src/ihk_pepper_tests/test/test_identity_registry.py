"""
Tests fuer identity_registry.py::effective_role() (Entwicklungsauftrag
04-B, AP7, Abschnitt 6).
"""
from ihk_pepper_person_memory.identity_registry import effective_role


def test_valid_role_without_expiry_is_returned_unchanged():
    assert effective_role("employee", None, now=1000.0) == "employee"


def test_valid_role_before_expiry_is_returned_unchanged():
    assert effective_role("admin", 2000.0, now=1000.0) == "admin"


def test_expired_role_falls_back_to_student():
    assert effective_role("employee", 500.0, now=1000.0) == "student"


def test_expiry_exactly_now_is_still_valid():
    # "now > valid_until" (strikt), nicht ">=" -- der exakte
    # Ablaufzeitpunkt selbst gilt noch als gueltig.
    assert effective_role("admin", 1000.0, now=1000.0) == "admin"


def test_unknown_role_falls_back_to_student():
    assert effective_role("superadmin", None, now=1000.0) == "student"
