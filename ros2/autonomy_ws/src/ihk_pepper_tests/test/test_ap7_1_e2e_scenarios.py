"""
Entwicklungsauftrag 04-B, AP7.1, Abschnitt 18: die fuenf geforderten
Offline-End-zu-Ende-Szenarien (A-E), implementiert als echte,
lauffaehige Tests -- OHNE echte Hardware, OHNE echte Nav2-Fahrt, OHNE
einen echten ROS2-Prozessgraphen (kein rclpy.init()).

"Ende-zu-Ende" bedeutet hier: mehrere ECHTE, bereits einzeln getestete
Produktionsmodule werden in EINEM zusammenhaengenden Ablauf verkettet
(Identitaetsregistrierung -> Rollenaufloesung -> command_router_node ->
AuthorizationGrantCache bzw. Gruppentracking -> aktive Sprecherauswahl),
NICHT nur ein einzelnes Modul isoliert -- die Verdrahtung als ECHTER
ROS2-Graph (Topics/Services zwischen echten Node-Prozessen) ist bereits
einzeln per Live-Rauchtest bestaetigt (siehe die Commit-Nachrichten
5-9 dieses Auftrags: command_router_node/person_approach_node/
face_identity_node/bt_executor_node wurden je gegen einen echten
ROS2-Graphen gestartet und verifiziert). Diese Datei dupliziert das
NICHT, sondern prueft die Logik-Kette, die dort verdrahtet wird.

Wiederverwendet die bereits bestehenden Test-Fakes aus
test_command_router_node.py (_FakeNode/_FakeRoleLookupClient/_command/
_identity/_safety_state/_confirm/_pending_request) statt sie zu
duplizieren.
"""
from ihk_pepper_interaction.authorization_policy import POLICY_ROLE_PLUS_CONFIRMATION
from ihk_pepper_interaction.roles import ROLE_EMPLOYEE, ROLE_STUDENT
from ihk_pepper_interfaces.msg import PersonIdentityArray
from ihk_pepper_interaction.role_resolution import resolve_role
from ihk_pepper_navigation.authorization_grant_cache import AuthorizationGrantCache
from ihk_pepper_navigation.group_observation_pose import compute_group_observation_pose
from ihk_pepper_perception.group_tracking import GroupTracker, GroupTrackingConfig, TrackCandidate, \
    compute_group_geometry
from ihk_pepper_audio.group_speaker_selection import ActiveSpeakerSelector, GroupMemberBearing

from test_command_router_node import (
    _FakeNode,
    _FakeRoleLookupClient,
    _command,
    _confirm,
    _identity,
    _pending_request,
    _safety_state,
)


# ---- Szenario A: bekannte(r) Mitarbeiter(in) folgt -----------------------

def test_scenario_a_known_employee_follows():
    node = _FakeNode(role_lookup_client=_FakeRoleLookupClient(role=ROLE_EMPLOYEE))
    node._on_identities(PersonIdentityArray(identities=[
        _identity(track_id=5, known=True, consent_granted=True, person_id="emp1")]))
    node._on_safety_state(_safety_state(allow_person_approach=True))

    node._on_command(_command(command="follow_speaker", track_id=5))
    # Rolle allein reicht bei POLICY_ROLE_PLUS_CONFIRMATION (Standard-
    # Policy) nicht -- es muss eine sekundaere Bestaetigung angefragt
    # werden, kein sofortiges "granted".
    pending = node.command_pub.messages[-1]
    assert pending.authorization_status == "pending_confirmation"
    request = _pending_request(node)
    assert request.person_id == "emp1"
    assert request.role == ROLE_EMPLOYEE

    # Tablet/Bedienperson bestaetigt die GENAU angezeigte Anfrage.
    response = _confirm(node, request.request_id, request.nonce, approve=True)
    assert response.success is True
    final = node.command_pub.messages[-1]
    assert final.authorization_status == "granted"
    grant = node.grant_pub.messages[-1]
    assert grant.valid is True
    assert grant.person_id == "emp1"
    assert grant.track_id == 5

    # Der Grant reist NUR ueber /authorization/grants (kein gemeinsamer
    # Prozessspeicher) -- person_approach_node.py haelt eine EIGENE
    # AuthorizationGrantCache-Instanz, die diesen Grant unabhaengig
    # validiert, bevor FollowPerson tatsaechlich startet.
    approach_cache = AuthorizationGrantCache()
    expires_at_s = grant.expires_at.sec + grant.expires_at.nanosec / 1e9
    approach_cache.add(grant.grant_id, grant.person_id, grant.track_id, grant.command, expires_at_s)
    ok, reason = approach_cache.validate_and_consume(grant.grant_id, track_id=5, command="follow_speaker")
    assert ok is True, reason


# ---- Szenario B: Student(in) wird abgelehnt -------------------------------

def test_scenario_b_student_is_denied():
    node = _FakeNode(role_lookup_client=_FakeRoleLookupClient(role=ROLE_STUDENT))
    node._on_identities(PersonIdentityArray(identities=[
        _identity(track_id=7, known=True, consent_granted=True, person_id="stu1")]))
    node._on_safety_state(_safety_state(allow_person_approach=True))

    node._on_command(_command(command="follow_speaker", track_id=7))
    out = node.command_pub.messages[-1]
    assert out.authorization_status == "denied"
    # NIE eine Anfrage/NIE einen Grant fuer eine von vornherein
    # abgelehnte Rolle -- ein Student kann diesen Befehl nicht einfach
    # "spaeter noch bestaetigen lassen".
    assert node.auth_request_pub.messages == []
    assert node.grant_pub.messages == []

    # Ein leerer AuthorizationGrantCache lehnt JEDEN Fahrversuch fuer
    # diese track_id konsequent ab -- "keine Bewegung" ist damit nicht
    # nur eine Beobachtung, sondern strukturell erzwungen.
    approach_cache = AuthorizationGrantCache()
    ok, reason = approach_cache.validate_and_consume("irgendein-grant", track_id=7, command="follow_speaker")
    assert ok is False


# ---- Szenario C: Codewort waehrend eines laufenden Gespraechs ------------

def test_scenario_c_codeword_works_during_an_active_conversation_for_anyone():
    node = _FakeNode(role_lookup_client=_FakeRoleLookupClient(role=ROLE_STUDENT))
    # Bewusst OHNE jede Identitaet/Rolle -- das Codewort ist laut Auftrag
    # "kein LLM-Befehl", "deterministisch, VOR jeder normalen
    # Dialogverarbeitung ausgewertet" und rollenfrei (siehe roles.py).
    node._on_safety_state(_safety_state(allow_person_approach=False))  # selbst OHNE Bewegungsfreigabe

    node._on_command(_command(command="interrupt_and_look", track_id=-1))
    out = node.command_pub.messages[-1]
    assert out.authorization_status == "not_required"
    # Kein AuthorizationRequest/kein Grant -- das Codewort umgeht die
    # gesamte zweistufige Bestaetigungsmaschinerie strukturell, exakt
    # wie fuer follow_speaker (Szenario A) beschrieben, aber ohne sie zu
    # durchlaufen.
    assert node.auth_request_pub.messages == []
    assert node.grant_pub.messages == []


# ---- Szenario D: Gruppenunterhaltung --------------------------------------

def test_scenario_d_group_conversation_forms_positions_and_selects_a_speaker():
    fake_time = [0.0]
    tracker = GroupTracker(
        GroupTrackingConfig(join_hysteresis_s=0.0, minimum_stable_duration_s=1.0, minimum_members=2),
        now_fn=lambda: fake_time[0])
    members = [
        TrackCandidate(track_id=1, x_m=3.0, y_m=0.3, stable=True, age_s=0.1, has_3d_position=True),
        TrackCandidate(track_id=2, x_m=3.0, y_m=-0.3, stable=True, age_s=0.1, has_3d_position=True),
    ]
    tracker.update(members, anchor_track_id=1)
    fake_time[0] = 2.0
    snapshot = tracker.update(members, anchor_track_id=1)
    assert snapshot.formed is True
    assert snapshot.stable is True
    assert set(snapshot.member_track_ids) == {1, 2}

    geometry = compute_group_geometry(members, camera_horizontal_fov_deg=87.0)
    assert geometry is not None
    assert geometry.all_members_within_fov is True

    pose = compute_group_observation_pose(
        robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0,
        member_positions=[(m.x_m, m.y_m) for m in members],
        camera_horizontal_fov_deg=87.0, minimum_person_distance_m=0.8,
        maximum_travel_distance_m=5.0,
    )
    assert pose.valid is True

    # Aktive-Sprecher-Auswahl: NUR ein bestaetigtes Gruppenmitglied kann
    # gewinnen, ein fremder Winkel ausserhalb der Gruppe NIE.
    selector = ActiveSpeakerSelector(required_confirming_frames=3)
    bearings = [GroupMemberBearing(track_id=1, bearing_rad=0.1),
                GroupMemberBearing(track_id=2, bearing_rad=-0.1)]
    result = None
    for _ in range(3):
        result = selector.observe(
            vad_active=True, doa_azimuth_rad=0.1, doa_valid=True, members=bearings)
    assert result.selected_track_id == 1
    assert result.changed is True

    outsider = [GroupMemberBearing(track_id=1, bearing_rad=0.1),
                GroupMemberBearing(track_id=2, bearing_rad=-0.1)]
    outsider_result = selector.observe(
        vad_active=True, doa_azimuth_rad=2.5, doa_valid=True, members=outsider)
    assert outsider_result.selected_track_id == 1  # bleibt beim bisherigen, kein fremder Gewinn
    assert outsider_result.changed is False


# ---- Szenario E: Identitaet faellt aus -> UNKNOWN/STUDENT ----------------

def test_scenario_e_identity_outage_falls_back_to_student_but_conversation_continues():
    def _broken_registry_lookup(person_id, now=None):
        raise RuntimeError("person_memory_node nicht erreichbar (simulierter Ausfall)")

    # role_resolution.py faengt JEDEN Fehler des Registry-Aufrufs ab und
    # faellt IMMER auf STUDENT zurueck -- selbst mit known=True.
    role = resolve_role(
        known=True, consent_granted=True, person_id="p-irgendwer",
        get_effective_role_fn=_broken_registry_lookup)
    assert role == ROLE_STUDENT

    node = _FakeNode(
        policy=POLICY_ROLE_PLUS_CONFIRMATION,
        role_lookup_client=_FakeRoleLookupClient(available=False))  # Registry nicht erreichbar
    node._on_identities(PersonIdentityArray(identities=[
        _identity(track_id=9, known=True, consent_granted=True, person_id="p9")]))
    node._on_safety_state(_safety_state(allow_person_approach=True))

    # Privilegierter Befehl bleibt gesperrt (keine Bewegung).
    node._on_command(_command(command="follow_speaker", track_id=9))
    privileged_out = node.command_pub.messages[-1]
    assert privileged_out.authorization_status == "denied"
    assert node.grant_pub.messages == []

    # Ein rollenfreier Befehl (hier: "stop", stellvertretend fuer
    # "normales Gespraech bleibt moeglich" -- dialogue_text durchlaeuft
    # denselben Router-Pfad wie stop, siehe InteractionCommand.msg-Doku:
    # "dialogue_text -- kein Steuerbefehl, geht ans LLM weiter") bleibt
    # trotz des Ausfalls uneingeschraenkt nutzbar.
    node._on_command(_command(command="stop", track_id=9, event_id="evt-2"))
    stop_out = node.command_pub.messages[-1]
    assert stop_out.authorization_status == "not_required"
