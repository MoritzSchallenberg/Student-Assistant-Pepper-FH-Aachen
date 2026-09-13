"""
Automatisierter Struktur-/Verhaltenstest fuer
interaction_full_safe.launch.py (Entwicklungsauftrag 04-B, Bedingung 10
-- diese Datei hatte bis dahin ausschliesslich manuelle
--show-args-/Live-Verifikation, siehe deren eigene Moduldoku).

Startet NIE echte Nodes/Prozesse (kein `ros2 launch`, kein
LaunchService.run()) -- prueft ausschliesslich generate_launch_description()s
Struktur und die OpaqueFunction-Gate-Logik direkt, mit einem echten
launch.LaunchContext, aber ohne jede Hardware-/ROS2-Prozess-Aktion.
"""
import importlib.util

import pytest
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.substitutions import TextSubstitution
from launch_ros.actions import Node


def _load_module():
    path = get_package_share_directory("ihk_pepper_bringup") + "/launch/interaction_full_safe.launch.py"
    spec = importlib.util.spec_from_file_location("interaction_full_safe_launch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launch_module():
    return _load_module()


def test_valid_modes_match_required_set(launch_module):
    assert launch_module.VALID_MODES == (
        "offline_test", "microphone_test", "realsense_test",
        "pepper_gesture_test", "navigation_dry_run", "production",
        "respeaker_offline_test", "respeaker_hardware_test",
        "audio_visual_test", "respeaker_head_test",
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 26/30.
        "role_authorization_offline_test", "group_interaction_offline_test",
        "follow_person_dry_run", "interaction_lifecycle_dry_run",
        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20.
        "identity_offline_test", "authorization_tablet_test",
        "command_follow_dry_run", "group_interaction_dry_run",
    )


def _validate(
        launch_module, ctx, mode, production_confirm="false", head_test_confirm="false",
        gesture_test_confirm="false"):
    return launch_module._validate_mode_and_guards(
        ctx, TextSubstitution(text=mode), TextSubstitution(text=production_confirm),
        TextSubstitution(text=head_test_confirm), TextSubstitution(text=gesture_test_confirm),
    )


def test_unknown_mode_raises_before_any_node_is_declared(launch_module):
    ctx = LaunchContext()
    with pytest.raises(RuntimeError, match="unbekannter mode"):
        _validate(launch_module, ctx, "not_a_real_mode")


def test_production_without_confirmation_flag_raises(launch_module):
    ctx = LaunchContext()
    with pytest.raises(RuntimeError, match="i_confirm_hardware_acceptance_complete"):
        _validate(launch_module, ctx, "production", production_confirm="false")


def test_production_with_confirmation_flag_does_not_raise(launch_module):
    ctx = LaunchContext()
    result = _validate(launch_module, ctx, "production", production_confirm="true")
    assert result  # eine LogInfo-Aktion, kein Fehler


def test_respeaker_head_test_without_confirmation_flag_raises(launch_module):
    ctx = LaunchContext()
    with pytest.raises(RuntimeError, match="i_confirm_head_test_supervised"):
        _validate(launch_module, ctx, "respeaker_head_test", head_test_confirm="false")


def test_respeaker_head_test_with_confirmation_flag_does_not_raise(launch_module):
    ctx = LaunchContext()
    result = _validate(launch_module, ctx, "respeaker_head_test", head_test_confirm="true")
    assert result


# Entwicklungsauftrag 04-B, AP8.9, Abschnitt 4/6/8 (bestaetigter Fund):
# pepper_gesture_test/navigation_dry_run setzen beide bridge_dry_run=False
# (echte SSH-Verbindung moeglich), hatten aber bisher UEBERHAUPT KEINE
# Bestaetigungshuerde -- anders als production/respeaker_head_test.
# Deshalb NICHT mehr Teil der "braucht nie eine Huerde"-Parametrisierung
# unten, sondern eigene, dedizierte Tests wie bei den anderen beiden.
@pytest.mark.parametrize("mode", ["pepper_gesture_test", "navigation_dry_run"])
def test_gesture_test_modes_without_confirmation_flag_raise(launch_module, mode):
    ctx = LaunchContext()
    with pytest.raises(RuntimeError, match="i_confirm_gesture_test_supervised"):
        _validate(launch_module, ctx, mode, gesture_test_confirm="false")


@pytest.mark.parametrize("mode", ["pepper_gesture_test", "navigation_dry_run"])
def test_gesture_test_modes_with_confirmation_flag_do_not_raise(launch_module, mode):
    ctx = LaunchContext()
    result = _validate(launch_module, ctx, mode, gesture_test_confirm="true")
    assert result


@pytest.mark.parametrize("mode", [
    "offline_test", "microphone_test", "realsense_test",
    "respeaker_offline_test", "respeaker_hardware_test", "audio_visual_test",
])
def test_non_production_modes_never_need_the_confirmation_flag(launch_module, mode):
    ctx = LaunchContext()
    # production_confirm/head_test_confirm bleiben bei "false" -- darf
    # fuer jeden anderen Modus NIE einen Fehler ausloesen.
    result = _validate(launch_module, ctx, mode)
    assert result


@pytest.mark.parametrize("mode", [
    "offline_test", "microphone_test", "realsense_test",
    "respeaker_offline_test", "respeaker_hardware_test", "audio_visual_test",
])
def test_non_head_test_modes_never_need_the_head_test_confirmation_flag(launch_module, mode):
    ctx = LaunchContext()
    result = _validate(launch_module, ctx, mode, head_test_confirm="false")
    assert result


def test_mode_execution_profile_covers_every_valid_mode(launch_module):
    # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 4: jeder Modus MUSS ein
    # explizites Eintrag haben -- kein stillschweigendes Fehlen, das
    # spaeter zu einem KeyError im PythonExpression fuehren wuerde.
    assert set(launch_module._MODE_EXECUTION_PROFILE.keys()) == set(launch_module.VALID_MODES)


@pytest.mark.parametrize("mode,expected_profile", [
    ("production", "production"),
    ("respeaker_head_test", "supervised_hardware_test"),
    ("pepper_gesture_test", "supervised_hardware_test"),
    ("navigation_dry_run", "supervised_hardware_test"),
])
def test_bridge_live_modes_get_a_hardware_capable_execution_profile(launch_module, mode, expected_profile):
    # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 4 (bestaetigter Fund):
    # diese vier sind die EINZIGEN mit bridge_dry_run=False -- ein
    # execution_profile, das bei diesen weiterhin auf dem sicheren
    # 'offline_mock' (nicht hardwarefaehig) stehen bliebe, wuerde jede
    # Gestenausfuehrung strukturell verhindern, obwohl dry_run=False
    # bereits eine echte SSH-Verbindung erlaubt.
    assert launch_module._MODE_FLAGS[mode][4] is False  # bridge_dry_run
    assert launch_module._MODE_EXECUTION_PROFILE[mode] == expected_profile


@pytest.mark.parametrize("mode", [
    "offline_test", "microphone_test", "realsense_test",
    "respeaker_offline_test", "respeaker_hardware_test", "audio_visual_test",
    "role_authorization_offline_test", "group_interaction_offline_test",
    "follow_person_dry_run", "interaction_lifecycle_dry_run",
    "identity_offline_test", "authorization_tablet_test",
    "command_follow_dry_run", "group_interaction_dry_run",
])
def test_bridge_dry_run_modes_stay_on_the_safe_offline_mock_profile(launch_module, mode):
    assert launch_module._MODE_FLAGS[mode][4] is True  # bridge_dry_run
    assert launch_module._MODE_EXECUTION_PROFILE[mode] == "offline_mock"


def test_bridge_node_motion_permissions_default_to_false_and_are_wired_through(launch_module):
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 5: allow_head_motion/
    # allow_arm_motion/allow_torso_motion muessen tatsaechlich an die
    # Bridge durchgereicht werden (nicht nur deklariert sein) und per
    # Default "false" bleiben, unabhaengig vom gewaehlten mode.
    from launch.utilities import perform_substitutions
    ld = launch_module.generate_launch_description()
    bridge_node = next(
        a for a in ld.entities if getattr(a, "node_executable", None) == "bridge_node")
    param_dict = bridge_node._Node__parameters[0]
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = "production"
    # DeclareLaunchArgument-Defaults werden erst beim tatsaechlichen
    # Visitieren der LaunchDescription in den Kontext geschrieben (nicht
    # bei einem manuell konstruierten LaunchContext) -- hier explizit
    # auf den deklarierten Default gesetzt, um die WIRING (nicht die
    # Deklaration selbst) zu pruefen.
    ctx.launch_configurations["allow_head_motion"] = "false"
    ctx.launch_configurations["allow_arm_motion"] = "false"
    ctx.launch_configurations["allow_torso_motion"] = "false"
    resolved = {
        perform_substitutions(ctx, list(key)): perform_substitutions(ctx, list(value))
        for key, value in param_dict.items()
    }
    assert resolved["allow_head_motion"] == "false"
    assert resolved["allow_arm_motion"] == "false"
    assert resolved["allow_torso_motion"] == "false"

    ctx.launch_configurations["allow_arm_motion"] = "true"
    resolved_after_change = {
        perform_substitutions(ctx, list(key)): perform_substitutions(ctx, list(value))
        for key, value in param_dict.items()
    }
    assert resolved_after_change["allow_arm_motion"] == "true"
    assert resolved_after_change["allow_head_motion"] == "false"  # unabhaengig von allow_arm_motion


def test_motion_capable_and_enable_live_motion_default_to_false(launch_module):
    ld = launch_module.generate_launch_description()
    declares = {
        a.name: a for a in ld.entities if isinstance(a, DeclareLaunchArgument)
    }
    assert declares["motion_capable"].default_value[0].perform(LaunchContext()) == "false"
    assert declares["enable_live_motion"].default_value[0].perform(LaunchContext()) == "false"
    assert declares["i_confirm_hardware_acceptance_complete"].default_value[0].perform(
        LaunchContext()) == "false"
    assert declares["mode"].default_value[0].perform(LaunchContext()) == "offline_test"
    # Entwicklungsauftrag 04-B, AP6.
    assert declares["i_confirm_head_test_supervised"].default_value[0].perform(
        LaunchContext()) == "false"
    assert declares["respeaker_transport_kind"].default_value[0].perform(LaunchContext()) == "mock"
    assert declares["respeaker_backend_kind"].default_value[0].perform(LaunchContext()) == "passthrough"


def test_dialog_manager_node_is_never_referenced(launch_module):
    # Bedingung aus der Moduldoku: run_dialogue_action_server ersetzt
    # dialog_manager_node hier vollstaendig -- kein Node-EINTRAG darf je
    # "dialog_manager_node" als executable tragen (die Moduldoku selbst
    # ERWAEHNT den Namen erklaerend -- deshalb Pruefung auf die
    # tatsaechlichen Node()-Eintraege, nicht auf den Quelltext als Ganzes).
    ld = launch_module.generate_launch_description()
    executables = {e.node_executable for e in ld.entities if isinstance(e, Node)}
    assert "dialog_manager_node" not in executables


def test_run_dialogue_action_server_is_declared_exactly_once(launch_module):
    ld = launch_module.generate_launch_description()
    nodes = [e for e in ld.entities if isinstance(e, Node)]
    matches = [
        n for n in nodes
        if n.node_executable == "run_dialogue_action_server"
    ]
    assert len(matches) == 1


def test_opaque_function_gate_runs_before_any_node_declaration(launch_module):
    # Die OpaqueFunction (Mode-/Production-Gate) muss VOR jedem Node()
    # in der Entities-Liste stehen -- sonst koennte ein Node schon
    # deklariert sein, bevor ein ungueltiger Modus den Start abbricht.
    ld = launch_module.generate_launch_description()
    first_node_index = next(
        i for i, e in enumerate(ld.entities) if isinstance(e, Node)
    )
    gate_index = next(
        i for i, e in enumerate(ld.entities) if isinstance(e, OpaqueFunction)
    )
    assert gate_index < first_node_index


def _find_nav2_include(ld):
    # IncludeLaunchDescription.launch_description_source.location bleibt
    # vor einem echten get_launch_description()-Aufruf unaufgeloest (eine
    # Liste von Substitution-Objekten ohne string-Repraesentation, siehe
    # launch.LaunchDescriptionSource.location-Docstring) -- ein echter
    # Aufruf wuerde nav2_bringup.launch.py tatsaechlich rekursiv laden.
    # Stattdessen ueber das eindeutige cmd_vel_out_topic-Launch-Argument
    # identifizieren, das NUR die nav2_bringup.launch.py-Einbindung traegt.
    includes = [e for e in ld.entities if isinstance(e, IncludeLaunchDescription)]
    matches = [e for e in includes if "cmd_vel_out_topic" in dict(e.launch_arguments)]
    assert len(matches) == 1, "genau eine Einbindung muss cmd_vel_out_topic setzen (nav2_bringup.launch.py)"
    return matches[0]


def test_navigation_dry_run_never_targets_the_real_cmd_vel_topic(launch_module):
    ld = launch_module.generate_launch_description()
    launch_args = dict(_find_nav2_include(ld).launch_arguments)
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = "navigation_dry_run"
    resolved = launch_args["cmd_vel_out_topic"].perform(ctx)
    assert resolved == "navigation_dry_run/cmd_vel_sink"
    assert resolved != "/cmd_vel"


def test_production_mode_resolves_to_the_real_cmd_vel_topic(launch_module):
    # Gegenprobe zum vorigen Test -- bestaetigt, dass NUR production den
    # echten Pfad bekommt (kein Test hier loest je einen echten Start aus,
    # nur die reine String-Aufloesung der Substitution).
    ld = launch_module.generate_launch_description()
    launch_args = dict(_find_nav2_include(ld).launch_arguments)
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = "production"
    assert launch_args["cmd_vel_out_topic"].perform(ctx) == "/cmd_vel"


def test_pepper_gesture_test_mode_flags_disable_perception_and_audio(launch_module):
    # (perception, audio, real_camera, real_nav2, bridge_dry_run)
    assert launch_module._MODE_FLAGS["pepper_gesture_test"] == (False, False, False, False, False)


def test_microphone_test_mode_never_enables_real_navigation(launch_module):
    perception, audio, real_camera, real_nav2, bridge_dry_run = (
        launch_module._MODE_FLAGS["microphone_test"]
    )
    assert audio is True
    assert real_nav2 is False
    assert bridge_dry_run is True  # keine echte SSH-Verbindung, daher keine Pepper-Bewegung moeglich


@pytest.mark.parametrize("mode", [
    "offline_test", "microphone_test", "realsense_test", "pepper_gesture_test", "navigation_dry_run",
])
def test_gesture_memory_node_always_runs_together_with_run_dialogue_action_server(launch_module, mode):
    # Entwicklungsauftrag 04-B, AP5A, Abschnitt 10: gesture_memory_node
    # muss ueberall dort verfuegbar sein, wo run_dialogue_action_server
    # laeuft (sonst faellt jede Gestensuche strukturell aus) -- beide
    # Node()-Eintraege muessen in JEDEM Modus dieselbe Bedingung ergeben.
    ld = launch_module.generate_launch_description()
    nodes_by_executable = {n.node_executable: n for n in ld.entities if isinstance(n, Node)}
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = mode
    dialog_enabled = nodes_by_executable["run_dialogue_action_server"].condition.evaluate(ctx)
    gesture_memory_enabled = nodes_by_executable["gesture_memory_node"].condition.evaluate(ctx)
    assert dialog_enabled == gesture_memory_enabled


def test_respeaker_head_test_mode_is_the_only_one_with_bridge_live(launch_module):
    # (perception, audio, real_camera, real_nav2, bridge_dry_run)
    for mode_name, flags in launch_module._MODE_FLAGS.items():
        bridge_dry_run = flags[4]
        real_nav2 = flags[3]
        if mode_name == "respeaker_head_test":
            assert bridge_dry_run is False
        # Keiner der vier neuen respeaker_*-Modi darf JEMALS real_nav2
        # aktivieren (Auftrag: "kein Nav2" in allen vier Phasen).
        if mode_name in launch_module.RESPEAKER_AUDIO_MODES:
            assert real_nav2 is False


@pytest.mark.parametrize("mode,expected_perception", [
    ("respeaker_offline_test", False),
    ("respeaker_hardware_test", False),
    ("audio_visual_test", True),
    ("respeaker_head_test", False),
])
def test_respeaker_mode_perception_flag_matches_spec(launch_module, mode, expected_perception):
    perception, *_rest = launch_module._MODE_FLAGS[mode]
    assert perception is expected_perception


def test_actuator_arbiter_node_is_always_started(launch_module):
    # Bestaetigter Fund (AP5B/AP6): Say/PlayGesture/SetHeadPose brauchen
    # seit AP5B/AP6 zwingend eine Lease vom Aktuator-Arbiter -- kein
    # Modus darf ohne ihn starten.
    ld = launch_module.generate_launch_description()
    executables = {e.node_executable for e in ld.entities if isinstance(e, Node)}
    assert "actuator_arbiter_node" in executables


def _resolve_source_kind(ld, mode):
    audio_node = next(
        n for n in ld.entities if isinstance(n, Node) and n.node_executable == "audio_node")
    from launch.utilities import perform_substitutions
    param_dict = audio_node._Node__parameters[0]
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = mode
    ctx.launch_configurations["audio_source_kind"] = "microphone"
    for key, value in param_dict.items():
        # Nur den source_kind-Eintrag selbst aufloesen -- die uebrigen
        # Parameter (respeaker_host/_user/_password/...) haetten in
        # diesem minimalen LaunchContext (ohne die restlichen
        # DeclareLaunchArgument-Defaults) keinen aufgeloesten Wert.
        if perform_substitutions(ctx, list(key)) == "source_kind":
            return perform_substitutions(ctx, list(value))
    raise AssertionError("source_kind nicht in audio_node-Parametern gefunden")


@pytest.mark.parametrize("mode", ["respeaker_offline_test", "respeaker_hardware_test",
                                   "audio_visual_test", "respeaker_head_test"])
def test_respeaker_modes_resolve_audio_source_kind_to_respeaker_core_v2(launch_module, mode):
    ld = launch_module.generate_launch_description()
    assert _resolve_source_kind(ld, mode) == "respeaker_core_v2"


def test_non_respeaker_modes_keep_the_configured_audio_source_kind(launch_module):
    ld = launch_module.generate_launch_description()
    assert _resolve_source_kind(ld, "microphone_test") == "microphone"


def test_gesture_memory_node_production_mode_locked_to_true_only_in_production(launch_module):
    ld = launch_module.generate_launch_description()
    gesture_memory_node = next(
        n for n in ld.entities if isinstance(n, Node) and n.node_executable == "gesture_memory_node")
    # Node.parameters ist launch_ros-intern (kein oeffentliches Attribut,
    # Schluessel selbst als Tupel von Substitution-Objekten kodiert) --
    # hier bewusst read-only Introspektion ueber perform_substitutions(),
    # kein Eingriff in den Launch-Ablauf.
    from launch.utilities import perform_substitutions
    param_dict = gesture_memory_node._Node__parameters[0]
    for mode, expected in [("offline_test", "false"), ("production", "true")]:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        resolved = {
            perform_substitutions(ctx, list(key)): perform_substitutions(ctx, list(value))
            for key, value in param_dict.items()
        }
        assert resolved["production_mode"] == expected


def _find_include_by_basename(ld, basename):
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: wie _find_nav2_include()
    # oben -- location bleibt ohne LaunchContext.perform() eine
    # Substitution-Liste ohne brauchbare str()-Repraesentation, hier aber
    # ueber das name-gemangelte private Attribut + perform_substitutions()
    # gegen einen LEEREN LaunchContext aufgeloest (die Pfade selbst sind
    # reine Python-Strings aus get_package_share_directory()+os.path.join(),
    # brauchen also keine echten Launch-Konfigurationswerte).
    from launch.utilities import perform_substitutions
    includes = [e for e in ld.entities if isinstance(e, IncludeLaunchDescription)]
    ctx = LaunchContext()
    matches = [
        e for e in includes
        if perform_substitutions(
            ctx, e.launch_description_source._LaunchDescriptionSource__location
        ).endswith(basename)
    ]
    assert len(matches) == 1, f"genau eine Einbindung von {basename} erwartet, {len(matches)} gefunden"
    return matches[0]


@pytest.mark.parametrize("mode,expected", [
    ("offline_test", False),
    ("microphone_test", False),
    ("pepper_gesture_test", False),
    ("realsense_test", True),
    ("navigation_dry_run", True),
    ("production", True),
    ("respeaker_offline_test", True),
    ("respeaker_hardware_test", True),
    ("audio_visual_test", True),
    ("respeaker_head_test", True),
])
def test_pepper_robot_state_included_for_real_camera_and_respeaker_modes(launch_module, mode, expected):
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: robot_state_publisher
    # (pepper_robot_state.launch.py) ist Voraussetzung fuer JEDE TF-Kette
    # unter "Head" -- RealSense-Modi UND alle vier respeaker_*-Modi
    # brauchen ihn, keine anderen.
    ld = launch_module.generate_launch_description()
    include = _find_include_by_basename(ld, "pepper_robot_state.launch.py")
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = mode
    assert include.condition.evaluate(ctx) is expected


@pytest.mark.parametrize("mode,expected", [
    ("offline_test", False),
    ("microphone_test", False),
    ("realsense_test", False),
    ("pepper_gesture_test", False),
    ("navigation_dry_run", False),
    ("production", False),
    ("respeaker_offline_test", True),
    ("respeaker_hardware_test", True),
    ("audio_visual_test", True),
    ("respeaker_head_test", True),
])
def test_respeaker_static_tf_included_only_for_respeaker_audio_modes(launch_module, mode, expected):
    ld = launch_module.generate_launch_description()
    include = _find_include_by_basename(ld, "respeaker_static_tf.launch.py")
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = mode
    assert include.condition.evaluate(ctx) is expected


# ---- Entwicklungsauftrag 04-B, AP6.1 (7/7): "Produktionsvalidierung" --
# strukturelle Launch-Pruefung statt eines Laufzeit-Supervisors (dieses
# Projekt validiert Launch-Beschreibungen konsequent so, siehe
# test_gesture_memory_node_always_runs_together_with_run_dialogue_action_server
# oben) -- garantiert GENAU einen Publisher je RAW-/kanonischem Audio-
# Richtungstopic, da genau ein Node() -- audio_node bzw.
# sound_direction_transform_node -- je generierter Launch-Beschreibung
# existiert (keine doppelte Deklaration moeglich).

def test_exactly_one_audio_node_and_one_sound_direction_transform_node_declared(launch_module):
    ld = launch_module.generate_launch_description()
    executables = [e.node_executable for e in ld.entities if isinstance(e, Node)]
    # audio_node.py ist der EINZIGE Publisher der RAW-Topics
    # (/audio/sound_direction_raw, /audio/wakeword_event_raw),
    # sound_direction_transform_node.py der EINZIGE Publisher der
    # kanonischen Topics (/audio/sound_direction, /audio/wakeword_event) --
    # siehe deren Moduldoku (AP6.1 Commit 3). Mehr als ein Node()-Eintrag
    # mit demselben Executable-Namen wuerde diese Garantie strukturell
    # verletzen.
    assert executables.count("audio_node") == 1
    assert executables.count("sound_direction_transform_node") == 1


def test_sound_direction_transform_node_runs_in_every_mode_audio_node_does(launch_module):
    # AP6.1 Abschnitt 12: der Transform-Node muss ueberall mitlaufen, wo
    # audio_node aktiv ist -- sonst blieben RAW-Nachrichten unverarbeitet
    # und WaitForFreshWakeword saehe nie ein kanonisches Ereignis.
    ld = launch_module.generate_launch_description()
    nodes_by_executable = {n.node_executable: n for n in ld.entities if isinstance(n, Node)}
    audio_condition = nodes_by_executable["audio_node"].condition
    transform_condition = nodes_by_executable["sound_direction_transform_node"].condition
    for mode in launch_module.VALID_MODES:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        assert audio_condition.evaluate(ctx) == transform_condition.evaluate(ctx)


def test_audio_node_production_mode_locked_to_true_only_in_production(launch_module):
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 7/13 -- bestaetigter Fund:
    # audio_node bekam production_mode bislang NIE ueber dieses Launch-File
    # gesetzt (blieb IMMER beim Node-internen Default false, auch in
    # mode=production) -- die in Commit 1/5 eingefuehrten Start-Guards
    # (continuous_development bzw. allow_ambiguous_direction_for_head_
    # orientation in Produktion gesperrt) haetten dadurch in der echten
    # production-Launch nie gegriffen. Gleiches Pruefmuster wie
    # test_gesture_memory_node_production_mode_locked_to_true_only_in_production.
    # Wie _resolve_source_kind() oben: NUR den production_mode-Eintrag
    # selbst aufloesen -- die uebrigen audio_node-Parameter
    # (respeaker_host/_user/_password/...) haetten in einem minimalen
    # LaunchContext (ohne die restlichen DeclareLaunchArgument-Defaults)
    # keinen aufgeloesten Wert, siehe _resolve_source_kind()-Kommentar.
    from launch.utilities import perform_substitutions
    ld = launch_module.generate_launch_description()
    audio_node = next(
        n for n in ld.entities if isinstance(n, Node) and n.node_executable == "audio_node")
    param_dict = audio_node._Node__parameters[0]
    for mode, expected in [("offline_test", "false"), ("microphone_test", "false"),
                            ("production", "true")]:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        resolved = None
        for key, value in param_dict.items():
            if perform_substitutions(ctx, list(key)) == "production_mode":
                resolved = perform_substitutions(ctx, list(value))
                break
        assert resolved == expected, f"mode={mode}"


# ---- Entwicklungsauftrag 04-B, AP7, Abschnitt 26/30: neue Testmodi ----

def _condition_for(ld, executable):
    return next(
        n for n in ld.entities if isinstance(n, Node) and n.node_executable == executable
    ).condition


def test_ap7_offline_test_modes_never_enable_real_navigation_or_camera(launch_module):
    for mode in launch_module.AP7_OFFLINE_TEST_MODES:
        perception, audio, real_camera, real_nav2, bridge_dry_run = (
            launch_module._MODE_FLAGS[mode]
        )
        assert real_camera is False
        assert real_nav2 is False
        assert bridge_dry_run is True


def test_command_router_node_runs_wherever_audio_does(launch_module):
    # command_router_node braucht /interaction/command aus
    # sound_direction_transform_node -- muss also GENAU dieselbe
    # Bedingung wie audio_node/sound_direction_transform_node haben
    # (gleiches Pruefmuster wie
    # test_sound_direction_transform_node_runs_in_every_mode_audio_node_does).
    ld = launch_module.generate_launch_description()
    audio_condition = _condition_for(ld, "audio_node")
    router_condition = _condition_for(ld, "command_router_node")
    for mode in launch_module.VALID_MODES:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        assert audio_condition.evaluate(ctx) == router_condition.evaluate(ctx), f"mode={mode}"


def test_group_tracking_node_runs_wherever_perception_does(launch_module):
    ld = launch_module.generate_launch_description()
    perception_condition = _condition_for(ld, "perception_node")
    group_condition = _condition_for(ld, "group_tracking_node")
    for mode in launch_module.VALID_MODES:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        assert perception_condition.evaluate(ctx) == group_condition.evaluate(ctx), f"mode={mode}"


def test_enable_follow_person_is_true_only_in_follow_person_dry_run(launch_module):
    from launch.utilities import perform_substitutions
    ld = launch_module.generate_launch_description()
    person_approach = next(
        n for n in ld.entities if isinstance(n, Node) and n.node_executable == "person_approach_node")
    param_dict = person_approach._Node__parameters[0]
    for mode, expected in [
        ("offline_test", "false"), ("microphone_test", "false"),
        ("role_authorization_offline_test", "false"),
        ("group_interaction_offline_test", "false"),
        ("interaction_lifecycle_dry_run", "false"),
        ("follow_person_dry_run", "true"),
        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20: command_follow_dry_run
        # ist gleichbedeutend mit follow_person_dry_run.
        ("command_follow_dry_run", "true"),
        ("identity_offline_test", "false"),
        ("authorization_tablet_test", "false"),
        ("group_interaction_dry_run", "false"),
    ]:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        resolved = None
        for key, value in param_dict.items():
            if perform_substitutions(ctx, list(key)) == "enable_follow_person":
                resolved = perform_substitutions(ctx, list(value))
                break
        assert resolved == expected, f"mode={mode}"


def test_ap7_offline_test_modes_use_mock_nav2(launch_module):
    # Dieselben Knoten wie offline_test (camera_pose_gate_node/
    # mock_nav2_server/person_approach_node/...) -- niemals der echte
    # Nav2-/RTAB-Map-Pfad.
    ld = launch_module.generate_launch_description()
    mock_nav2_condition = _condition_for(ld, "mock_nav2_server")
    for mode in launch_module.AP7_OFFLINE_TEST_MODES:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        assert mock_nav2_condition.evaluate(ctx) is True, f"mode={mode}"


# ---- Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20: identity_offline_test/
#      authorization_tablet_test/command_follow_dry_run/
#      group_interaction_dry_run ----

def test_face_identity_node_runs_wherever_perception_does(launch_module):
    ld = launch_module.generate_launch_description()
    perception_condition = _condition_for(ld, "perception_node")
    for mode in launch_module.VALID_MODES:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        result = launch_module._launch_identity_node(
            ctx, TextSubstitution(text=mode),
            TextSubstitution(text="disabled"), TextSubstitution(text="disabled"),
            TextSubstitution(text=""), TextSubstitution(text=""), TextSubstitution(text=""),
            TextSubstitution(text=""), TextSubstitution(text=""), TextSubstitution(text="false"),
        )
        has_identity_node = any(isinstance(a, Node) for a in result)
        ctx2 = LaunchContext()
        ctx2.launch_configurations["mode"] = mode
        assert has_identity_node == perception_condition.evaluate(ctx2), f"mode={mode}"


@pytest.mark.parametrize("mode", ["identity_offline_test", "authorization_tablet_test"])
def test_identity_modes_default_to_mock_face_detector_and_backend(launch_module, mode):
    ld = launch_module.generate_launch_description()
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = mode
    ctx.launch_configurations["identity_face_detector_kind"] = "disabled"
    ctx.launch_configurations["identity_backend_kind"] = "disabled"
    opaque_functions = [e for e in ld.entities if isinstance(e, OpaqueFunction)]
    identity_opaque = next(
        f for f in opaque_functions if f._OpaqueFunction__function.__name__ == "_launch_identity_node")
    resolved_face_kind = identity_opaque._OpaqueFunction__args[1].perform(ctx)
    resolved_identity_kind = identity_opaque._OpaqueFunction__args[2].perform(ctx)
    assert resolved_face_kind == "mock"
    assert resolved_identity_kind == "mock"


def test_non_identity_modes_keep_the_configured_identity_kind(launch_module):
    ld = launch_module.generate_launch_description()
    ctx = LaunchContext()
    ctx.launch_configurations["mode"] = "offline_test"
    ctx.launch_configurations["identity_face_detector_kind"] = "disabled"
    ctx.launch_configurations["identity_backend_kind"] = "disabled"
    opaque_functions = [e for e in ld.entities if isinstance(e, OpaqueFunction)]
    identity_opaque = next(
        f for f in opaque_functions if f._OpaqueFunction__function.__name__ == "_launch_identity_node")
    assert identity_opaque._OpaqueFunction__args[1].perform(ctx) == "disabled"
    assert identity_opaque._OpaqueFunction__args[2].perform(ctx) == "disabled"


def _launch_identity_direct(launch_module, ctx, mode, face_kind="disabled", identity_kind="disabled",
                             model_path="", model_checksum="", template_store_path="",
                             registry_db_path="", camera_calibration_path="", hardware_ready="false"):
    return launch_module._launch_identity_node(
        ctx, TextSubstitution(text=mode), TextSubstitution(text=face_kind),
        TextSubstitution(text=identity_kind), TextSubstitution(text=model_path),
        TextSubstitution(text=model_checksum), TextSubstitution(text=template_store_path),
        TextSubstitution(text=registry_db_path), TextSubstitution(text=camera_calibration_path),
        TextSubstitution(text=hardware_ready),
    )


def _resolved_params(node):
    from launch.utilities import perform_substitutions
    ctx = LaunchContext()
    param_dict = node._Node__parameters[0]
    return {
        perform_substitutions(ctx, list(key)): perform_substitutions(ctx, list(value))
        for key, value in param_dict.items()
    }


def test_launch_identity_node_skips_when_perception_is_disabled(launch_module):
    ctx = LaunchContext()
    result = _launch_identity_direct(launch_module, ctx, "pepper_gesture_test")
    assert result == []


def test_launch_identity_node_uses_the_requested_kind_outside_production(launch_module):
    ctx = LaunchContext()
    result = _launch_identity_direct(
        launch_module, ctx, "identity_offline_test", face_kind="mock", identity_kind="mock")
    node = next(a for a in result if isinstance(a, Node))
    resolved = _resolved_params(node)
    assert resolved["face_detector_kind"] == "mock"
    assert resolved["identity_backend_kind"] == "mock"


def test_launch_identity_node_production_gate_forces_disabled_without_a_valid_model(launch_module):
    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20: KEINES der sieben
    # Gates ist erfuellt (keine Modell-/Speicher-/Registry-/Kalibrierungs-
    # Pfade, keine Hardwarefreigabe) -- selbst ein angefordertes "mock"
    # muss auf "disabled" zurueckfallen (identity bleibt UNKNOWN, role
    # bleibt STUDENT).
    ctx = LaunchContext()
    result = _launch_identity_direct(
        launch_module, ctx, "production", face_kind="mock", identity_kind="mock")
    node = next(a for a in result if isinstance(a, Node))
    resolved = _resolved_params(node)
    assert resolved["face_detector_kind"] == "disabled"
    assert resolved["identity_backend_kind"] == "disabled"


def test_launch_identity_node_production_gate_passes_with_all_files_present(
        launch_module, tmp_path, monkeypatch):
    import hashlib
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model-bytes")
    checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
    template_store_path = tmp_path / "templates.db"
    template_store_path.write_bytes(b"encrypted")
    registry_db_path = tmp_path / "registry.db"
    registry_db_path.write_bytes(b"registry")
    calibration_path = tmp_path / "calibration.yaml"
    calibration_path.write_bytes(b"calib")

    class _FakeStore:
        def __init__(self, *a, **kw):
            pass

        def all_person_ids(self):
            return []

        def get_template(self, person_id):
            return None

        def close(self):
            pass

    import ihk_pepper_identity.biometric_template_store as biometric_template_store_module
    monkeypatch.setattr(biometric_template_store_module, "BiometricTemplateStore", _FakeStore)

    ctx = LaunchContext()
    result = _launch_identity_direct(
        launch_module, ctx, "production", face_kind="mock", identity_kind="mock",
        model_path=str(model_path), model_checksum=checksum,
        template_store_path=str(template_store_path), registry_db_path=str(registry_db_path),
        camera_calibration_path=str(calibration_path), hardware_ready="true",
    )
    node = next(a for a in result if isinstance(a, Node))
    resolved = _resolved_params(node)
    assert resolved["face_detector_kind"] == "mock"
    assert resolved["identity_backend_kind"] == "mock"


def test_ap7_offline_test_modes_never_target_the_real_cmd_vel_topic(launch_module):
    # Der echte Nav2-Bringup (mit dem einzigen echten /cmd_vel-Pfad) wird
    # nur fuer navigation_dry_run/production included -- fuer alle vier
    # neuen Modi darf real_nav_condition nie zutreffen, damit
    # nav2_bringup.launch.py erst gar nicht included wird. Wiederverwendet
    # _find_nav2_include() -- .location ist vor einem echten
    # Launch-Aufruf nicht als String aufloesbar, siehe dessen Kommentar.
    ld = launch_module.generate_launch_description()
    condition = _find_nav2_include(ld).condition
    for mode in launch_module.AP7_OFFLINE_TEST_MODES:
        ctx = LaunchContext()
        ctx.launch_configurations["mode"] = mode
        assert condition.evaluate(ctx) is False, f"mode={mode}"
