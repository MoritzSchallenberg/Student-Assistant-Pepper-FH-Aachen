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
    )


def test_unknown_mode_raises_before_any_node_is_declared(launch_module):
    ctx = LaunchContext()
    with pytest.raises(RuntimeError, match="unbekannter mode"):
        launch_module._validate_mode_and_guards(
            ctx, TextSubstitution(text="not_a_real_mode"), TextSubstitution(text="false"),
        )


def test_production_without_confirmation_flag_raises(launch_module):
    ctx = LaunchContext()
    with pytest.raises(RuntimeError, match="i_confirm_hardware_acceptance_complete"):
        launch_module._validate_mode_and_guards(
            ctx, TextSubstitution(text="production"), TextSubstitution(text="false"),
        )


def test_production_with_confirmation_flag_does_not_raise(launch_module):
    ctx = LaunchContext()
    result = launch_module._validate_mode_and_guards(
        ctx, TextSubstitution(text="production"), TextSubstitution(text="true"),
    )
    assert result  # eine LogInfo-Aktion, kein Fehler


@pytest.mark.parametrize("mode", [
    "offline_test", "microphone_test", "realsense_test", "navigation_dry_run",
])
def test_non_production_modes_never_need_the_confirmation_flag(launch_module, mode):
    ctx = LaunchContext()
    # production_confirm bleibt bei "false" -- darf fuer jeden anderen
    # Modus NIE einen Fehler ausloesen (nur mode=="production" prueft das).
    result = launch_module._validate_mode_and_guards(
        ctx, TextSubstitution(text=mode), TextSubstitution(text="false"),
    )
    assert result


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
