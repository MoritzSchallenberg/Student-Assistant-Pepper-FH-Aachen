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

    Entwicklungsauftrag 04-B, AP7, Abschnitt 26/30 (Rollen/Codewoerter/
    Gruppengespraeche/FollowPerson/Lebenszyklus) -- alle vier Modi wie
    offline_test rein softwarebasiert (mock_nav2_server, kein echter
    Pepper, kein Mikrofon-Hardwarezugriff, KEIN echter /cmd_vel):

    role_authorization_offline_test  command_router_node zusaetzlich
                         gestartet (Codewort-/Rollen-Autorisierung),
                         privileged_motion_policy bleibt der
                         Node-Default (role_plus_confirmation) --
                         POLICY_ROLE_ONLY_DEVELOPMENT ist unabhaengig
                         vom Modus in production_mode=true IMMER
                         gesperrt (siehe authorization_policy.py).
    group_interaction_offline_test  zusaetzlich group_tracking_node
                         (stabile Mehrpersonen-Gruppen aus
                         /perception_node/person_tracks) -- audio_focus_node
                         (bereits in jedem audio-aktiven Modus gestartet)
                         nutzt automatisch dessen /perception/
                         conversation_groups, sobald verfuegbar.
    follow_person_dry_run  wie offline_test, zusaetzlich
                         enable_follow_person:=true auf person_approach_node
                         (command_router_node laeuft ohnehin in jedem
                         audio-aktiven Modus mit und stellt die noetige
                         AuthorizationGrant aus) -- faehrt weiterhin nur
                         gegen mock_nav2_server, NIEMALS echten Nav2/Pepper.
    interaction_lifecycle_dry_run  wie offline_test, zusaetzlich
                         command_router_node + group_tracking_node --
                         deckt CaptureOriginPose/ReturnToOriginViaBT/
                         EndInteractionSubtree (Entwicklungsauftrag 04-B,
                         AP7, Commit 9/10) im laufenden Baum ab, ohne
                         echte Bewegung.

    Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20 (Launch-Modi):

    identity_offline_test  wie offline_test, zusaetzlich face_identity_node
                         mit face_detector_kind/identity_backend_kind
                         standardmaessig "mock" (MockFaceDetector, siehe
                         face_detector_backend.py) -- KEINE echte Kamera,
                         KEIN echtes ONNX-Modell noetig. Deckt den
                         RealSense->Track->Face->Identity-Datenfluss
                         strukturell ab, ohne echte Gesichtserkennung.
    authorization_tablet_test  wie offline_test, zusaetzlich
                         command_router_node + face_identity_node (mock) --
                         fuer manuelle Tests der Tablet-Bestaetigungsseite
                         (apps/web/tablet.html) gegen eine echte,
                         laufende ScopedAuthorizationStore-Instanz.
    command_follow_dry_run  Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20:
                         gleichbedeutend mit follow_person_dry_run (AP7) --
                         eigener Modusname fuer AP7.1-Namenskonformitaet,
                         follow_person_dry_run bleibt unveraendert
                         nutzbar (kein Duplikat, dieselbe Konfiguration).
    group_interaction_dry_run  Entwicklungsauftrag 04-B, AP7.1, Abschnitt
                         20: gleichbedeutend mit group_interaction_offline_test
                         (AP7) -- eigener Modusname fuer AP7.1-
                         Namenskonformitaet, dieselbe Konfiguration.

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
from launch.substitutions import LaunchConfiguration, PythonExpression, TextSubstitution
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
    # Entwicklungsauftrag 04-B, AP7, Abschnitt 26/30.
    "role_authorization_offline_test",
    "group_interaction_offline_test",
    "follow_person_dry_run",
    "interaction_lifecycle_dry_run",
    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20.
    "identity_offline_test",
    "authorization_tablet_test",
    "command_follow_dry_run",
    "group_interaction_dry_run",
)

# Entwicklungsauftrag 04-B, AP7: alle acht Testmodi (vier aus AP7, vier
# aus AP7.1) sind rein softwarebasiert wie offline_test -- eigene
# Konstante statt sie an jeder einzelnen Stelle einzeln aufzuzaehlen.
AP7_OFFLINE_TEST_MODES = (
    "role_authorization_offline_test",
    "group_interaction_offline_test",
    "follow_person_dry_run",
    "interaction_lifecycle_dry_run",
    "identity_offline_test",
    "authorization_tablet_test",
    "command_follow_dry_run",
    "group_interaction_dry_run",
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
    # Entwicklungsauftrag 04-B, AP7, Abschnitt 26/30: alle vier wie
    # offline_test (perception+audio aktiv, kein echter Nav2/Kamera,
    # Bridge dry_run) -- die einzelnen Zusatzknoten (command_router_node/
    # group_tracking_node/enable_follow_person) werden weiter unten
    # NICHT ueber diese Tabelle, sondern ueber AP7_OFFLINE_TEST_MODES-
    # spezifische Bedingungen gestartet (siehe dort).
    "role_authorization_offline_test": (True, True, False, False, True),
    "group_interaction_offline_test":  (True, True, False, False, True),
    "follow_person_dry_run":           (True, True, False, False, True),
    "interaction_lifecycle_dry_run":   (True, True, False, False, True),
    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20: gleiche Grund-
    # konfiguration wie die vier AP7-Modi (perception+audio aktiv, kein
    # echter Nav2/Kamera, Bridge dry_run) -- was sie zusaetzlich
    # unterscheidet, wird ueber AP7_OFFLINE_TEST_MODES-spezifische
    # Bedingungen weiter unten gesteuert (face_identity_node,
    # enable_follow_person), nicht ueber diese Tabelle.
    "identity_offline_test":           (True, True, False, False, True),
    "authorization_tablet_test":       (True, True, False, False, True),
    "command_follow_dry_run":          (True, True, False, False, True),
    "group_interaction_dry_run":       (True, True, False, False, True),
}

# Entwicklungsauftrag 04-B, AP8.9, Abschnitt 4 (bestaetigter Fund): die
# Bridge bekam bisher NUR den dry_run-Parameter -- execution_profile
# blieb dadurch IMMER auf seinem sicheren Standard 'offline_mock' stehen
# (siehe bridge_node.py::__init__/gesture_execution_policy.py), egal
# welcher mode gewaehlt wurde. Fuer die VIER Modi mit bridge_dry_run=False
# (production/respeaker_head_test/pepper_gesture_test/navigation_dry_run)
# MUSS jetzt explizit ein hardwarefaehiges Profil gesetzt werden --
# sonst waere z.B. production dauerhaft im NICHT-hardwarefaehigen
# offline_mock-Profil gefangen (siehe
# gesture_execution_policy.py::HARDWARE_CAPABLE_PROFILES), obwohl
# dry_run=False bereits eine echte SSH-Verbindung erlaubt. Jeder andere
# (bridge_dry_run=True) Modus bleibt beim sicheren 'offline_mock'.
_MODE_EXECUTION_PROFILE = {mode_name: "offline_mock" for mode_name in VALID_MODES}
_MODE_EXECUTION_PROFILE.update({
    "production": "production",
    "respeaker_head_test": "supervised_hardware_test",
    "pepper_gesture_test": "supervised_hardware_test",
    "navigation_dry_run": "supervised_hardware_test",
})

# Modi, in denen audio_node source_kind=respeaker_core_v2 verwenden soll
# (statt des per audio_source_kind gewaehlten Werts) -- eigene
# Konstante statt eines weiteren Tabellenindex, damit _MODE_FLAGS bei
# den bereits bestehenden Modi unveraendert bleibt.
RESPEAKER_AUDIO_MODES = (
    "respeaker_offline_test", "respeaker_hardware_test",
    "audio_visual_test", "respeaker_head_test",
)


def _validate_mode_and_guards(
        context, mode_arg, production_confirm_arg, head_test_confirm_arg,
        gesture_test_confirm_arg, *args, **kwargs):
    mode = context.perform_substitution(mode_arg)
    if mode not in VALID_MODES:
        raise RuntimeError(
            f"interaction_full_safe.launch.py: unbekannter mode '{mode}'. "
            f"Erlaubt: {', '.join(VALID_MODES)}."
        )
    # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 6 (bestaetigter Fund):
    # pepper_gesture_test/navigation_dry_run hatten bisher UEBERHAUPT
    # KEINE Bestaetigungshuerde, obwohl beide bridge_dry_run=False setzen
    # (echte SSH-Verbindung, echte Gesten-/Sprachausgabe moeglich) --
    # anders als production/respeaker_head_test, die bereits je eine
    # eigene i_confirm_*-Huerde verlangen. Dieselbe Huerde jetzt auch
    # hier: KEINE echte Sicherheitspruefung, nur ein Schutz gegen
    # versehentliches Copy-Paste eines Launch-Befehls.
    if mode in ("pepper_gesture_test", "navigation_dry_run"):
        if context.perform_substitution(gesture_test_confirm_arg) != "true":
            raise RuntimeError(
                f"interaction_full_safe.launch.py: mode={mode} verlangt "
                "i_confirm_gesture_test_supervised:=true. Dieser Modus startet "
                "die Bridge mit dry_run=false (echte SSH-Verbindung, echte "
                "Say-/PlayGesture-Ausfuehrung moeglich) -- NUR mit einer "
                "Bedienperson direkt am Roboter und physischem Not-Stopp in "
                "Reichweite starten. Keine automatischen Ausloeser (kein "
                "Perception-/Dialog-/BT-Knoten startet in pepper_gesture_test; "
                "in navigation_dry_run bleibt nur Nav2/RealSense-seitig echt, "
                "der /cmd_vel-Ausgang bleibt trotzdem auf einen Sink umgebogen)."
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


def _launch_identity_node(
        context, mode_arg, face_detector_kind_arg, identity_backend_kind_arg,
        model_path_arg, model_checksum_arg, template_store_path_arg,
        registry_db_path_arg, camera_calibration_path_arg, hardware_ready_arg,
        *args, **kwargs):
    """Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20/21: startet
    face_identity_node in jedem Modus mit aktiver Perception (gleiche
    Bedingung wie group_tracking_node), UND erzwingt in mode=production
    zusaetzlich die sieben in production_readiness.py geprueften Gates --
    bei einem nicht bestandenen Gate werden face_detector_kind/
    identity_backend_kind auf "disabled" zurueckgesetzt (identity bleibt
    UNKNOWN, role bleibt STUDENT, siehe role_resolution.py), der
    Systemstart selbst wird NICHT blockiert (ein normales Gespraech
    bleibt moeglich)."""
    mode = context.perform_substitution(mode_arg)
    if not _MODE_FLAGS[mode][0]:  # kein perception in diesem Modus (z.B. pepper_gesture_test)
        return []

    face_detector_kind = context.perform_substitution(face_detector_kind_arg)
    identity_backend_kind = context.perform_substitution(identity_backend_kind_arg)
    actions = []

    if mode == "production":
        from ihk_pepper_identity.production_readiness import check_identity_production_gates

        model_path = context.perform_substitution(model_path_arg)
        template_store_path = context.perform_substitution(template_store_path_arg)

        def _validate_store():
            try:
                from ihk_pepper_identity.biometric_template_store import BiometricTemplateStore
                store = BiometricTemplateStore(template_store_path)
                try:
                    person_ids = store.all_person_ids()
                    return all(store.get_template(pid) is not None for pid in person_ids)
                finally:
                    store.close()
            except Exception:
                return False

        gate = check_identity_production_gates(
            model_path=model_path,
            model_checksum_sha256=context.perform_substitution(model_checksum_arg),
            template_store_path=template_store_path,
            registry_db_path=context.perform_substitution(registry_db_path_arg),
            camera_calibration_path=context.perform_substitution(camera_calibration_path_arg),
            minimum_liveness_valid_samples=20,  # Node-Default, siehe face_identity_node.py
            hardware_approval_confirmed=(
                context.perform_substitution(hardware_ready_arg) == "true"),
            validate_template_store_fn=_validate_store if template_store_path else None,
        )
        if not gate.ok:
            actions.append(LogInfo(msg=(
                "*** mode=production: persistente Gesichtszuordnung GESPERRT "
                f"(Gates nicht erfuellt: {', '.join(gate.reasons)}) -- "
                "identity bleibt UNKNOWN, role bleibt STUDENT. ***"
            )))
            face_detector_kind = "disabled"
            identity_backend_kind = "disabled"

    # TextSubstitution statt roher Python-Strings -- gleiche
    # Normalisierung wie ueberall sonst im Launch-File (PythonExpression/
    # LaunchConfiguration), damit Introspektion ueber
    # perform_substitutions() (siehe test_interaction_full_safe_launch.py)
    # konsistent funktioniert.
    resolved_model_path = context.perform_substitution(model_path_arg)
    actions.append(Node(
        package="ihk_pepper_identity", executable="face_identity_node", output="screen",
        parameters=[{
            "face_detector_kind": TextSubstitution(text=face_detector_kind),
            "identity_backend_kind": TextSubstitution(text=identity_backend_kind),
            "face_detector_model_path": TextSubstitution(text=resolved_model_path),
            "identity_backend_model_path": TextSubstitution(text=resolved_model_path),
            "biometric_db_path": TextSubstitution(
                text=context.perform_substitution(template_store_path_arg)),
            "identity_registry_db_path": TextSubstitution(
                text=context.perform_substitution(registry_db_path_arg)),
        }],
    ))
    return actions


def generate_launch_description():
    mode = LaunchConfiguration("mode")
    motion_capable = LaunchConfiguration("motion_capable")
    enable_live_motion = LaunchConfiguration("enable_live_motion")
    audio_source_kind = LaunchConfiguration("audio_source_kind")
    camera_name = LaunchConfiguration("camera_name")
    database_path = LaunchConfiguration("database_path")
    production_confirm = LaunchConfiguration("i_confirm_hardware_acceptance_complete")
    head_test_confirm = LaunchConfiguration("i_confirm_head_test_supervised")
    gesture_test_confirm = LaunchConfiguration("i_confirm_gesture_test_supervised")
    allow_head_motion = LaunchConfiguration("allow_head_motion")
    allow_arm_motion = LaunchConfiguration("allow_arm_motion")
    allow_torso_motion = LaunchConfiguration("allow_torso_motion")
    respeaker_transport_kind = LaunchConfiguration("respeaker_transport_kind")
    respeaker_host = LaunchConfiguration("respeaker_host")
    respeaker_user = LaunchConfiguration("respeaker_user")
    respeaker_password = LaunchConfiguration("respeaker_password")
    respeaker_device_name = LaunchConfiguration("respeaker_device_name")
    respeaker_backend_kind = LaunchConfiguration("respeaker_backend_kind")
    identity_face_detector_kind = LaunchConfiguration("identity_face_detector_kind")
    identity_backend_kind = LaunchConfiguration("identity_backend_kind")
    identity_model_path = LaunchConfiguration("identity_model_path")
    identity_model_checksum_sha256 = LaunchConfiguration("identity_model_checksum_sha256")
    identity_template_store_path = LaunchConfiguration("identity_template_store_path")
    identity_registry_db_path = LaunchConfiguration("identity_registry_db_path")
    identity_camera_calibration_path = LaunchConfiguration("identity_camera_calibration_path")
    identity_hardware_ready_confirm = LaunchConfiguration("i_confirm_identity_hardware_ready")

    nav_share = get_package_share_directory("ihk_pepper_navigation")

    # Entwicklungsauftrag 04-B, AP6: in den vier respeaker_*-Modi
    # verwendet audio_node IMMER source_kind=respeaker_core_v2 -- in
    # jedem anderen (bestehenden) Modus bleibt es exakt der per
    # audio_source_kind gewaehlte Wert, unveraendertes Verhalten.
    resolved_audio_source_kind = PythonExpression([
        "'respeaker_core_v2' if '", mode, f"' in {RESPEAKER_AUDIO_MODES!r} else '",
        audio_source_kind, "'",
    ])

    # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20: identity_offline_test/
    # authorization_tablet_test wollen den Identitaets-Datenfluss
    # SOFORT sichtbar ausueben, ohne dass ein Nutzer zusaetzlich
    # identity_face_detector_kind:=mock/identity_backend_kind:=mock von
    # Hand setzen muss -- jeder andere Modus bleibt beim per Argument
    # gewaehlten Wert (Standard "disabled").
    _IDENTITY_MOCK_MODES = ("identity_offline_test", "authorization_tablet_test")
    resolved_identity_face_detector_kind = PythonExpression([
        "'mock' if '", mode, f"' in {_IDENTITY_MOCK_MODES!r} else '",
        identity_face_detector_kind, "'",
    ])
    resolved_identity_backend_kind = PythonExpression([
        "'mock' if '", mode, f"' in {_IDENTITY_MOCK_MODES!r} else '",
        identity_backend_kind, "'",
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
    # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 4: siehe
    # _MODE_EXECUTION_PROFILE oben -- die Bridge bekommt jetzt IMMER das
    # zum gewaehlten mode passende execution_profile, nicht mehr nur
    # dry_run.
    execution_profile_param = PythonExpression([
        f"{_MODE_EXECUTION_PROFILE!r}['", mode, "']"
    ])

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
        DeclareLaunchArgument("i_confirm_gesture_test_supervised", default_value="false",
            description="NUR fuer mode=pepper_gesture_test/navigation_dry_run (beide "
                         "bridge_dry_run=false). Siehe docs/GESTURE_HARDWARE_ACCEPTANCE.md."),
        # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 5: getrennte
        # Bewegungsfreigaben je Ressourcengruppe -- WEDER
        # i_confirm_gesture_test_supervised NOCH
        # i_confirm_hardware_acceptance_complete geben allein irgendeine
        # Bewegungsfreigabe ("Ein Bestaetigungsflag allein ersetzt keine
        # Ressourcenfreigabe"). Alle drei bleiben per Default aus, in
        # JEDEM Modus (auch production) -- ein Bediener muss sie
        # zusaetzlich EXPLIZIT setzen. Wirkungslos, solange
        # execution_profile nicht hardwarefaehig ist (offline_mock/
        # offline_preview), siehe bridge_node.py::_resource_motion_denied().
        DeclareLaunchArgument("allow_head_motion", default_value="false",
            description="Bridge-Parameter, siehe docs/GESTURE_HARDWARE_ACCEPTANCE.md."),
        DeclareLaunchArgument("allow_arm_motion", default_value="false",
            description="Bridge-Parameter, siehe docs/GESTURE_HARDWARE_ACCEPTANCE.md."),
        DeclareLaunchArgument("allow_torso_motion", default_value="false",
            description="Bridge-Parameter, siehe docs/GESTURE_HARDWARE_ACCEPTANCE.md."),
        DeclareLaunchArgument("respeaker_transport_kind", default_value="mock",
            description="mock|local_alsa|ssh_pcm|network_pcm, siehe ihk_pepper_audio/respeaker_transport.py"),
        DeclareLaunchArgument("respeaker_host", default_value=""),
        DeclareLaunchArgument("respeaker_user", default_value=""),
        DeclareLaunchArgument("respeaker_password", default_value=""),
        DeclareLaunchArgument("respeaker_device_name", default_value="seeed-8mic-voicecard"),
        DeclareLaunchArgument("respeaker_backend_kind", default_value="passthrough",
            description="passthrough|gcc_phat, siehe ihk_pepper_audio/directional_audio.py"),

        # Entwicklungsauftrag 04-B, AP7.1, Abschnitt 20/21: face_identity_node.
        # Default bleibt ueberall "disabled" (sicherer Ausgangszustand,
        # identity bleibt UNKNOWN/role bleibt STUDENT, siehe
        # role_resolution.py) -- identity_offline_test setzt "mock" per
        # eigener PythonExpression unten, mode=production erzwingt
        # zusaetzlich die in production_readiness.py geprueften Gates.
        DeclareLaunchArgument("identity_face_detector_kind", default_value="disabled",
            description="disabled|mock|local_onnx, siehe face_detector_backend.py"),
        DeclareLaunchArgument("identity_backend_kind", default_value="disabled",
            description="disabled|mock|local_embedding, siehe face_identity_backend.py"),
        DeclareLaunchArgument("identity_model_path", default_value=""),
        DeclareLaunchArgument("identity_model_checksum_sha256", default_value=""),
        DeclareLaunchArgument("identity_template_store_path", default_value=""),
        DeclareLaunchArgument("identity_registry_db_path", default_value=""),
        DeclareLaunchArgument("identity_camera_calibration_path", default_value=""),
        DeclareLaunchArgument("i_confirm_identity_hardware_ready", default_value="false",
            description="NUR fuer mode=production, siehe production_readiness.py "
                         "(Hardwarefreigabe ist EINES von sieben Gates, kein Ersatz "
                         "fuer die anderen sechs)."),

        OpaqueFunction(
            function=_validate_mode_and_guards,
            args=[mode, production_confirm, head_test_confirm, gesture_test_confirm]),
        OpaqueFunction(
            function=_launch_identity_node,
            args=[
                mode, resolved_identity_face_detector_kind, resolved_identity_backend_kind,
                identity_model_path, identity_model_checksum_sha256,
                identity_template_store_path, identity_registry_db_path,
                identity_camera_calibration_path, identity_hardware_ready_confirm,
            ]),

        # ---- Immer gestartet (auch in pepper_gesture_test, minimal) ----
        Node(
            package="ihk_pepper_bridge", executable="bridge_node",
            namespace="pepper_bridge", output="screen",
            parameters=[{
                "dry_run": bridge_dry_run_param,
                "execution_profile": execution_profile_param,
                "allow_head_motion": allow_head_motion,
                "allow_arm_motion": allow_arm_motion,
                "allow_torso_motion": allow_torso_motion,
            }],
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
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 26/30: stabile
        # Mehrpersonen-Gruppen aus /perception_node/person_tracks (+
        # /audio/focus_state, falls Audio in diesem Modus aktiv ist) --
        # gleiche Bedingung wie perception_node selbst, laeuft in JEDEM
        # Modus mit, in dem ueberhaupt Personentracks existieren (nicht
        # nur in group_interaction_offline_test -- kein Grund, es dort
        # exklusiv zu sperren).
        Node(
            package="ihk_pepper_perception", executable="group_tracking_node",
            output="screen", condition=_cond(0),
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
                # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 7/13: bestaetigter
                # Fund -- ohne diese Zeile blieb production_mode IMMER beim
                # Node-internen Default (false), auch in mode=production. Die
                # in Commit 1/5 eingefuehrten Start-Guards (continuous_development/
                # allow_ambiguous_direction_for_head_orientation in Produktion
                # gesperrt) haetten dadurch in der echten production-Launch NIE
                # gegriffen. Gleiches Muster wie gesture_memory_node oben.
                "production_mode": PythonExpression([
                    "'true' if '", mode, "' == 'production' else 'false'"
                ]),
            }],
            condition=_cond(1),
        ),
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.1/4/12: EINZIGER
        # Publisher der kanonischen /audio/sound_direction(+_event)-Topics
        # -- transformiert audio_node.py's RAW-Topics (_raw-Suffix, immer
        # frame_id=respeaker_link) nach base_link. Gleiche Bedingung wie
        # audio_node (laeuft harmlos mit, auch wenn die aktive Audioquelle
        # in diesem Modus gar keine Richtung schaetzt -- dann kommen
        # einfach nie RAW-Nachrichten an).
        Node(
            package="ihk_pepper_audio", executable="sound_direction_transform_node",
            output="screen",
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
        # Entwicklungsauftrag 04-B, AP7, Abschnitt 8/9/19: deterministischer
        # Codewort-/Privilegierte-Befehl-Router -- braucht das kanonische
        # /interaction/command-Topic aus sound_direction_transform_node,
        # also dieselbe Bedingung wie Audio insgesamt. production_mode
        # bleibt Node-Default (false) -- POLICY_ROLE_ONLY_DEVELOPMENT ist
        # in production_mode=true ohnehin fail-closed gesperrt (siehe
        # authorization_policy.py), kein separates Launch-Flag noetig.
        Node(
            package="ihk_pepper_interaction", executable="command_router_node",
            output="screen",
            parameters=[{
                "production_mode": PythonExpression([
                    "'true' if '", mode, "' == 'production' else 'false'"
                ]),
            }],
            condition=_cond(1),
        ),
    ]

    # ---- Kamera-/Navigationspfad: Mock-Nav (offline_test/
    #      microphone_test/realsense_test) vs. echter Nav2-Stack
    #      (navigation_dry_run/production) ----
    mock_nav_condition = IfCondition(PythonExpression([
        "'", mode, f"' in ('offline_test', 'microphone_test', 'realsense_test') or ('",
        mode, f"' in {AP7_OFFLINE_TEST_MODES!r})",
    ]))
    real_nav_condition = IfCondition(PythonExpression([
        "'", mode, "' in ('navigation_dry_run', 'production')"
    ]))
    real_camera_condition = _cond(2)

    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: robot_state_publisher
    # (pepper_robot_state.launch.py) wird gebraucht, sobald IRGENDEIN
    # kopfmontierter Sensor eine TF-Kette unter "Head" braucht -- das ist
    # real_camera_condition (RealSense) ODER einer der vier respeaker_*-
    # Modi (ReSpeaker, auch wenn real_camera in diesem Modus False ist,
    # z.B. respeaker_offline_test/respeaker_hardware_test/
    # respeaker_head_test). respeaker_static_tf.launch.py selbst braucht
    # nur die respeaker_audio_condition (ReSpeaker-Montage-TF ist
    # unabhaengig von der Kamera).
    respeaker_audio_condition = IfCondition(PythonExpression([
        "'", mode, f"' in {RESPEAKER_AUDIO_MODES!r}"
    ]))
    robot_state_condition = IfCondition(PythonExpression([
        f"({repr(_MODE_FLAGS)}['", mode, f"'][2]) or ('", mode,
        f"' in {RESPEAKER_AUDIO_MODES!r})",
    ]))

    ld += [
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: dynamische
        # base_link->torso->Neck->Head-Kette (aus /joint_states, siehe
        # bridge_node.py::_publish_joint_states) -- Voraussetzung fuer
        # realsense_static_tf.launch.py/respeaker_static_tf.launch.py,
        # deren parent_frame jetzt "Head" statt "base_link" ist. Braucht
        # zusaetzlich zu autonomy_ws den separaten robot_model-Workspace
        # gesourct (siehe pepper_robot_state.launch.py-Docstring).
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "pepper_robot_state.launch.py")),
            condition=robot_state_condition,
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_share, "launch", "respeaker_static_tf.launch.py")),
            condition=respeaker_audio_condition,
        ),
    ]

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
            parameters=[{
                # Entwicklungsauftrag 04-B, AP7, Abschnitt 19/26: NUR in
                # follow_person_dry_run/command_follow_dry_run (AP7.1,
                # Abschnitt 20 -- derselbe Modus, zweiter Name) scharf --
                # jeder andere Modus bleibt beim sicheren Node-Default
                # (false).
                "enable_follow_person": PythonExpression([
                    "'true' if '", mode,
                    "' in ('follow_person_dry_run', 'command_follow_dry_run') else 'false'"
                ]),
            }],
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
