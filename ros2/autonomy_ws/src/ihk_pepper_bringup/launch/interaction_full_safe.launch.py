"""
interaction_full_safe: die EINE zentrale, vollstaendige Startdatei fuer
das Interaktionssystem (Entwicklungsauftrag 4, AP3).

Startet je nach `mode` einen sicheren, ueberschneidungsfreien
Knotengraphen -- WICHTIG (Auftrag AP3): der AELTERE dialog_manager_node
laeuft hier NIE zusammen mit dem NEUEN run_dialogue_action_server (beide
wuerden sonst um dieselbe Aufgabe konkurrieren, siehe
docs/DEVELOPMENT_ORDER_03_REPORT.md AP11). Dieses Launch startet
IMMER run_dialogue_action_server, NIE dialog_manager_node
(dialog_manager_node bleibt ausschliesslich fuer den separaten,
unveraenderten dialog_only.launch.py-Passivmodus erhalten).

Beim normalen Start wird KEINE Fahrt und KEINE Armbewegung ausgeloest:
motion_capable und enable_live_motion bleiben in JEDEM Modus false,
ausser production setzt sie nach bestandener Sicherheitsabnahme explizit
-- selbst dann bleibt das bestehende Zwei-Schluessel-System
(motion_capable-Parameter UND separate /set_motion_permission-Anfrage,
siehe SafetyGate) unveraendert zusaetzlich erforderlich.

Unterstuetzte Modi (Auftrag AP3):

    offline_test        kein Pepper, keine Kamera, mock_nav2_server,
                         alles Software/Mock -- fuer CI/Entwicklung.
    microphone_test      wie offline_test, zusaetzlich echtes Mikrofon
                         + Faster-Whisper, KEINE Pepper-Bewegung.
    realsense_test       wie offline_test, echte RealSense statt Mock-
                         Kamerapfad, weiterhin mock_nav2_server (kein
                         echter Nav2-Stack).
    pepper_gesture_test   echter Pepper per SSH/qicli, NUR einzeln per
                         Action ausgeloeste Gesten (kein Perception/
                         Navigation/Audio, damit nichts automatisch
                         etwas ausloest) -- siehe
                         pepper_gesture_test.launch.py fuer denselben,
                         bewusst minimalen Ansatz.
    navigation_dry_run    echter Nav2-Stack gegen echte RealSense-Daten,
                         Motion Guard vollstaendig durchlaufen, aber
                         cmd_vel_out_topic auf einen Sink umgebogen --
                         KEIN Publisher zum echten /cmd_vel.
    production           voller Stack, echter Pepper, echte Kamera,
                         echter Nav2-Pfad zum ECHTEN /cmd_vel -- NUR
                         erreichbar mit
                         i_confirm_hardware_acceptance_complete:=true,
                         siehe docs/NAVIGATION_SAFETY_ACCEPTANCE.md.
                         Ohne dieses Flag bricht der Start sofort ab.

    Entwicklungsauftrag 04-B, AP6, Abschnitt 16 (ReSpeaker/Wakeword):

    respeaker_offline_test  synthetische Mehrkanaldaten (respeaker_transport_kind=mock),
                         Mock-DoA (respeaker_backend_kind=passthrough),
                         KEIN Perception-Node (keine echte Kamera -> keine
                         echten Personentracks), Bridge dry_run -- reine
                         Software-Verdrahtungspruefung des gesamten
                         Wakeword-Pfads, kein /cmd_vel.
    respeaker_hardware_test  echter ReSpeaker (respeaker_transport_kind
                         auf ssh_pcm/local_alsa/network_pcm setzen,
                         respeaker_host/_user/_password), echte
                         Richtungsdaten (respeaker_backend_kind=gcc_phat),
                         weiterhin KEIN echter Pepper (Bridge dry_run) --
                         Kopfbewegung bliebe selbst bei echtem Wakeword
                         nur ein simulierter play_trajectory()-Aufruf.
    audio_visual_test    echter ReSpeaker + echte RealSense (real_camera),
                         audiovisuelle Zuordnung laeuft gegen ECHTE
                         Personentracks -- Pepper-Aktuatoren bleiben
                         weiterhin Dry-Run, kein Nav2, kein /cmd_vel.
    respeaker_head_test  echter ReSpeaker + echter Pepper-KOPF (Bridge
                         NICHT dry_run) -- NUR mit
                         i_confirm_head_test_supervised:=true erreichbar
                         (physischer Not-Stopp + Bedienperson
                         erforderlich, siehe
                         docs/RESPEAKER_HARDWARE_ACCEPTANCE.md Phase C).
                         Mapping/Nav2 bleiben vollstaendig deaktiviert,
                         keine Arme/Basis moeglich (SetHeadPose ist der
                         einzige scharfe Aktuator-Pfad in diesem Modus).

Startet je nach Modus aus (siehe Knotenliste unten fuer die genaue
Zuordnung): bridge_node, audio_node, perception_node,
person_memory_node, gesture_memory_node, supervisor_node, bt_executor_node,
run_dialogue_action_server, presentation_manager_node, motion_guard_node,
optional RealSense-/Navigationskomponenten.

NICHT live gegen echten Pepper/echte RealSense getestet in dieser
Sitzung (Entwicklungsauftrag 4) -- nur Launch-Struktur
(--show-args) und der offline_test-Modus als echter Prozessstart
verifiziert, siehe docs/DEVELOPMENT_ORDER_04_REPORT.md.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node

VALID_MODES = (
    "offline_test",
    "microphone_test",
    "realsense_test",
    "pepper_gesture_test",
    "navigation_dry_run",
    "production",
    # Entwicklungsauftrag 04-B, AP6, Abschnitt 16.
    "respeaker_offline_test",
    "respeaker_hardware_test",
    "audio_visual_test",
    "respeaker_head_test",
)

# Welche Komponenten laufen in welchem Modus -- explizite Tabelle statt
# verstreuter if/else-Zweige, damit auf einen Blick nachvollziehbar
# bleibt, was ein Modus tatsaechlich startet (Auftrag AP3: "Beim
# normalen Start darf kein Fahrbefehl und keine Armbewegung ausgeloest
# werden").
_MODE_FLAGS = {
    #                    perception  audio  real_camera  real_nav2  bridge_dry_run
    "offline_test":      (True,      False, False,       False,     True),
    "microphone_test":   (True,      True,  False,       False,     True),
    "realsense_test":    (True,      False, True,        False,     True),
    "pepper_gesture_test": (False,   False, False,       False,     False),
    "navigation_dry_run": (True,     True,  True,        True,      False),
    "production":         (True,     True,  True,        True,      False),
    # Entwicklungsauftrag 04-B, AP6, Abschnitt 16: keiner dieser vier
    # Modi startet jemals Nav2/den echten /cmd_vel (real_nav2 bleibt
    # ueberall False) -- respeaker_head_test ist der EINZIGE der vier mit
    # bridge_dry_run=False (echte Kopfbewegung ueberhaupt moeglich),
    # zusaetzlich hinter einer eigenen expliziten Bestaetigung
    # (i_confirm_head_test_supervised) gesperrt, siehe
    # _validate_mode_and_guards().
    "respeaker_offline_test": (False, True, False,      False,     True),
    "respeaker_hardware_test": (False, True, False,     False,     True),
    "audio_visual_test":      (True,  True, True,       False,     True),
    "respeaker_head_test":    (False, True, False,      False,     False),
}

# Modi, in denen audio_node source_kind=respeaker_core_v2 verwenden soll
# (statt des per audio_source_kind gewaehlten Werts) -- eigene
# Konstante statt eines weiteren Tabellenindex, damit _MODE_FLAGS bei
# den bereits bestehenden Modi unveraendert bleibt.
RESPEAKER_AUDIO_MODES = (
    "respeaker_offline_test", "respeaker_hardware_test",
    "audio_visual_test", "respeaker_head_test",
)


def _validate_mode_and_guards(
        context, mode_arg, production_confirm_arg, head_test_confirm_arg, *args, **kwargs):
    mode = context.perform_substitution(mode_arg)
    if mode not in VALID_MODES:
        raise RuntimeError(
            f"interaction_full_safe.launch.py: unbekannter mode '{mode}'. "
            f"Erlaubt: {', '.join(VALID_MODES)}."
        )
    if mode == "production":
        if context.perform_substitution(production_confirm_arg) != "true":
            raise RuntimeError(
                "interaction_full_safe.launch.py: mode=production verlangt "
                "i_confirm_hardware_acceptance_complete:=true. Das ist "
                "KEINE echte Sicherheitspruefung, nur eine Huerde gegen "
                "versehentliches Copy-Paste -- die eigentliche Abnahme "
                "(RealSense-Abdeckung, Kalibrierung, TF, Lokalisierung, "
                "Costmaps, Collision Monitor, Stoppkette) MUSS vorher "
                "einzeln nach docs/NAVIGATION_SAFETY_ACCEPTANCE.md "
                "nachgewiesen sein. NIEMALS unbeaufsichtigt starten."
            )
        return [LogInfo(msg=(
            "*** mode=production: echter Pepper, echte Bewegung MOEGLICH "
            "(zusaetzlich weiterhin durch motion_capable + "
            "/set_motion_permission gesperrt, bis explizit freigegeben). "
            "NIE unbeaufsichtigt lassen. ***"
        ))]
    if mode == "respeaker_head_test":
        if context.perform_substitution(head_test_confirm_arg) != "true":
            raise RuntimeError(
                "interaction_full_safe.launch.py: mode=respeaker_head_test "
                "verlangt i_confirm_head_test_supervised:=true. Dieser Modus "
                "bewegt Peppers ECHTEN Kopf (SetHeadPose, dry_run=false) -- "
                "NUR mit physischem Not-Stopp in Reichweite und einer "
                "Bedienperson direkt am Roboter starten (Auftrag Abschnitt "
                "16/20, Phase C). Keine Arme, keine Basis, Mapping/Nav2 "
                "bleiben in diesem Modus vollstaendig deaktiviert."
            )
        return [LogInfo(msg=(
            "*** mode=respeaker_head_test: ECHTE Kopfbewegung moeglich "
            "(nur HeadYaw/HeadPitch, niedrige Geschwindigkeit ueber "
            "orient_to_sound). NIEMALS unbeaufsichtigt lassen. ***"
        ))]
    return [LogInfo(msg=f"interaction_full_safe: mode={mode} -- keine Bewegung ohne explizite Freigabe.")]


def generate_launch_description():
    mode = LaunchConfiguration("mode")
    motion_capable = LaunchConfiguration("motion_capable")
    enable_live_motion = LaunchConfiguration("enable_live_motion")
    audio_source_kind = LaunchConfiguration("audio_source_kind")
    camera_name = LaunchConfiguration("camera_name")
    database_path = LaunchConfiguration("database_path")
    production_confirm = LaunchConfiguration("i_confirm_hardware_acceptance_complete")
    head_test_confirm = LaunchConfiguration("i_confirm_head_test_supervised")
    respeaker_transport_kind = LaunchConfiguration("respeaker_transport_kind")
    respeaker_host = LaunchConfiguration("respeaker_host")
    respeaker_user = LaunchConfiguration("respeaker_user")
    respeaker_password = LaunchConfiguration("respeaker_password")
    respeaker_device_name = LaunchConfiguration("respeaker_device_name")
    respeaker_backend_kind = LaunchConfiguration("respeaker_backend_kind")

    nav_share = get_package_share_directory("ihk_pepper_navigation")

    # Entwicklungsauftrag 04-B, AP6: in den vier respeaker_*-Modi
    # verwendet audio_node IMMER source_kind=respeaker_core_v2 -- in
    # jedem anderen (bestehenden) Modus bleibt es exakt der per
    # audio_source_kind gewaehlte Wert, unveraendertes Verhalten.
    resolved_audio_source_kind = PythonExpression([
        "'respeaker_core_v2' if '", mode, f"' in {RESPEAKER_AUDIO_MODES!r} else '",
        audio_source_kind, "'",
    ])

    def _cond(flag_index):
        # PythonExpression, weil die Modus-Auswahl eine reine
        # Zeichenketten-Tabelle ist (siehe _MODE_FLAGS oben) -- kein
        # eigener Launch-Parameter pro Flag noetig, ein Nutzer setzt nur
        # `mode`, alles andere ergibt sich daraus.
        table_repr = repr(_MODE_FLAGS)
        return IfCondition(PythonExpression([
            f"{table_repr}['", mode, f"'][{flag_index}]"
        ]))

    is_dry_bridge = PythonExpression([repr(_MODE_FLAGS), "['", mode, "'][4]"])
    bridge_dry_run_param = PythonExpression(["'true' if ", is_dry_bridge, " else 'false'"])

    ld = [
        DeclareLaunchArgument("mode", default_value="offline_test",
            description=f"Einer von: {', '.join(VALID_MODES)}"),
        DeclareLaunchArgument("motion_capable", default_value="false",
            description="Kill-Switch, siehe SafetyGate. NIE per Default true."),
        DeclareLaunchArgument("enable_live_motion", default_value="false",
            description="Motion-Guard-Freigabe fuer echte Fahrbefehle. NIE per Default true."),
        DeclareLaunchArgument("audio_source_kind", default_value="microphone",
            description="siehe ihk_pepper_audio/audio_source.py"),
        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("database_path", default_value="",
            description="Nur fuer navigation_dry_run/production: Pfad zu einer vorhandenen RTAB-Map-.db-Datei."),
        DeclareLaunchArgument("i_confirm_hardware_acceptance_complete", default_value="false",
            description="NUR fuer mode=production. Siehe docs/NAVIGATION_SAFETY_ACCEPTANCE.md."),
        DeclareLaunchArgument("i_confirm_head_test_supervised", default_value="false",
            description="NUR fuer mode=respeaker_head_test. Siehe docs/RESPEAKER_HARDWARE_ACCEPTANCE.md, Phase C."),
        DeclareLaunchArgument("respeaker_transport_kind", default_value="mock",
            description="mock|local_alsa|ssh_pcm|network_pcm, siehe ihk_pepper_audio/respeaker_transport.py"),
        DeclareLaunchArgument("respeaker_host", default_value=""),
        DeclareLaunchArgument("respeaker_user", default_value=""),
        DeclareLaunchArgument("respeaker_password", default_value=""),
        DeclareLaunchArgument("respeaker_device_name", default_value="seeed-8mic-voicecard"),
        DeclareLaunchArgument("respeaker_backend_kind", default_value="passthrough",
            description="passthrough|gcc_phat, siehe ihk_pepper_audio/directional_audio.py"),

        OpaqueFunction(
            function=_validate_mode_and_guards,
            args=[mode, production_confirm, head_test_confirm]),

        # ---- Immer gestartet (auch in pepper_gesture_test, minimal) ----
        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
            parameters=[{"dry_run": bridge_dry_run_param}],
        ),
        Node(
            package="ihk_pepper_interaction", executable="supervisor_node", output="screen",
            parameters=[{"motion_capable": motion_capable}],
        ),
        Node(
            package="ihk_pepper_interaction", executable="motion_guard_node", output="screen",
            parameters=[{"enable_live_motion": enable_live_motion}],
        ),
        # Entwicklungsauftrag 04-B, AP5B/AP6: bestehender Fund behoben --
        # KEIN Launch-Modus startete bisher den Aktuator-Arbiter, obwohl
        # Say/PlayGesture/SetHeadPose seit AP5B/AP6 zwingend eine Lease
        # von ihm brauchen (ohne ihn erreichbar wuerden ALLE drei
        # Actions mit "actuator_arbiter nicht erreichbar" fehlschlagen).
        Node(
            package="ihk_pepper_interaction", executable="actuator_arbiter_node", output="screen",
        ),

        # ---- Person-Gedaechtnis + der EINE Dialog-Pfad (NICHT
        #      dialog_manager_node -- siehe Moduldoku oben) ----
        Node(
            package="ihk_pepper_person_memory", executable="person_memory_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", mode, "' != 'pepper_gesture_test'"])),
        ),
        Node(
            package="ihk_pepper_dialog", executable="run_dialogue_action_server",
            output="screen",
            # Entwicklungsauftrag 04-B, AP5A: keine expliziten gesture_search.*-
            # Parameter hier -- die Knoten-eigenen Defaults (enabled=true,
            # service_timeout_s=0.75, top_k=5, max_duration_s=6.0,
            # minimum_tested_status_development=dry_run_validated,
            # recent_gesture_window=3) entsprechen bereits der im Auftrag
            # vorgegebenen Beispielkonfiguration. Faellt search_gestures aus
            # (z.B. gesture_memory_node noch nicht bereit) oder ist der
            # Service deaktiviert, spricht Pepper trotzdem ohne Geste
            # weiter (siehe run_dialogue_action_server.py::_search_gestures()).
            condition=IfCondition(PythonExpression(["'", mode, "' != 'pepper_gesture_test'"])),
        ),
        Node(
            package="ihk_pepper_presentation", executable="presentation_manager_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", mode, "' != 'pepper_gesture_test'"])),
        ),
        Node(
            package="ihk_pepper_behavior_tree", executable="bt_executor_node",
            output="screen",
            condition=IfCondition(PythonExpression(["'", mode, "' != 'pepper_gesture_test'"])),
        ),
        # Gesten-Vektordatenbank (Ergaenzungsauftrag 04-A). production_mode
        # nur in mode=production true -- siehe SearchGestures.srv-Doku:
        # damit sind ausserhalb von production auch draft-/dry_run_validated-
        # Gesten suchbar (fuer gesturectl/Entwicklung), production erzwingt
        # live_validated-only unabhaengig davon, was ein einzelner Aufruf anfordert.
        Node(
            package="ihk_pepper_gesture_memory", executable="gesture_memory_node",
            output="screen",
            parameters=[{"production_mode": PythonExpression([
                "'true' if '", mode, "' == 'production' else 'false'"
            ])}],
            condition=IfCondition(PythonExpression(["'", mode, "' != 'pepper_gesture_test'"])),
        ),

        # ---- Perception (alle Modi ausser pepper_gesture_test) ----
        Node(
            package="ihk_pepper_perception", executable="perception_node", output="screen",
            condition=_cond(0),
        ),

        # ---- Audio (microphone_test, navigation_dry_run, production,
        #      und die vier respeaker_*-Modi -- source_kind wird oben
        #      ueber resolved_audio_source_kind aufgeloest) ----
        Node(
            package="ihk_pepper_audio", executable="audio_node", output="screen",
            parameters=[{
                "source_kind": resolved_audio_source_kind,
                "respeaker_transport_kind": respeaker_transport_kind,
                "respeaker_host": respeaker_host,
                "respeaker_user": respeaker_user,
                "respeaker_password": respeaker_password,
                "respeaker_device_name": respeaker_device_name,
                "respeaker_backend_kind": respeaker_backend_kind,
            }],
            condition=_cond(1),
        ),
        # Entwicklungsauftrag 04-B, AP6: laufen nur dort sinnvoll, wo
        # Audio ueberhaupt aktiv ist (gleiche Bedingung wie audio_node).
        Node(
            package="ihk_pepper_audio", executable="audio_focus_node", output="screen",
            condition=_cond(1),
        ),
        Node(
            package="ihk_pepper_interaction", executable="orient_to_sound_node", output="screen",
            condition=_cond(1),
        ),
        Node(
            package="ihk_pepper_perception", executable="audiovisual_association_node",
            output="screen",
            condition=_cond(1),
        ),
    ]

    # ---- Kamera-/Navigationspfad: Mock-Nav (offline_test/
    #      microphone_test/realsense_test) vs. echter Nav2-Stack
    #      (navigation_dry_run/production) ----
    mock_nav_condition = IfCondition(PythonExpression([
        "'", mode, "' in ('offline_test', 'microphone_test', 'realsense_test')"
    ]))
    real_nav_condition = IfCondition(PythonExpression([
        "'", mode, "' in ('navigation_dry_run', 'production')"
    ]))
    real_camera_condition = _cond(2)

    ld += [
        # Mock-Pfad: dieselbe Knotenliste wie offline_test.launch.py.
        Node(
            package="ihk_pepper_navigation", executable="camera_pose_gate_node",
            output="screen", condition=mock_nav_condition,
        ),
        Node(
            package="ihk_pepper_navigation", executable="mock_nav2_server", output="screen",
            condition=mock_nav_condition,
        ),
        Node(
            package="ihk_pepper_navigation", executable="person_approach_node",
            output="screen", condition=mock_nav_condition,
        ),
        Node(
            package="ihk_pepper_navigation", executable="realsense_diagnostics_node",
            output="screen", condition=mock_nav_condition,
        ),
        Node(
            package="ihk_pepper_navigation", executable="odometry_health_node",
            output="screen", condition=mock_nav_condition,
        ),

        # Echte RealSense-Treiber/-TF (realsense_test, navigation_dry_run, production).
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_bringup.launch.py")),
            launch_arguments={"camera_name": camera_name}.items(),
            condition=real_camera_condition,
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_static_tf.launch.py")),
            condition=real_camera_condition,
        ),

        # Echter Nav2-/RTAB-Map-Pfad NUR fuer navigation_dry_run/production
        # -- wiederverwendet dieselben, bereits einzeln gebauten
        # Sub-Launches wie navigation_dry_run.launch.py, statt sie hier
        # zu duplizieren.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_odometry.launch.py")),
            launch_arguments={"camera_name": camera_name}.items(),
            condition=real_nav_condition,
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "realsense_localization.launch.py")),
            launch_arguments={"camera_name": camera_name, "database_path": database_path}.items(),
            condition=real_nav_condition,
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "nav2_bringup.launch.py")),
            launch_arguments={
                "allow_motion": motion_capable,
                # production haengt am ECHTEN /cmd_vel (kein cmd_vel_out_topic-
                # Override); navigation_dry_run bleibt am Sink -- siehe
                # navigation_dry_run.launch.py fuer denselben Mechanismus.
                "cmd_vel_out_topic": PythonExpression([
                    "'/cmd_vel' if '", mode, "' == 'production' else 'navigation_dry_run/cmd_vel_sink'"
                ]),
            }.items(),
            condition=real_nav_condition,
        ),
    ]

    return LaunchDescription(ld)
