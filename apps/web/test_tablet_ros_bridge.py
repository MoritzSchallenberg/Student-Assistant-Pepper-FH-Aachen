"""
Tests fuer die sichere Bestaetigungsansicht in tablet/ros_bridge.py
(Entwicklungsauftrag 04-B, AP7.1, Abschnitt 10). Testet ausschliesslich
die reinen Konvertierungs-/Filterfunktionen und die Eingabepruefung von
confirm_authorization() direkt an einer TabletRosBridge-Instanz -- kein
echtes ROS2 noetig (TabletRosBridge bleibt auch ohne rclpy konstruierbar,
siehe Moduldoku _try_import_ros()).
"""
import time
import types

from tablet.ros_bridge import TabletRosBridge


def _bridge():
    return TabletRosBridge()


def _fake_stamp(seconds):
    whole = int(seconds)
    return types.SimpleNamespace(sec=whole, nanosec=int((seconds - whole) * 1e9))


def _fake_request(request_id="r1", nonce="n1", person_id="p1", role="employee",
                   command="follow_speaker", created_at_s=1000.0, expires_at_s=1030.0):
    return types.SimpleNamespace(
        request_id=request_id, nonce=nonce, person_id=person_id, role=role, command=command,
        created_at=_fake_stamp(created_at_s), expires_at=_fake_stamp(expires_at_s),
    )


def test_authorization_request_to_dict_maps_known_command_to_a_description():
    b = _bridge()
    d = b._authorization_request_to_dict(_fake_request(command="follow_speaker"))
    assert d["request_id"] == "r1"
    assert d["nonce"] == "n1"
    assert d["known"] is True
    assert d["role"] == "employee"
    assert "folgt" in d["action_description"].lower()


def test_authorization_request_to_dict_unknown_command_has_a_generic_description():
    b = _bridge()
    d = b._authorization_request_to_dict(_fake_request(command="some_future_command"))
    assert "some_future_command" in d["action_description"]


def test_authorization_request_to_dict_empty_person_id_is_not_known():
    b = _bridge()
    d = b._authorization_request_to_dict(_fake_request(person_id=""))
    assert d["known"] is False


def test_on_authorization_decision_clears_the_matching_pending_request():
    b = _bridge()
    b._store("pending_authorization", b._authorization_request_to_dict(_fake_request(request_id="r1")))
    b._on_authorization_decision(types.SimpleNamespace(request_id="r1"))
    assert b._data["pending_authorization"] is None


def test_on_authorization_decision_ignores_a_different_request_id():
    # Ein alter/anderer Request darf den aktuell angezeigten NICHT
    # loeschen -- sonst koennte eine ueberholte Entscheidung eine
    # gerade erst gestellte, noch offene Anfrage verstecken.
    b = _bridge()
    b._store("pending_authorization", b._authorization_request_to_dict(_fake_request(request_id="r1")))
    b._on_authorization_decision(types.SimpleNamespace(request_id="r2"))
    assert b._data["pending_authorization"] is not None
    assert b._data["pending_authorization"]["request_id"] == "r1"


def test_get_snapshot_hides_an_expired_pending_authorization():
    b = _bridge()
    b._store("pending_authorization", b._authorization_request_to_dict(
        _fake_request(created_at_s=time.time() - 100, expires_at_s=time.time() - 1)))
    snapshot = b.get_snapshot()
    assert snapshot["pending_authorization"] is None


def test_get_snapshot_shows_a_still_valid_pending_authorization():
    b = _bridge()
    b._store("pending_authorization", b._authorization_request_to_dict(
        _fake_request(created_at_s=time.time(), expires_at_s=time.time() + 60)))
    snapshot = b.get_snapshot()
    assert snapshot["pending_authorization"] is not None
    assert snapshot["pending_authorization"]["request_id"] == "r1"


def test_confirm_authorization_rejects_when_bridge_unavailable():
    b = _bridge()
    b.available = False
    success, reason = b.confirm_authorization("r1", "n1", True)
    assert success is False
    assert "nicht verfuegbar" in reason


def test_confirm_authorization_rejects_empty_request_id_or_nonce():
    b = _bridge()
    b.available = True
    b._confirm_authorization_client = object()  # wird bei leerer request_id/nonce nie erreicht
    success, reason = b.confirm_authorization("", "n1", True)
    assert success is False
    success2, reason2 = b.confirm_authorization("r1", "", True)
    assert success2 is False
