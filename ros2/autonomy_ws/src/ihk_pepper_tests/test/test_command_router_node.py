"""
Tests fuer command_router_node.py (Entwicklungsauftrag 04-B, AP7,
Abschnitt 10). Gleiches Duck-Typing-Muster wie
test_audiovisual_association_node.py -- die ECHTEN, ungebundenen
Methoden von CommandRouterNode laufen gegen ein leichtgewichtiges Fake.
"""
from ihk_pepper_interaction.authorization_policy import (
    POLICY_ROLE_ONLY_DEVELOPMENT,
    POLICY_ROLE_PLUS_CONFIRMATION,
)
from ihk_pepper_interaction.command_router_node import CommandRouterNode
from ihk_pepper_interaction.roles import ROLE_EMPLOYEE, ROLE_STUDENT
from ihk_pepper_interfaces.msg import AudioFocusState, InteractionCommand, PersonIdentity, PersonIdentityArray, SafetyState
from ihk_pepper_interfaces.srv import GetEffectiveRole
from std_msgs.msg import Bool


class _FakeFuture:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self):
        return self._result


class _FakeRoleLookupClient:
    """Gleiches Duck-Typing-Muster wie _FakeLeaseClient in
    test_person_approach_base_lease.py -- Standardrolle EMPLOYEE, damit
    die bestehenden Tests (die ihre Test-Identitaeten mit role=EMPLOYEE
    bauen) unveraendert funktionieren, obwohl PersonIdentity.role seit
    AP7.1 nicht mehr gelesen wird (siehe command_router_node.py::
    _lookup_identity())."""

    def __init__(self, available=True, role=ROLE_EMPLOYEE):
        self.available = available
        self.role = role
        self.requested_person_ids = []

    def wait_for_service(self, timeout_sec=None):
        return self.available

    def call_async(self, request):
        self.requested_person_ids.append(request.person_id)
        response = GetEffectiveRole.Response()
        response.role = self.role
        return _FakeFuture(response)


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def info(self, *a, **kw):
        pass

    def warn(self, *a, **kw):
        pass


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeNode:
    _on_focus_state = CommandRouterNode._on_focus_state
    _on_identities = CommandRouterNode._on_identities
    _on_safety_state = CommandRouterNode._on_safety_state
    _on_secondary_confirmation = CommandRouterNode._on_secondary_confirmation
    _get_effective_role = CommandRouterNode._get_effective_role
    _lookup_identity = CommandRouterNode._lookup_identity
    _safety_state_valid = CommandRouterNode._safety_state_valid
    _on_command = CommandRouterNode._on_command
    _issue_grant = CommandRouterNode._issue_grant

    def __init__(self, policy=POLICY_ROLE_PLUS_CONFIRMATION, minimum_confidence=0.8,
                 grant_validity_s=30.0, role_lookup_client=None):
        self._latest_identities = None
        self._latest_focus_track_id = -1
        self._safety_state = None
        self._secondary_confirmation_valid = False
        self.command_pub = _FakePublisher()
        self.grant_pub = _FakePublisher()
        self.role_lookup_client = role_lookup_client or _FakeRoleLookupClient()
        self._params = {
            "privileged_motion_policy": policy,
            "minimum_recognition_confidence": minimum_confidence,
            "grant_validity_s": grant_validity_s,
        }

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()


def _command(command="follow_speaker", track_id=-1, event_id="evt-1"):
    msg = InteractionCommand()
    msg.event_id = event_id
    msg.command = command
    msg.track_id = track_id
    msg.direction_valid = True
    msg.direction_azimuth_rad_base = 0.3
    return msg


def _identity(track_id=5, known=True, consent_granted=True, role=ROLE_EMPLOYEE,
              confidence=0.95, liveness_passed=True, person_id="p1"):
    identity = PersonIdentity()
    identity.track_id = track_id
    identity.known = known
    identity.consent_granted = consent_granted
    identity.role = role
    identity.recognition_confidence = confidence
    identity.liveness_passed = liveness_passed
    identity.person_id = person_id
    return identity


def _safety_state(allow_person_approach=True):
    msg = SafetyState()
    msg.allow_person_approach = allow_person_approach
    return msg


# ---- rollenfreie Befehle: immer durchgereicht ----

def test_stop_command_is_never_required_even_without_any_context():
    node = _FakeNode()
    node._on_command(_command(command="stop"))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "not_required"


# ---- follow_speaker: fehlende Voraussetzungen ----

def test_follow_speaker_without_any_identity_is_denied():
    node = _FakeNode()
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.reason == "identity_unknown"


def test_follow_speaker_with_known_employee_but_no_confirmation_is_denied():
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity()]))
    node._on_safety_state(_safety_state())
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.reason == "keine_zusatzbestaetigung"


def test_follow_speaker_fully_confirmed_is_granted():
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity()]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "granted"
    assert out.person_id == "p1"
    assert out.role == ROLE_EMPLOYEE


# ---- Entwicklungsauftrag 04-B, AP7.1, Abschnitt 8: Rollenaufloesung
#      AUSSCHLIESSLICH ueber /get_effective_role, NIE ueber
#      PersonIdentity.role ----

def test_identity_role_field_is_ignored_registry_role_wins():
    # Die PersonIdentity-Nachricht behauptet "admin", die Registry sagt
    # "employee" -- das Ergebnis MUSS "employee" sein (die Nachricht
    # selbst darf niemals eine Rolle erhoehen koennen).
    node = _FakeNode(role_lookup_client=_FakeRoleLookupClient(role=ROLE_EMPLOYEE))
    node._on_identities(PersonIdentityArray(identities=[_identity(role="admin")]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.role == ROLE_EMPLOYEE
    assert node.role_lookup_client.requested_person_ids == ["p1"]


def test_registry_reports_student_denies_the_privileged_command():
    node = _FakeNode(role_lookup_client=_FakeRoleLookupClient(role=ROLE_STUDENT))
    node._on_identities(PersonIdentityArray(identities=[_identity(role="admin")]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.role == ROLE_STUDENT


def test_unreachable_role_registry_fails_closed_to_student():
    node = _FakeNode(role_lookup_client=_FakeRoleLookupClient(available=False))
    node._on_identities(PersonIdentityArray(identities=[_identity(role="admin")]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.role == ROLE_STUDENT


def test_follow_speaker_falls_back_to_focus_track_id_when_raw_track_id_is_unknown():
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity(track_id=7)]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_focus_state(AudioFocusState(valid=True, selected_track_id=7))
    node._on_command(_command(command="follow_speaker", track_id=-1))
    out = node.command_pub.messages[0]
    assert out.track_id == 7
    assert out.authorization_status == "granted"


def test_follow_speaker_denied_when_safety_state_invalid():
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity()]))
    node._on_safety_state(_safety_state(allow_person_approach=False))
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.reason == "safety_state_ungueltig"


def test_follow_speaker_denied_for_a_different_tracks_identity():
    # Die Identitaet gehoert zu Track 5, der Befehl kommt aber (laut
    # Fokus-Fallback) von Track 99 -- KEINE automatische Uebernahme.
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity(track_id=5)]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=99))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.reason == "identity_unknown"


def test_development_policy_grants_without_liveness_or_confirmation():
    node = _FakeNode(policy=POLICY_ROLE_ONLY_DEVELOPMENT)
    node._on_identities(PersonIdentityArray(identities=[_identity(liveness_passed=False)]))
    node._on_command(_command(command="follow_speaker", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "granted"


def test_change_system_mode_is_always_denied():
    node = _FakeNode(policy=POLICY_ROLE_ONLY_DEVELOPMENT)
    node._on_command(_command(command="change_system_mode", track_id=5))
    out = node.command_pub.messages[0]
    assert out.authorization_status == "denied"
    assert out.reason == "befehl_nie_per_sprache_erlaubt"


def test_output_preserves_event_id_and_direction():
    node = _FakeNode()
    node._on_command(_command(command="stop", event_id="evt-42"))
    out = node.command_pub.messages[0]
    assert out.event_id == "evt-42"
    assert out.direction_valid is True
    assert out.direction_azimuth_rad_base == 0.3


# ---- AuthorizationGrant-Ausstellung (Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9) ----

def test_granted_command_issues_an_authorization_grant():
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity()]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5))
    assert len(node.grant_pub.messages) == 1
    grant = node.grant_pub.messages[0]
    assert grant.person_id == "p1"
    assert grant.track_id == 5
    assert grant.command == "follow_speaker"
    assert grant.valid is True
    assert grant.grant_id  # nicht leer


def test_denied_command_issues_no_grant():
    node = _FakeNode()
    node._on_command(_command(command="follow_speaker", track_id=5))
    assert node.grant_pub.messages == []


def test_rollenfreier_befehl_ohne_grant():
    node = _FakeNode()
    node._on_command(_command(command="stop"))
    assert node.grant_pub.messages == []


def test_each_grant_gets_a_unique_id():
    node = _FakeNode()
    node._on_identities(PersonIdentityArray(identities=[_identity()]))
    node._on_safety_state(_safety_state())
    node._on_secondary_confirmation(Bool(data=True))
    node._on_command(_command(command="follow_speaker", track_id=5, event_id="evt-1"))
    node._on_command(_command(command="follow_speaker", track_id=5, event_id="evt-2"))
    ids = {g.grant_id for g in node.grant_pub.messages}
    assert len(ids) == 2
