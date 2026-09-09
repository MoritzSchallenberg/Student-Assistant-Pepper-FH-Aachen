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
from ihk_pepper_interaction.roles import ROLE_EMPLOYEE
from ihk_pepper_interfaces.msg import AudioFocusState, InteractionCommand, PersonIdentity, PersonIdentityArray, SafetyState
from std_msgs.msg import Bool


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
    _lookup_identity = CommandRouterNode._lookup_identity
    _safety_state_valid = CommandRouterNode._safety_state_valid
    _on_command = CommandRouterNode._on_command

    def __init__(self, policy=POLICY_ROLE_PLUS_CONFIRMATION, minimum_confidence=0.8):
        self._latest_identities = None
        self._latest_focus_track_id = -1
        self._safety_state = None
        self._secondary_confirmation_valid = False
        self.command_pub = _FakePublisher()
        self._params = {
            "privileged_motion_policy": policy,
            "minimum_recognition_confidence": minimum_confidence,
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
