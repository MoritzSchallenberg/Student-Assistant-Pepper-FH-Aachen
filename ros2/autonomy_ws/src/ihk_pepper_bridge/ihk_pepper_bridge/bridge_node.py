#!/usr/bin/env python3
"""
ihk_pepper_bridge: kapselt die vorhandenen qicli-Faehigkeiten (SSH) als
ROS2-Node -- Actions fuer lang laufende Dinge (Sprechen, Gesten), Topics
fuer Status (Akku, Touch, Autonomous-Life).

Getestet (2026-08-19): NUR mit Pepper nicht angeschlossen, d.h. Action-
Server/Struktur/Gesten-Validierung wurden verifiziert, die tatsaechliche
SSH-Kommunikation mit dem echten Roboter NICHT live in dieser Session
(siehe docs/IMPLEMENTATION_REPORT.md).
"""
import os
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from std_msgs.msg import String, Bool, Float32, UInt8
from sensor_msgs.msg import JointState
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_interfaces.action import Say, PlayGesture, SetHeadPose
from ihk_pepper_interfaces.msg import ActuatorLease, SafetyState, SystemHealth
from ihk_pepper_interfaces.srv import AcquireActuatorLease, ReleaseActuatorLease

from ihk_pepper_interaction.actuator_arbiter import HEAD, PRIORITY_ATTRACT, PRIORITY_DIALOGUE
from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interaction.resource_derivation import resources_for_gesture, resources_for_speech

from .pepper_client import PepperInterruptChannel, ThreadSafePepperClient
from .gesture_catalog import GestureCatalog, GestureValidationError
from .gesture_cancellation import CancelSignal, GestureCancelReason
from .gesture_execution_policy import (
    HARDWARE_CAPABLE_PROFILES,
    VALID_EXECUTION_PROFILES,
    GestureExecutionPolicy,
    PROFILE_OFFLINE_MOCK,
    PROFILE_PRODUCTION,
    RuntimeContext,
)
from .joint_limits import validate_angle_with_margin
from .tts_guard import TtsTextRejected, validate_tts_text
from . import safety_topics


def _default_gesture_dir():
    # Installierter Fall (ros2 run/launch): Daten liegen im share/-Ordner,
    # siehe setup.py data_files. Fallback aufs Source-Layout, falls jemand
    # das Modul direkt aus dem src/-Baum importiert (z.B. in Tests).
    try:
        return os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "gestures"
        )


DEFAULT_GESTURE_DIR = _default_gesture_dir()

# Entwicklungsauftrag 04-B, AP5B: Poll-Intervalle/Wartezeiten fuer die
# Cancel-Beobachtung waehrend Say/PlayGesture -- kein unbegrenztes
# Blockieren mehr (siehe Abschnitt 2.1/2.2).
SAY_POLL_INTERVAL_S = 0.1
SAY_CANCEL_GRACE_S = 1.0
GESTURE_POLL_INTERVAL_S = 0.1
GESTURE_CANCEL_GRACE_S = 2.0
# Entwicklungsauftrag 04-B, AP8-R1.3 (bestaetigter Fund 3.3): max_duration_s
# begrenzte bisher nur die KOMPILIERTE Solltrajektorie -- eine tatsaechlich
# haengende Transportausfuehrung (z.B. eine SSH-Verbindung, die nie
# zurueckkehrt) wurde dadurch NICHT zuverlaessig abgebrochen. Der
# Laufzeit-Watchdog nutzt die bereits POLICY-validierte expected_duration_s
# (aus der zweiten Autorisierungspruefung) plus diese Marge als HARTEN,
# absoluten Zeitdeckel -- kein neuer, unbelegter Grenzwert, nur ein
# dokumentierter Sicherheitsaufschlag auf eine bereits gepruefte Dauer.
GESTURE_WATCHDOG_TIMEOUT_MARGIN_S = 5.0
OWNER_ID = "pepper_bridge"

# Entwicklungsauftrag 04-B, AP8-R1.3: uebersetzt einen GestureExecutionPolicy-
# reason_code (Laufzeitkontext-Ablehnung waehrend des Watchdog-Polls, siehe
# PepperBridgeNode._watchdog_check()) in den passenden strukturierten
# GestureCancelReason. "safety_state_ungueltig_oder_unbekannt" fehlt hier
# ABSICHTLICH -- der wird ueber _classify_safety_cancel_reason() feiner in
# EMERGENCY_STOP/BUMPER_ACTIVE/SAFETY_INVALID aufgeschluesselt.
_POLICY_REJECTION_TO_CANCEL_REASON = {
    "pepper_nicht_erreichbar": GestureCancelReason.PEPPER_UNREACHABLE,
    "nav2_moving_unklar_oder_aktiv": GestureCancelReason.NAVIGATION_STARTED,
    "mapping_unklar_oder_aktiv": GestureCancelReason.MAPPING_STARTED,
    "interaktionszustand_unzulaessig": GestureCancelReason.INTERACTION_INVALID,
    "lease_widerrufen": GestureCancelReason.LEASE_REVOKED,
}

# Entwicklungsauftrag 04-B, AP6, Abschnitt 7/12: SetHeadPose ist der
# sichere Hardware-Grenzpunkt fuer JEDE Kopfbewegung -- konservative
# operative Grenzen ENGER als die vollen Gelenkgrenzen aus
# joint_limits.py (JOINT_LIMITS["HeadYaw"]=(-2.0857, 2.0857),
# ["HeadPitch"]=(-0.7068, 0.4451)). Werte sind ein bewusst vorsichtiger
# Startpunkt, keine kalibrierte Endgrenze -- siehe
# docs/RESPEAKER_CALIBRATION.md.
HEAD_YAW_OPERATIONAL_MIN_RAD = -1.2
HEAD_YAW_OPERATIONAL_MAX_RAD = 1.2
HEAD_PITCH_OPERATIONAL_MIN_RAD = -0.3
HEAD_PITCH_OPERATIONAL_MAX_RAD = 0.2
HEAD_MOVE_BASE_DURATION_S = 1.5
HEAD_POLL_INTERVAL_S = 0.1
HEAD_CANCEL_GRACE_S = 1.0
HEAD_LEASE_TTL_S = 10.0


class PepperBridgeNode(Node):
    def __init__(self):
        super().__init__("pepper_bridge")
        # Entwicklungsauftrag 04-B, AP8-R1.3: node-lokales Shutdown-Flag
        # fuer den Laufzeit-Watchdog (siehe _watchdog_check()/
        # destroy_node()) -- bewusst NICHT rclpy.ok() (das ist global fuer
        # den gesamten Prozess und in jedem Unit-Test ohne rclpy.init()
        # bereits False).
        self._shutting_down = False

        self.declare_parameter("gesture_dir", DEFAULT_GESTURE_DIR)
        self.declare_parameter("health_publish_interval_s", 5.0)
        # Entwicklungsauftrag 1, Abschnitt 12: erlaubt offline_test/
        # navigation_dry_run, den kompletten Behavior-Tree-Ablauf bis
        # CONVERSATION_READY zu durchlaufen, OHNE eine echte SSH-
        # Verbindung zu Pepper zu brauchen -- Say/PlayGesture melden
        # sofort Erfolg, OHNE pepper_client anzufassen. Siehe
        # gesture_catalog.py::play(dry_run=...), das dieselbe Idee schon
        # fuer die reine Katalog-Logik hatte.
        self.declare_parameter("dry_run", False)
        if self.get_parameter("dry_run").value:
            self.get_logger().warn(
                "pepper_bridge im dry_run-Modus -- KEINE echte SSH-Verbindung zu Pepper, "
                "Say/PlayGesture melden sofort Erfolg ohne jede Hardwareaktion."
            )

        # Entwicklungsauftrag 04-B, AP8.1: execution_profile ist die
        # AUTORITATIVE Ausfuehrungsgrenze fuer Gesten -- unabhaengig vom
        # bereits bestehenden dry_run-Parameter (der nur SSH/qicli
        # global an-/ausschaltet, aber nichts ueber tested_status weiss).
        # Sicherer Default "offline_mock": auch ein Bridge-Start OHNE
        # explizites Launch-Argument beruehrt damit NIE Hardware, selbst
        # wenn dry_run versehentlich auf False stuende (Verteidigung in
        # der Tiefe, siehe _execute_gesture()).
        self.declare_parameter("execution_profile", PROFILE_OFFLINE_MOCK)
        execution_profile = self.get_parameter("execution_profile").value
        if execution_profile not in VALID_EXECUTION_PROFILES:
            raise ValueError(
                f"pepper_bridge: unbekanntes execution_profile '{execution_profile}' "
                f"(erlaubt: {VALID_EXECUTION_PROFILES})"
            )
        self.gesture_policy = GestureExecutionPolicy()
        # Entwicklungsauftrag 04-B, AP8-R1.8: austauschbarer Erweiterungs-
        # punkt fuer ein spaeteres ECHTES Kollisions-Backend -- None
        # (Standard) laesst GestureCatalog.play()/_play_v2() ihre eigene
        # Standard-TrajectorySafetyValidator()-Instanz bauen (Joint-
        # AndTimingValidator + DisabledCollisionBackend, siehe
        # trajectory_safety.py). Sobald ein reproduzierbar lauffaehiges
        # Kollisions-Backend existiert, kann es HIER gesetzt werden, ohne
        # gesture_catalog.py/bridge_node.py sonst zu aendern.
        self.gesture_safety_validator = None

        gesture_dir = self.get_parameter("gesture_dir").value
        self.catalog = GestureCatalog(gesture_dir)
        for e in self.catalog.reload():
            self.get_logger().error(f"Geste ungueltig, uebersprungen: {e}")
        self.get_logger().info(
            f"Gesten-Katalog geladen aus {gesture_dir}: {self.catalog.names()}"
        )

        self.pepper = ThreadSafePepperClient()
        # Entwicklungsauftrag 04-B, AP5B, Abschnitt 2.3/10: unabhaengiger
        # zweiter SSH-Kanal AUSSCHLIESSLICH fuer Abbruchbefehle -- teilt
        # sich nie den Lock des Hauptkanals, blockiert also nie hinter
        # einem lange laufenden TTS-/Trajektorienaufruf. Lazy Verbindung
        # (siehe PepperInterruptChannel), kein Zusatzaufwand, solange nie
        # abgebrochen wird.
        self.interrupt_channel = PepperInterruptChannel()

        cb_group = ReentrantCallbackGroup()

        # Entwicklungsauftrag 04-B, AP5B: Service-Clients zum zentralen
        # Aktuator-Arbiter -- jede Say-/PlayGesture-Ausfuehrung MUSS erst
        # eine Lease erhalten, bevor irgendeine Hardwareaktion angestossen
        # wird (siehe _acquire_lease()/_release_lease() unten).
        self.acquire_lease_client = self.create_client(
            AcquireActuatorLease, "/actuator_arbiter/acquire", callback_group=cb_group)
        self.release_lease_client = self.create_client(
            ReleaseActuatorLease, "/actuator_arbiter/release", callback_group=cb_group)

        self._say_active = threading.Event()

        # Fuer den Halbduplex-Controller in ihk_pepper_audio: solange
        # Pepper spricht, soll die Audio-Pipeline nicht gleichzeitig
        # zuhoeren (sonst transkribiert er sich selbst).
        self.speaking_pub = self.create_publisher(Bool, "speaking", 10)

        # Entwicklungsauftrag 04-B, AP8.2: Freshness-Parameter fuer JEDEN
        # sicherheitsrelevanten Laufzeitzustand einzeln (Auftrag Abschnitt
        # 6) -- dieselbe FreshBool/FreshValue-Hilfslogik wie an jeder
        # anderen Stelle im Projekt (safety_topics.py, ABSICHTLICH
        # identische Kopie in drei Paketen, siehe dessen Moduldoku).
        self.declare_parameter("safety_state_max_age_s", 2.0)
        self.declare_parameter("nav2_moving_max_age_s", 2.0)
        self.declare_parameter("mapping_active_max_age_s", 2.0)
        self.declare_parameter("interaction_state_max_age_s", 2.0)
        # health_publish_interval_s ist bereits oben deklariert -- die
        # Reichweite-Pruefung selbst laeuft periodisch dort mit
        # (_publish_health(), siehe unten), pepper_reachable_max_age_s
        # muss daher GROESSER als dieses Intervall sein, sonst waere der
        # Wert strukturell nie "frisch".
        self.declare_parameter("pepper_reachable_max_age_s", 12.0)

        # Entwicklungsauftrag 2, AP10 / AP8.2 (bestaetigter, korrigierter
        # Fund, siehe DEVELOPMENT_ORDER_04_B_REPORT.md AP8 Commit 1/11):
        # der bisherige nackte Bool-Default war "False" (= "bewegt sich
        # NICHT"), bis das Topic je empfangen wurde -- das ist GENAU die
        # FALSCHE fail-closed-Richtung (Auftrag Abschnitt 6: "nav2_moving
        # fehlt/veraltet -> ALS BEWEGUNG BEHANDELN"). FreshBool(True)
        # macht daraus den sicheren Ausweichwert: ohne (frische) Nachricht
        # gilt Pepper als "bewegt sich", stationaere Gesten bleiben
        # gesperrt.
        self._nav2_moving_fresh = safety_topics.FreshBool(True)
        self._nav2_moving = True  # Rueckwaertskompatibel fuer _on_nav2_moving()-Leser unten
        self.create_subscription(Bool, "/nav2_moving", self._on_nav2_moving, 10)

        # SafetyState fehlt/veraltet -> jede Hardwaregeste sperren
        # (Auftrag Abschnitt 6) -- Ausweichwert False ("nicht ok").
        self._safety_ok_fresh = safety_topics.FreshBool(False)
        # Entwicklungsauftrag 04-B, AP8-R1.3/1.4: die ROHEN Einzelfelder
        # (nicht nur das abgeleitete safety_ok) werden zusaetzlich
        # gehalten, damit der Laufzeit-Watchdog einen Abbruch als
        # EMERGENCY_STOP/BUMPER_ACTIVE (statt nur generisch
        # SAFETY_INVALID) klassifizieren kann -- siehe
        # _classify_safety_cancel_reason().
        self._last_emergency_stop = None
        self._last_bumper_active = None
        self.create_subscription(
            SafetyState, safety_topics.SAFETY_STATE_TOPIC, self._on_safety_state_for_gestures, 10)

        # mapping_active fehlt/veraltet -> Kopfgesten sperren -- Ausweichwert
        # True ("Mapping koennte aktiv sein").
        self._mapping_active_fresh = safety_topics.FreshBool(True)
        self.create_subscription(
            Bool, safety_topics.MAPPING_ACTIVE_TOPIC, self._on_mapping_active, 10)

        # current_interaction_state fehlt/veraltet -> Gesten mit
        # Zustands-Allowlist sperren -- Ausweichwert None ("unbekannt",
        # RuntimeContext behandelt das bereits wie einen unzulaessigen
        # Zustand, siehe gesture_execution_policy.py).
        self._interaction_state_fresh = safety_topics.FreshValue(None)
        self.create_subscription(
            UInt8, safety_topics.INTERACTION_STATE_TOPIC, self._on_interaction_state, 10)

        # Pepper nicht erreichbar -> Hardwaregeste sperren -- wiederverwendet
        # DENSELBEN periodischen Erreichbarkeits-Check wie _publish_health()
        # (siehe dort), statt einen zweiten, blockierenden Netzwerk-Check
        # im Gesten-Ausfuehrungspfad selbst einzufuegen.
        self._pepper_reachable_fresh = safety_topics.FreshBool(False)

        # Entwicklungsauftrag 04-B, AP8.3: verbindet einen Lease-Widerruf
        # tatsaechlich mit dem exakt betroffenen laufenden Ziel (bisher
        # nur ueber periodisches Abfragen von ~/state theoretisch
        # erkennbar, siehe DEVELOPMENT_ORDER_04_B_REPORT.md AP8 Commit
        # 1/11, Abschnitt 3.5). _active_gesture_cancel_events bindet
        # lease_id -> dasselbe threading.Event, das die laufende Geste
        # ohnehin schon beobachtet (cancel_event in _execute_gesture()) --
        # ein Widerruf setzt es GENAU wie ein normales Action-Cancel,
        # nutzt also den bereits bestehenden Abbruchpfad, keinen zweiten.
        # _revoked_lease_ids faengt zusaetzlich den kurzen Zeitraum ab,
        # in dem eine Lease ZWISCHEN Erwerb und der zweiten
        # Autorisierungspruefung widerrufen wird (bevor der Eintrag in
        # _active_gesture_cancel_events ueberhaupt existiert).
        #
        # Entwicklungsauftrag 04-B, AP8-R1.7 (bestaetigter Fund 3.8,
        # 'Lease-Revocation-Race'): registrieren/lesen/loeschen dieser drei
        # Strukturen laeuft jetzt IMMER unter _active_execution_lock --
        # _on_lease_revoked() (laeuft auf dem ROS-Subscription-Thread) und
        # _execute_gesture() (Action-Thread) griffen vorher OHNE
        # gemeinsamen Lock auf dieselben dicts/sets zu, wodurch ein
        # Widerruf GENAU zwischen Lease-Erwerb und Registrierung des
        # cancel_event unbemerkt verpuffen konnte (die Lease-ID wurde zwar
        # in _revoked_lease_ids gespeichert, aber nie erneut geprueft,
        # bevor der Transport startete). _quarantined_lease_ids (AP8-R1.6):
        # eine Lease, deren Hintergrund-Thread die Cancel-Grace-Zeit
        # ueberschritten hat, darf auch bei einem VERSPAETETEN
        # on_cancel='restore'-Abschluss KEINE Restore-Trajektorie mehr
        # ausloesen (die Action wurde bereits als 'cancel_unconfirmed'
        # zurueckgegeben).
        self._active_execution_lock = threading.Lock()
        self._active_gesture_cancel_events: dict = {}
        self._revoked_lease_ids: set = set()
        self._quarantined_lease_ids: set = set()
        self.create_subscription(
            ActuatorLease, "/actuator_arbiter/lease_revoked", self._on_lease_revoked, 10)

        self.say_action_server = ActionServer(
            self, Say, "say",
            execute_callback=self._execute_say,
            goal_callback=self._goal_callback_say,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )
        self.gesture_action_server = ActionServer(
            self, PlayGesture, "play_gesture",
            execute_callback=self._execute_gesture,
            goal_callback=self._goal_callback_gesture,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )
        self.set_head_pose_action_server = ActionServer(
            self, SetHeadPose, "set_head_pose",
            execute_callback=self._execute_set_head_pose,
            goal_callback=self._goal_callback_set_head_pose,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )

        self.health_pub = self.create_publisher(SystemHealth, "system_health", 10)
        interval = self.get_parameter("health_publish_interval_s").value
        self.create_timer(interval, self._publish_health)

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: robot_state_publisher
        # (siehe pepper_robot_state.launch.py) braucht /joint_states, um die
        # dynamische Kette base_link->torso->Neck->Head zu berechnen --
        # camera_pose_gate_node.py/head_pose_gate.py haben /joint_states
        # bereits seit Auftrag 1 konsumiert (fail-closed bei fehlend/
        # veraltet), aber VOR AP6.1 hat es in autonomy_ws nie einen
        # tatsaechlichen Publisher dafuer gegeben -- head_navigation_pose_valid
        # war dadurch in jedem echten Einsatz vermutlich immer False. Dieselbe
        # Taktrate wie system_health (kein eigener Parameter noetig, das
        # Gelenk aendert sich nicht schneller als die Health-Schleife
        # sinnvoll aufloest).
        self.joint_states_pub = self.create_publisher(JointState, "/joint_states", 10)

        # Entwicklungsauftrag 4, AP4 / Entwicklungsauftrag 04-B, AP2: reale
        # Statustopics statt Platzhalter. Alle unter dem eigenen Node-
        # Namespace (pepper_bridge/...) -- Namen jetzt aus der
        # gemeinsamen safety_topics.py-Konstantendatei (04-B: "zentrale,
        # dokumentierte Topic-Liste... vermeide leicht abweichende Namen
        # in mehreren Paketen") statt lokaler String-Literale, die von
        # den Abonnenten (Supervisor/Motion Guard) unabhaengig
        # nachgetippt werden mussten -- genau DAS ist bei
        # gesture_in_progress bereits einmal auseinandergedriftet (siehe
        # safety_topics.py-Docstring: motion_guard_node.py abonnierte
        # bisher "/gesture_in_progress" ohne Namespace-Praefix und hat
        # dieses Topic dadurch NIE empfangen).
        self.bumper_pub = self.create_publisher(Bool, safety_topics.BUMPER_TOPIC_RELATIVE, 10)
        self.charging_state_pub = self.create_publisher(
            Bool, safety_topics.CHARGING_STATE_TOPIC_RELATIVE, 10)
        self.battery_pub = self.create_publisher(Float32, safety_topics.BATTERY_TOPIC_RELATIVE, 10)
        self.connection_state_pub = self.create_publisher(
            String, safety_topics.CONNECTION_STATE_TOPIC_RELATIVE, 10)
        self.gesture_in_progress_pub = self.create_publisher(
            Bool, safety_topics.GESTURE_IN_PROGRESS_TOPIC_RELATIVE, 10)

        self.get_logger().info("pepper_bridge Node gestartet.")

    # ---- Aktuator-Arbiter (Entwicklungsauftrag 04-B, AP5B) ----

    def _acquire_lease(self, resources, purpose: str, goal_id: str, ttl_s: float,
                        priority: int = PRIORITY_DIALOGUE):
        """Gibt (granted, lease_id, reason) zurueck. Fail-closed: ein
        nicht erreichbarer/nicht antwortender Arbiter gewaehrt NIE
        stillschweigend eine Aktuation. priority (Entwicklungsauftrag
        04-B, AP6): Say/PlayGesture bleiben bei PRIORITY_DIALOGUE (Default,
        unveraendert), SetHeadPose nutzt PRIORITY_ATTRACT (siehe Auftrag
        Abschnitt 12: "im Idle-Modus Prioritaet ATTRACT")."""
        if not self.acquire_lease_client.wait_for_service(timeout_sec=1.0):
            return False, "", "actuator_arbiter nicht erreichbar"
        req = AcquireActuatorLease.Request()
        req.owner_id = OWNER_ID
        req.resources = sorted(resources)
        req.purpose = purpose
        req.priority = priority
        req.ttl_s = ttl_s
        req.goal_id = goal_id
        future = self.acquire_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "", "actuator_arbiter Zeitueberschreitung"
        try:
            response = future.result()
        except Exception as e:
            return False, "", f"actuator_arbiter Fehler: {e}"
        return response.granted, response.lease_id, response.reason

    def _release_lease(self, lease_id: str):
        if not lease_id:
            return
        if not self.release_lease_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(
                f"Lease '{lease_id}' konnte nicht freigegeben werden (Arbiter nicht erreichbar).")
            return
        req = ReleaseActuatorLease.Request()
        req.lease_id = lease_id
        future = self.release_lease_client.call_async(req)
        deadline = time.time() + 1.5
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)

    @staticmethod
    def _goal_id_str(goal_handle) -> str:
        try:
            return str(bytes(goal_handle.goal_id.uuid))
        except Exception:
            return ""

    # ---- Say ----

    def _goal_callback_say(self, goal_request):
        if not goal_request.text.strip():
            self.get_logger().warn("Say-Ziel mit leerem Text abgelehnt")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute_say(self, goal_handle):
        """Entwicklungsauftrag 04-B, AP5B, Abschnitt 9/12: Text wird an
        DIESER Grenze nochmal validiert (Abschnitt 9.2, unabhaengig von
        einer bereits erfolgten Bereinigung im Dialogserver), die
        eigentliche TTS-Ausgabe laeuft in einem Hintergrund-Thread, damit
        goal_handle.is_cancel_requested/max_duration_s waehrend des
        Sprechens tatsaechlich beobachtet werden (vorher: blockierender
        Aufruf ohne jede Cancel-Beobachtung). SPEECH-Lease wird VOR jeder
        Hardwareaktion angefordert und in JEDEM Endpfad freigegeben."""
        result = Say.Result()
        try:
            text = validate_tts_text(goal_handle.request.text)
        except TtsTextRejected as e:
            self.get_logger().warn(f"Say abgelehnt (Textpruefung an der Bridge-Grenze): {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
            return result

        allow_interrupt = goal_handle.request.allow_interrupt
        max_duration_s = goal_handle.request.max_duration_s or None
        goal_id = self._goal_id_str(goal_handle)

        granted, lease_id, reason = self._acquire_lease(
            resources_for_speech(), purpose="say", goal_id=goal_id,
            ttl_s=(max_duration_s or 30.0) + 10.0,
        )
        if not granted:
            self.get_logger().warn(f"Say abgelehnt (Aktuator-Arbiter): {reason}")
            result.success = False
            result.error_message = f"Ressourcenkonflikt: {reason}"
            goal_handle.abort()
            return result

        feedback = Say.Feedback()
        feedback.status = "speaking"
        goal_handle.publish_feedback(feedback)

        self._say_active.set()
        self.speaking_pub.publish(Bool(data=True))

        done_event = threading.Event()
        outcome = {"error": None}

        def _run():
            try:
                if not self.get_parameter("dry_run").value:
                    self.pepper.say_text_only(text)
            except Exception as e:  # noqa: BLE001
                outcome["error"] = e
            finally:
                done_event.set()

        thread = threading.Thread(target=_run, daemon=True)
        t0 = time.time()
        thread.start()

        final_state = "SUCCEEDED"
        try:
            while not done_event.wait(timeout=SAY_POLL_INTERVAL_S):
                elapsed = time.time() - t0
                timed_out = max_duration_s is not None and elapsed > max_duration_s
                # Safety-/Nutzer-Stopp bleiben unabhaengig von
                # allow_interrupt wirksam (Abschnitt 9.3) -- ein echter
                # Not-Stopp/Bumper laeuft ueber
                # actuator_arbiter::emergency_revoke_all() und entzieht
                # die Lease bereits arbiterseitig; ein normaler
                # ROS2-Cancel respektiert allow_interrupt=False.
                user_cancel = goal_handle.is_cancel_requested and allow_interrupt
                if not (timed_out or user_cancel):
                    continue
                reason_text = "max_duration_s ueberschritten" if timed_out else "abgebrochen"
                self.get_logger().info(f"Say wird beendet: {reason_text}")
                try:
                    self.interrupt_channel.stop_speech()
                except Exception:
                    self.get_logger().warning(
                        "stop_speech() ueber Interrupt-Kanal fehlgeschlagen.", exc_info=True)
                done_event.wait(SAY_CANCEL_GRACE_S)
                final_state = "TIMED_OUT" if timed_out else "CANCELLED"
                break

            result.duration_s = time.time() - t0
            if final_state == "SUCCEEDED" and outcome["error"] is not None:
                self.get_logger().error(f"Say fehlgeschlagen: {outcome['error']}")
                result.success = False
                result.error_message = str(outcome["error"])
                goal_handle.abort()
            elif final_state == "SUCCEEDED":
                result.success = True
                goal_handle.succeed()
            elif final_state == "CANCELLED":
                result.success = False
                result.error_message = "abgebrochen"
                goal_handle.canceled()
            else:
                result.success = False
                result.error_message = final_state
                goal_handle.abort()
        finally:
            self._say_active.clear()
            self.speaking_pub.publish(Bool(data=False))
            self._release_lease(lease_id)
        return result

    def is_speaking(self) -> bool:
        """Fuer den Halbduplex-Controller in ihk_pepper_audio: waehrend
        Pepper spricht, soll die Audio-Pipeline nicht gleichzeitig
        zuhoeren (sonst transkribiert er sich selbst)."""
        return self._say_active.is_set()

    def _on_nav2_moving(self, msg: Bool):
        now = time.monotonic()
        self._nav2_moving = msg.data
        self._nav2_moving_fresh.update(msg.data, now)

    def _on_safety_state_for_gestures(self, msg: SafetyState):
        """Entwicklungsauftrag 04-B, AP8.2: dieselbe safety_ok-Definition
        wie actuator_arbiter_node.py::_safety_ok() (Emergency-Stopp/Bumper
        blockieren, alles andere gilt als "ok fuer eine neue Aktuation")
        -- KEINE zweite, abweichende Definition dessen, was 'sicher'
        bedeutet."""
        now = time.monotonic()
        safety_ok = not msg.emergency_stop and not msg.bumper_active
        self._safety_ok_fresh.update(safety_ok, now)
        # Entwicklungsauftrag 04-B, AP8-R1.4: rohe Einzelfelder zusaetzlich
        # gehalten, damit ein Abbruch als EMERGENCY_STOP/BUMPER_ACTIVE
        # (statt nur generisch SAFETY_INVALID) klassifiziert werden kann.
        self._last_emergency_stop = bool(msg.emergency_stop)
        self._last_bumper_active = bool(msg.bumper_active)

    def _on_mapping_active(self, msg: Bool):
        self._mapping_active_fresh.update(msg.data, time.monotonic())

    def _on_interaction_state(self, msg: UInt8):
        try:
            name = InteractionState(msg.data).name
        except ValueError:
            name = None  # unbekannter Enum-Wert -- gilt wie "nicht empfangen"
        self._interaction_state_fresh.update(name, time.monotonic())

    def _classify_safety_cancel_reason(self) -> str:
        """Entwicklungsauftrag 04-B, AP8-R1.3/1.4: leitet aus den ZULETZT
        empfangenen SafetyState-Rohfeldern den passendsten strukturierten
        Cancel-Grund ab -- EMERGENCY_STOP/BUMPER_ACTIVE, wenn das jeweilige
        Flag zuletzt aktiv war, sonst der generische SAFETY_INVALID
        (fehlend/veraltet/anderweitig ungueltig, siehe
        GestureExecutionPolicy.authorize())."""
        if self._last_emergency_stop:
            return GestureCancelReason.EMERGENCY_STOP
        if self._last_bumper_active:
            return GestureCancelReason.BUMPER_ACTIVE
        return GestureCancelReason.SAFETY_INVALID

    def _on_lease_revoked(self, msg: ActuatorLease):
        """Entwicklungsauftrag 04-B, AP8.3/AP8-R1.7: reagiert
        AUSSCHLIESSLICH auf den eigenen, aktiven Lease -- ein Widerruf fuer
        ein FREMDES Ziel (anderer owner_id) oder ein bereits
        abgeschlossenes eigenes Ziel (lease_id nicht mehr in
        _active_gesture_cancel_events) hat KEINE Wirkung. Setzt dasselbe
        CancelSignal, das eine laufende Geste ohnehin schon beobachtet --
        kein zweiter Abbruchpfad. Laeuft unter _active_execution_lock,
        damit eine Registrierung in _execute_gesture() (anderer Thread)
        NIE zwischen 'lease_id vormerken' und 'cancel_signal lesen'
        eingeschoben werden kann (bestaetigter Fund 3.8, 'Lease-
        Revocation-Race')."""
        if msg.owner_id != OWNER_ID:
            return
        with self._active_execution_lock:
            self._revoked_lease_ids.add(msg.lease_id)
            cancel_signal = self._active_gesture_cancel_events.get(msg.lease_id)
        if cancel_signal is not None:
            self.get_logger().warn(
                f"Aktuator-Lease '{msg.lease_id}' widerrufen ({msg.preempted_reason}) -- "
                "laufendes Ziel wird abgebrochen."
            )
            cancel_signal.set(GestureCancelReason.LEASE_REVOKED)

    def _register_active_execution(self, lease_id: str, cancel_signal: CancelSignal) -> bool:
        """Registriert cancel_signal fuer lease_id ATOMAR (zusammen mit
        _on_lease_revoked() unter demselben Lock) und meldet zurueck, ob
        die Lease zu DIESEM Zeitpunkt bereits (frueher) widerrufen wurde
        (Entwicklungsauftrag 04-B, AP8-R1.7)."""
        with self._active_execution_lock:
            self._active_gesture_cancel_events[lease_id] = cancel_signal
            return lease_id in self._revoked_lease_ids

    def _is_lease_revoked(self, lease_id: str) -> bool:
        with self._active_execution_lock:
            return lease_id in self._revoked_lease_ids

    def _unregister_active_execution(self, lease_id: str) -> None:
        with self._active_execution_lock:
            self._active_gesture_cancel_events.pop(lease_id, None)
            self._revoked_lease_ids.discard(lease_id)

    def _current_runtime_context(self, lease_revoked: bool = False) -> RuntimeContext:
        """Entwicklungsauftrag 04-B, AP8.1/AP8.2: baut den Laufzeitkontext
        fuer GestureExecutionPolicy.authorize() aus den aktuell an der
        Bridge bekannten, EINZELN mit eigenem Zeitstempel gefuehrten
        Signalen (Auftrag Abschnitt 6: "Fuehre mindestens folgende
        Zustaende mit monotonic timestamp und Ablaufzeit"). Wird SOWOHL
        vor der Autorisierung ALS AUCH unmittelbar vor Transportstart
        neu aufgerufen (siehe _execute_gesture()) -- niemals
        zwischengespeichert."""
        now = time.monotonic()
        return RuntimeContext(
            safety_ok=self._safety_ok_fresh.effective(
                now, self.get_parameter("safety_state_max_age_s").value, fail_closed_value=False),
            nav2_moving=self._nav2_moving_fresh.effective(
                now, self.get_parameter("nav2_moving_max_age_s").value, fail_closed_value=True),
            mapping_active=self._mapping_active_fresh.effective(
                now, self.get_parameter("mapping_active_max_age_s").value, fail_closed_value=True),
            current_interaction_state=self._interaction_state_fresh.effective(
                now, self.get_parameter("interaction_state_max_age_s").value, fail_closed_value=None),
            pepper_reachable=self._pepper_reachable_fresh.effective(
                now, self.get_parameter("pepper_reachable_max_age_s").value, fail_closed_value=False),
            lease_revoked=lease_revoked,
        )

    # ---- PlayGesture ----

    def _goal_callback_gesture(self, goal_request):
        if not goal_request.gesture_name.strip():
            self.get_logger().warn("PlayGesture-Ziel ohne Gestennamen abgelehnt")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _watchdog_check(self, gesture, cancel_signal: CancelSignal, execution_profile: str,
                        effective_speed_scale: float, hard_deadline_monotonic_s: float,
                        lease_id: str) -> None:
        """Entwicklungsauftrag 04-B, AP8-R1.3 (bestaetigter Fund 3.3):
        periodisch WAEHREND einer laufenden Gestenausfuehrung aufgerufen
        (siehe Polling-Schleife in _execute_gesture()) -- max_duration_s
        begrenzte bisher nur die KOMPILIERTE Solltrajektorie, nicht die
        tatsaechliche Laufzeit, und Safety-/Nav2-/Mapping-/Interaktions-/
        Erreichbarkeitszustand wurden nur VOR Transportstart geprueft, nie
        waehrend der laufenden Bewegung erneut. Wiederverwendet
        GestureExecutionPolicy.authorize() -- KEINE zweite, abweichende
        Sicherheitslogik. Setzt bei einer Verletzung EINMALIG (CancelSignal
        ist idempotent, ein spaeterer Aufruf aendert den Grund nicht mehr)
        einen strukturierten Cancel-Grund; das eigentliche Abbrechen
        (Interrupt-Kanal, transport.cancel()) uebernimmt der bereits
        bestehende cancel_event-Beobachtungspfad in
        gesture_catalog.py::_play_v2()."""
        if cancel_signal.is_set():
            return
        # Entwicklungsauftrag 04-B, AP8-R1.3: node-lokales Flag statt
        # rclpy.ok() -- rclpy.ok() ist global fuer den gesamten Prozess UND
        # liefert False, solange rclpy.init() (noch) nicht lief (z.B. in
        # jedem Unit-Test dieses Moduls ohne echten ROS2-Kontext), was den
        # Watchdog dort faelschlich sofort ausloesen wuerde. self._shutting_down
        # wird ausschliesslich von destroy_node() gesetzt (siehe dort).
        if self._shutting_down:
            cancel_signal.set(GestureCancelReason.NODE_SHUTDOWN)
            return
        if time.monotonic() > hard_deadline_monotonic_s:
            cancel_signal.set(GestureCancelReason.TIMEOUT)
            return
        if self._is_lease_revoked(lease_id):
            cancel_signal.set(GestureCancelReason.LEASE_REVOKED)
            return
        if execution_profile not in HARDWARE_CAPABLE_PROFILES:
            # Offline-Profile beruehren strukturell nie Hardware
            # (effective_dry_run erzwingt das unabhaengig hiervon) --
            # Laufzeitkontext ist dafuer bedeutungslos, genau wie in
            # GestureExecutionPolicy.authorize() selbst.
            return
        decision = self.gesture_policy.authorize(
            gesture, self._current_runtime_context(), execution_profile,
            requested_speed_scale=effective_speed_scale,
        )
        if decision.allowed:
            return
        reason = _POLICY_REJECTION_TO_CANCEL_REASON.get(decision.reason_code)
        if reason is None and decision.reason_code == "safety_state_ungueltig_oder_unbekannt":
            reason = self._classify_safety_cancel_reason()
        cancel_signal.set(reason or GestureCancelReason.SAFETY_INVALID)

    def _quarantine_unconfirmed_execution(self, lease_id: str, done_event: threading.Event, name: str) -> None:
        """Entwicklungsauftrag 04-B, AP8-R1.6 (bestaetigter Fund 3.4):
        der Hintergrund-Thread hat die Cancel-Grace-Zeit ueberschritten --
        die Lease bleibt ABSICHTLICH gehalten (der Aktuator-Arbiter
        blockiert dadurch jedes zweite Ziel auf denselben Ressourcen
        automatisch ueber die BESTEHENDE Konfliktpruefung, kein zweiter
        Mechanismus noetig), bis der Hintergrund-Thread NACHWEISLICH endet.
        Laeuft in einem eigenen Daemon-Thread, blockiert die
        Action-Rueckgabe nicht -- der urspruengliche Ausfuehrungs-Thread
        darf nach dieser Rueckgabe keinen Restore mehr ausloesen
        (lease_id ist bereits in _quarantined_lease_ids, siehe
        _safety_ok_for_restore() in _execute_gesture())."""
        def _late_cleanup():
            done_event.wait()  # kein Timeout -- wartet auf das tatsaechliche Ende
            self.get_logger().warn(
                f"PlayGesture '{name}': verspaetetes Thread-Ende (lease_id={lease_id}) erkannt -- "
                "Lease/Zustand wird jetzt bereinigt."
            )
            self.gesture_in_progress_pub.publish(Bool(data=False))
            self._unregister_active_execution(lease_id)
            self._quarantined_lease_ids.discard(lease_id)
            self._release_lease(lease_id)
        threading.Thread(target=_late_cleanup, daemon=True).start()

    def _execute_gesture(self, goal_handle):
        """Entwicklungsauftrag 04-B, AP5B, Abschnitt 4/12: Ressourcen
        werden DETERMINISTISCH aus den tatsaechlich betroffenen Gelenken
        abgeleitet (nie aus dem Gestennamen/einer LLM-Angabe), ALLE
        atomar ueber den Aktuator-Arbiter angefordert, BEVOR
        catalog.play() irgendeine Hardwareaktion anstoesst. Laeuft in
        einem Hintergrund-Thread, damit ein Cancel waehrend der
        Ausfuehrung tatsaechlich beobachtet und an catalog.play()s
        cancel_event durchgereicht wird.

        Entwicklungsauftrag 04-B, AP8-R1: mehrere Laufzeitluecken in der
        bereits bestehenden AP8.1-8.3-Struktur geschlossen (siehe
        docs/DEVELOPMENT_ORDER_04_B_REPORT.md, AP8-R1 Abschnitt 3):
        speed_scale wird jetzt GENAU EINMAL kanonisch aufgeloest und
        danach nirgends mehr unabhaengig neu berechnet (AP8-R1.1); die
        Lease-Registrierung erfolgt SOFORT nach Erwerb, nicht erst nach
        der zweiten Pruefung, und wird unmittelbar vor Transportstart
        ERNEUT geprueft (AP8-R1.7, schliesst das Lease-Revocation-Race);
        ein Laufzeit-Watchdog prueft waehrend der GESAMTEN Ausfuehrung
        periodisch weiter (AP8-R1.3); ein nach der Cancel-Grace-Zeit noch
        laufender Hintergrund-Thread fuehrt NIE zu einer Erfolgsmeldung
        oder einer sofortigen Lease-Freigabe (AP8-R1.6)."""
        name = goal_handle.request.gesture_name
        requested_speed_scale = goal_handle.request.speed_scale
        result = PlayGesture.Result()

        def feedback_cb(status, progress):
            fb = PlayGesture.Feedback()
            fb.status = status
            fb.progress = progress
            goal_handle.publish_feedback(fb)

        try:
            gesture = self.catalog.get(name)
        except KeyError as e:
            self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
            return result

        # Entwicklungsauftrag 04-B, AP8.1: ERSTE Autorisierungspruefung --
        # VOR jedem Ressourcenzugriff. Eine Ablehnung hier startet KEINEN
        # Hintergrund-Thread, erwirbt KEINE Lease und beruehrt weder SSH
        # noch qicli (die Pruefung steht bewusst vor _acquire_lease()).
        # Entwicklungsauftrag 04-B, AP8-R1.9 (bestaetigter Fund 3.6): der
        # v1-Transport besitzt noch nicht dieselben Cancel-/Restore-
        # Sicherheitsgarantien wie v2 (kein echtes Mid-Flight-Cancel ueber
        # einen synchronen Transport, kein Watchdog waehrend eines
        # einzelnen set_angle()-Aufrufs) -- production fuer schema_version
        # 1 wird deshalb STRUKTURELL, VOR jeder anderen Pruefung,
        # fail-closed abgelehnt. t_pose.yaml bleibt "live_validated"
        # (beschreibt weiterhin den DAMALS geprueften v1-Ablauf), dieser
        # Status darf die neue Laufzeitsperre aber nicht umgehen.
        execution_profile = self.get_parameter("execution_profile").value
        if gesture.schema_version == 1 and execution_profile == PROFILE_PRODUCTION:
            self.get_logger().warn(
                f"PlayGesture '{name}' abgelehnt: schema_version 1 ist im Profil "
                "'production' gesperrt (legacy_v1_not_safely_interruptible)."
            )
            result.success = False
            result.error_message = "legacy_v1_not_safely_interruptible"
            goal_handle.abort()
            return result

        decision = self.gesture_policy.authorize(
            gesture, self._current_runtime_context(), execution_profile,
            requested_speed_scale=requested_speed_scale,
        )
        if not decision.allowed:
            self.get_logger().warn(
                f"PlayGesture '{name}' von der Ausfuehrungsrichtlinie abgelehnt "
                f"(profile={execution_profile}, reason_code={decision.reason_code}): {decision.reason}"
            )
            result.success = False
            result.error_message = f"{decision.reason_code}: {decision.reason}"
            goal_handle.abort()
            return result

        try:
            resources = resources_for_gesture(gesture)
        except ValueError as e:
            self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
            result.success = False
            result.error_message = str(e)
            goal_handle.abort()
            return result

        goal_id = self._goal_id_str(goal_handle)
        # Entwicklungsauftrag 04-B, AP8-R1.1 (bestaetigter Fund 3.1): die
        # Lease-TTL nutzt DENSELBEN effective_speed_scale wie die erste
        # Autorisierungsentscheidung -- kein unabhaengig berechneter Wert
        # mehr (vorher: "goal_handle.request.speed_scale or 1.0", wodurch
        # die Policy z.B. mit 0.6 rechnen konnte, waehrend der Transport
        # tatsaechlich 1.0 bekam).
        granted, lease_id, reason = self._acquire_lease(
            resources, purpose=f"play_gesture:{name}", goal_id=goal_id,
            ttl_s=max(decision.expected_duration_s + 10.0, 15.0),
        )
        if not granted:
            self.get_logger().warn(f"PlayGesture '{name}' abgelehnt (Aktuator-Arbiter): {reason}")
            result.success = False
            result.error_message = f"Ressourcenkonflikt: {reason}"
            goal_handle.abort()
            return result

        # Entwicklungsauftrag 04-B, AP8-R1.7 (bestaetigter Fund 3.8,
        # 'Lease-Revocation-Race'): Registrierung ATOMAR SOFORT nach
        # Lease-Erwerb (nicht erst nach der zweiten Pruefung wie vorher)
        # -- schliesst das Zeitfenster, in dem ein Widerruf zwischen
        # Erwerb und Registrierung sonst unbemerkt verpuffen konnte
        # (die Lease-ID wurde zwar in _revoked_lease_ids gespeichert,
        # aber vor dem Transportstart nie erneut geprueft).
        cancel_signal = CancelSignal()
        already_revoked = self._register_active_execution(lease_id, cancel_signal)
        if already_revoked:
            cancel_signal.set(GestureCancelReason.LEASE_REVOKED)

        # Entwicklungsauftrag 04-B, AP8.1: ZWEITE Pruefung UNMITTELBAR vor
        # Transportstart -- der Laufzeitkontext kann sich zwischen der
        # ersten Pruefung und dem Lease-Erwerb geaendert haben.
        second_decision = self.gesture_policy.authorize(
            gesture, self._current_runtime_context(lease_revoked=already_revoked),
            execution_profile, requested_speed_scale=requested_speed_scale,
        )
        if not second_decision.allowed:
            self.get_logger().warn(
                f"PlayGesture '{name}' unmittelbar vor Transportstart erneut abgelehnt "
                f"(reason_code={second_decision.reason_code}): {second_decision.reason}"
            )
            self._unregister_active_execution(lease_id)
            self._release_lease(lease_id)
            result.success = False
            result.error_message = f"{second_decision.reason_code}: {second_decision.reason}"
            goal_handle.abort()
            return result

        # Entwicklungsauftrag 04-B, AP8-R1.1: AB HIER ist
        # second_decision.effective_speed_scale VERBINDLICH -- wird
        # unveraendert an catalog.play()/den Compiler/den Safety-Report/
        # den Watchdog weitergereicht, NIE erneut unabhaengig berechnet.
        # Weicht sie unerwartet von der ERSTEN Entscheidung ab (beide
        # muessten fuer dieselbe Anfrage deterministisch identisch sein),
        # wird sicherheitshalber abgelehnt statt eine unerklaerte
        # Abweichung stillschweigend zu uebernehmen.
        if second_decision.effective_speed_scale != decision.effective_speed_scale:
            self.get_logger().error(
                f"PlayGesture '{name}': effective_speed_scale aenderte sich unerwartet "
                f"zwischen erster ({decision.effective_speed_scale}) und zweiter "
                f"({second_decision.effective_speed_scale}) Autorisierungspruefung -- "
                "Ausfuehrung abgelehnt."
            )
            self._unregister_active_execution(lease_id)
            self._release_lease(lease_id)
            result.success = False
            result.error_message = "speed_scale_inkonsistent"
            goal_handle.abort()
            return result
        effective_speed_scale = second_decision.effective_speed_scale

        # Entwicklungsauftrag 04-B, AP8-R1.7: UNMITTELBAR vor Transportstart
        # ERNEUT unter Lock pruefen -- schliesst das (kleine, aber reale)
        # Fenster zwischen der zweiten Pruefung oben und dem tatsaechlichen
        # Threadstart.
        if self._is_lease_revoked(lease_id):
            self.get_logger().warn(
                f"PlayGesture '{name}': Lease unmittelbar vor Transportstart widerrufen -- "
                "Transport wird NICHT gestartet."
            )
            self._unregister_active_execution(lease_id)
            self._release_lease(lease_id)
            result.success = False
            result.error_message = "lease_widerrufen_vor_transportstart"
            goal_handle.abort()
            return result

        # Entwicklungsauftrag 4, AP4/AP13: schliesst die seit Auftrag 2
        # dokumentierte Luecke -- dieses Topic wurde bisher von KEINEM
        # Node tatsaechlich publiziert. True fuer die volle Dauer der
        # Ausfuehrung (auch waehrend eines fehlgeschlagenen Versuchs --
        # es ist erst "vorbei", wenn play() zurueckkehrt).
        self.gesture_in_progress_pub.publish(Bool(data=True))
        try:
            done_event = threading.Event()
            outcome = {"error": None}

            def _run():
                try:
                    # Entwicklungsauftrag 04-B, AP8.1: Verteidigung in der
                    # Tiefe -- offline_mock/offline_preview beruehren NIE
                    # Hardware, unabhaengig vom rohen dry_run-Parameter.
                    effective_dry_run = (
                        self.get_parameter("dry_run").value
                        or execution_profile not in HARDWARE_CAPABLE_PROFILES
                    )

                    def _safety_ok_for_restore():
                        # Entwicklungsauftrag 04-B, AP8.3/AP8-R1.6: eine
                        # Restore-Trajektorie (gesture.on_cancel ==
                        # "restore") braucht einen weiterhin gueltigen
                        # Lease, einen frischen sicheren Zustand ZUM
                        # ABBRUCHZEITPUNKT -- UND darf NIE mehr ausgeloest
                        # werden, wenn diese Lease bereits quarantaeniert
                        # ist (die Action wurde dann schon als
                        # 'cancel_unconfirmed' zurueckgegeben; ein
                        # verspaeteter Thread darf danach keine Bewegung
                        # mehr ausloesen).
                        if lease_id in self._quarantined_lease_ids:
                            return False
                        if self._is_lease_revoked(lease_id):
                            return False
                        return self._safety_ok_fresh.effective(
                            time.monotonic(),
                            self.get_parameter("safety_state_max_age_s").value,
                            fail_closed_value=False,
                        )

                    self.catalog.play(
                        self.pepper, name, effective_speed_scale, feedback_cb,
                        dry_run=effective_dry_run,
                        nav2_moving=self._nav2_moving,
                        cancel_event=cancel_signal,
                        interrupt_channel=self.interrupt_channel,
                        safety_ok_for_restore_fn=_safety_ok_for_restore,
                        # Entwicklungsauftrag 04-B, AP8-R1.8: production
                        # verweigert bereits ein 'inconclusive'
                        # TrajectorySafetyReport (kein Kollisionsnachweis)
                        # -- offline/supervised duerfen inconclusive
                        # ausdruecklich ausfuehren/anzeigen.
                        require_collision_proof=(execution_profile == PROFILE_PRODUCTION),
                        safety_validator=self.gesture_safety_validator,
                    )
                except Exception as e:  # noqa: BLE001
                    outcome["error"] = e
                finally:
                    done_event.set()

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

            # Entwicklungsauftrag 04-B, AP8-R1.3: harter, absoluter
            # Zeitdeckel fuer die TATSAECHLICHE Ausfuehrung -- abgeleitet
            # aus der bereits policy-validierten expected_duration_s
            # (second_decision), nicht aus einem neu erfundenen Wert.
            hard_deadline_monotonic_s = (
                time.monotonic() + second_decision.expected_duration_s + GESTURE_WATCHDOG_TIMEOUT_MARGIN_S
            )
            while not done_event.wait(timeout=GESTURE_POLL_INTERVAL_S):
                if goal_handle.is_cancel_requested:
                    cancel_signal.set(GestureCancelReason.NORMAL_USER_CANCEL)
                self._watchdog_check(
                    gesture, cancel_signal, execution_profile, effective_speed_scale,
                    hard_deadline_monotonic_s, lease_id,
                )
                if cancel_signal.is_set():
                    self.get_logger().info(
                        f"PlayGesture '{name}' wird abgebrochen (Grund: {cancel_signal.reason})."
                    )
                    done_event.wait(GESTURE_CANCEL_GRACE_S)
                    break

            if not done_event.is_set():
                # Entwicklungsauftrag 04-B, AP8-R1.6 (bestaetigter Fund
                # 3.4): der Hintergrund-Thread hat die Cancel-Grace-Zeit
                # ueberschritten -- NIE als Erfolg melden, Lease NICHT
                # freigeben (blockiert dadurch automatisch ein zweites
                # Ziel auf denselben Ressourcen ueber die bestehende
                # Konfliktpruefung), Restore fuer diese Lease dauerhaft
                # sperren, Cleanup erst beim tatsaechlichen (spaeteren)
                # Thread-Ende nachholen.
                self._quarantined_lease_ids.add(lease_id)
                self.get_logger().error(
                    f"PlayGesture '{name}': Hintergrund-Thread hat die Cancel-Grace-Zeit "
                    f"ueberschritten (Grund: {cancel_signal.reason}) -- Lease '{lease_id}' "
                    "bleibt quarantaeniert, bis der Thread nachweislich endet."
                )
                result.success = False
                result.error_message = "cancel_unconfirmed"
                goal_handle.abort()
                self._quarantine_unconfirmed_execution(lease_id, done_event, name)
                return result

            if outcome["error"] is not None:
                e = outcome["error"]
                if isinstance(e, (KeyError, GestureValidationError)):
                    self.get_logger().error(f"PlayGesture '{name}' abgelehnt: {e}")
                else:
                    self.get_logger().error(f"PlayGesture '{name}' fehlgeschlagen: {e}")
                result.success = False
                result.error_message = str(e)
                goal_handle.abort()
            elif cancel_signal.is_set():
                # Entwicklungsauftrag 04-B, AP8-R1.4: EINE gemeinsame
                # Auswertung fuer JEDEN strukturierten Abbruchgrund (ROS-
                # Cancel, Lease-Widerruf, Watchdog-Ausloeser) -- NIE als
                # Erfolg werten. goal_handle.canceled() nur fuer den
                # normalen Nutzerabbruch (ROS2-Konvention), jeder andere
                # Grund ist ein abort() mit dem strukturierten Grund als
                # Fehlermeldung.
                result.success = False
                result.error_message = cancel_signal.reason or "abgebrochen"
                if cancel_signal.reason == GestureCancelReason.NORMAL_USER_CANCEL:
                    goal_handle.canceled()
                else:
                    goal_handle.abort()
            else:
                result.success = True
                goal_handle.succeed()
        finally:
            if done_event.is_set():
                self.gesture_in_progress_pub.publish(Bool(data=False))
                self._unregister_active_execution(lease_id)
                self._quarantined_lease_ids.discard(lease_id)
                self._release_lease(lease_id)
            elif lease_id not in self._quarantined_lease_ids:
                # Fallback fuer eine unerwartete Exception VOR dem
                # regulaeren Quarantaene-Pfad oben -- stellt sicher, dass
                # eine solche Lease NIEMALS sofort freigegeben wird, nur
                # weil der erwartete Pfad nicht erreicht wurde.
                self._quarantined_lease_ids.add(lease_id)
                self._quarantine_unconfirmed_execution(lease_id, done_event, name)
        return result

    # ---- SetHeadPose (Entwicklungsauftrag 04-B, AP6, Abschnitt 7/12) ----

    def _goal_callback_set_head_pose(self, goal_request):
        return GoalResponse.ACCEPT

    def _execute_set_head_pose(self, goal_handle):
        """Sicherer Hardware-Grenzpunkt fuer JEDE Kopfbewegung --
        ausschliesslich HeadYaw/HeadPitch, NIEMALS die Basis. Erwirbt vor
        jeder Bewegung eine HEAD-Lease, klemmt auf konservative operative
        Grenzen (enger als die vollen Gelenkgrenzen), verwirft veraltete
        Quelldaten fail-closed, und bricht bei Cancel ueber den
        Interrupt-Kanal ab (gleiches Muster wie _execute_say/_execute_gesture)."""
        result = SetHeadPose.Result()
        request = goal_handle.request

        source_time_s = request.source_stamp.sec + request.source_stamp.nanosec / 1e9
        now_time_s = self.get_clock().now().nanoseconds / 1e9
        age_s = now_time_s - source_time_s
        if request.max_source_age_s > 0.0 and age_s > request.max_source_age_s:
            result.success = False
            result.error_message = (
                f"Quelldaten zu alt ({age_s:.2f}s > {request.max_source_age_s:.2f}s) -- "
                f"keine Bewegung auf Basis veralteter Daten."
            )
            goal_handle.abort()
            return result

        target_yaw = max(HEAD_YAW_OPERATIONAL_MIN_RAD, min(HEAD_YAW_OPERATIONAL_MAX_RAD, request.head_yaw_rad))
        target_pitch = max(HEAD_PITCH_OPERATIONAL_MIN_RAD, min(HEAD_PITCH_OPERATIONAL_MAX_RAD, request.head_pitch_rad))
        clamped = (target_yaw != request.head_yaw_rad) or (target_pitch != request.head_pitch_rad)
        try:
            validate_angle_with_margin("HeadYaw", target_yaw)
            validate_angle_with_margin("HeadPitch", target_pitch)
        except Exception as e:
            result.success = False
            result.error_message = f"Zielwinkel ausserhalb der Sicherheitsmarge: {e}"
            goal_handle.abort()
            return result

        feedback = SetHeadPose.Feedback()
        feedback.status = "acquiring_lease"
        feedback.current_head_yaw_rad = 0.0
        feedback.current_head_pitch_rad = 0.0
        goal_handle.publish_feedback(feedback)

        # request.owner_id ist rein informativ (Diagnose/purpose-Feld) --
        # die tatsaechliche Lease-Eigentuemerschaft bleibt konsistent bei
        # OWNER_ID="pepper_bridge", wie bei Say/PlayGesture: die Bridge
        # selbst ist der Aktuator-Eigentuemer, nicht der semantische
        # Aufrufer (z.B. orient_to_sound_node.py).
        purpose = f"set_head_pose:{request.owner_id}" if request.owner_id else "set_head_pose"
        granted, lease_id, reason = self._acquire_lease(
            {HEAD}, purpose=purpose, goal_id=self._goal_id_str(goal_handle),
            ttl_s=HEAD_LEASE_TTL_S, priority=PRIORITY_ATTRACT,
        )
        if not granted:
            self.get_logger().warn(f"SetHeadPose abgelehnt (Aktuator-Arbiter): {reason}")
            result.success = False
            result.error_message = f"HEAD-Lease verweigert: {reason}"
            goal_handle.abort()
            return result

        try:
            feedback.status = "moving"
            goal_handle.publish_feedback(feedback)

            speed_scale = request.max_speed_scale if request.max_speed_scale > 0.0 else 1.0
            speed_scale = max(0.05, min(1.0, speed_scale))
            duration = HEAD_MOVE_BASE_DURATION_S / speed_scale

            done_event = threading.Event()
            outcome = {"error": None}

            def _run():
                try:
                    if not self.get_parameter("dry_run").value:
                        self.pepper.play_trajectory(
                            ["HeadYaw", "HeadPitch"], [[target_yaw], [target_pitch]],
                            [[duration], [duration]], is_absolute=True,
                        )
                except Exception as e:  # noqa: BLE001
                    outcome["error"] = e
                finally:
                    done_event.set()

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

            cancelled = False
            while not done_event.wait(timeout=HEAD_POLL_INTERVAL_S):
                if goal_handle.is_cancel_requested:
                    self.get_logger().info("SetHeadPose wird abgebrochen.")
                    try:
                        self.interrupt_channel.stop_motion()
                    except Exception:
                        self.get_logger().warning(
                            "stop_motion() ueber Interrupt-Kanal fehlgeschlagen.", exc_info=True)
                    done_event.wait(HEAD_CANCEL_GRACE_S)
                    cancelled = True
                    break

            final_yaw, final_pitch = target_yaw, target_pitch
            try:
                if not self.get_parameter("dry_run").value:
                    final_yaw = self.pepper.get_angle("HeadYaw") or target_yaw
                    final_pitch = self.pepper.get_angle("HeadPitch") or target_pitch
            except Exception:
                pass  # Diagnose-Bestwertversuch -- Ergebnis faellt sonst auf das Ziel zurueck

            result.final_head_yaw_rad = final_yaw
            result.final_head_pitch_rad = final_pitch
            if cancelled:
                result.success = False
                result.error_message = "abgebrochen"
                goal_handle.canceled()
            elif outcome["error"] is not None:
                result.success = False
                result.error_message = str(outcome["error"])
                goal_handle.abort()
            else:
                result.success = True
                result.error_message = "auf operative Grenze geklemmt" if clamped else ""
                goal_handle.succeed()
            return result
        finally:
            self._release_lease(lease_id)

    # ---- Health ----

    def _publish_health(self):
        msg = SystemHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        reachable = self.pepper.is_reachable(timeout_s=1.0)
        # Entwicklungsauftrag 04-B, AP8.2: wiederverwendet genau diesen
        # bereits periodisch laufenden Erreichbarkeits-Check fuer
        # RuntimeContext.pepper_reachable -- kein zweiter, blockierender
        # Netzwerk-Check im Gesten-Ausfuehrungspfad selbst (siehe
        # _current_runtime_context()).
        self._pepper_reachable_fresh.update(reachable, time.monotonic())
        msg.pepper_bridge_ok = reachable
        msg.audio_pipeline_ok = False  # von ihk_pepper_audio ueberschrieben, hier nur Platzhalter
        msg.anythingllm_ok = False  # von ihk_pepper_dialog ueberschrieben
        msg.navigation_ok = False
        msg.perception_ok = False

        # Entwicklungsauftrag 4, AP4: reale Werte statt Platzhalter fuer
        # bumper/charging_state/battery/connection_state. Bei fehlendem
        # oder ungueltigem Wert wird bewusst NICHT "false"/0 verwendet
        # (das waere eine unbegruendete positive Aussage), sondern der
        # sicherste Wert je Topic -- ein Bumper, dessen Zustand nicht
        # ermittelt werden konnte, gilt als GEDRUECKT (blockiert), keine
        # Ladeinfo gilt als LAEDT NICHT (konservativ fuer den
        # Fahr-Interlock ist das die Annahme, die Fahrt eher zulaesst als
        # verweigert -- die eigentliche Sicherheitsentscheidung liegt bei
        # Motion Guard, der bei fehlenden/veralteten Daten ohnehin
        # blockiert, nicht bei diesem reinen Statustopic).
        bumper_pressed = None
        charging = None
        battery = None
        if reachable:
            try:
                bumper_pressed = self.pepper.get_bumper_pressed()
            except Exception as e:
                self.get_logger().warn(f"get_bumper_pressed() fehlgeschlagen: {e}")
            try:
                charging = self.pepper.get_charging_state()
            except Exception as e:
                self.get_logger().warn(f"get_charging_state() fehlgeschlagen: {e}")
            try:
                battery = self.pepper.get_battery()
            except Exception as e:
                self.get_logger().warn(f"get_battery() fehlgeschlagen: {e}")

        self.bumper_pub.publish(Bool(data=True if bumper_pressed is None else bumper_pressed))
        self.charging_state_pub.publish(Bool(data=False if charging is None else charging))
        self.battery_pub.publish(Float32(data=-1.0 if battery is None else float(battery)))
        self.connection_state_pub.publish(String(data=self.pepper.connection_state))
        self._publish_joint_states(reachable)

        msg.battery_percent = -1.0 if battery is None else float(battery)
        msg.current_mode = "unknown"
        msg.active_warnings = [] if reachable else ["pepper_unreachable"]
        self.health_pub.publish(msg)

    def _publish_joint_states(self, reachable: bool):
        """Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: einzige Quelle fuer
        /joint_states in autonomy_ws -- robot_state_publisher berechnet daraus
        die dynamische Kette base_link->torso->Neck->Head (siehe
        pepper_robot_state.launch.py). Nur HeadYaw/HeadPitch sind fuer diese
        Teilkette noetig (siehe pepper_description-URDF: base_link->torso ist
        FIX, torso->Neck traegt HeadYaw, Neck->Head traegt HeadPitch).

        Fail-closed wie das restliche Health-Polling: bei nicht erreichbarem
        Pepper oder einem Fehler beim Auslesen wird NICHTS publiziert --
        camera_pose_gate_node.py/head_pose_gate.py behandeln fehlende/
        veraltete /joint_states bereits als "Kopfpose nicht sicher bekannt"
        und sperren entsprechend (keine erfundenen Nullwerte statt echter
        Gelenkwinkel)."""
        if not reachable:
            return
        try:
            yaw = self.pepper.get_angle("HeadYaw")
            pitch = self.pepper.get_angle("HeadPitch")
        except Exception as e:
            self.get_logger().warn(f"get_angle() fuer /joint_states fehlgeschlagen: {e}")
            return
        if yaw is None or pitch is None:
            return
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = ["HeadYaw", "HeadPitch"]
        msg.position = [float(yaw), float(pitch)]
        self.joint_states_pub.publish(msg)

    def destroy_node(self):
        """Entwicklungsauftrag 04-B, AP8-R1.3: setzt das node-lokale
        Shutdown-Flag VOR dem eigentlichen Zerstoeren -- der
        Laufzeit-Watchdog einer noch laufenden Gestenausfuehrung
        (_watchdog_check()) beobachtet dieses Flag und bricht mit
        GestureCancelReason.NODE_SHUTDOWN ab, statt unbemerkt
        weiterzulaufen, waehrend der Node bereits abgebaut wird."""
        self._shutting_down = True
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PepperBridgeNode()
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.pepper.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
