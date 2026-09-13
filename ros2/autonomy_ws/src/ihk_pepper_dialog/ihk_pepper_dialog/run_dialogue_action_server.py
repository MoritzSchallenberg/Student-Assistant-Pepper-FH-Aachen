#!/usr/bin/env python3
"""
run_dialogue_action_server: implementiert RunDialogue.action als echten
Action-Server (Entwicklungsauftrag 3, AP11). Wird vom Behavior Tree ueber
den neuen RunDialogueViaBT-Knoten gestartet, NACHDEM CONVERSATION_READY
erreicht wurde (siehe DialogueSubtree in trees/pepper_main.xml).

Ablauf (Auftrag-Vorgabe): Zielperson/Session uebernehmen -> optional
freigegebenen Personenkontext laden (NUR mit Consent, ueber
person_memory_node) -> auf Frage warten -> Drei-LLM-Pipeline
(ihk_pepper_llm_contracts) -> ResponsePlan validieren -> sprechen+
gestikulieren (ResponsePlanExecutor) -> auf Folgefrage warten -> bei
Verabschiedung/Timeout/Personenverlust/Stopp beenden -> Gedaechtnis NUR
nach erfolgreicher Validierung aktualisieren -> zurueck in IDLE.

KEINE Abbruchbedingung gibt je eine Bewegungsfreigabe -- dieser Node
ruft NIEMALS SetMotionPermission auf und aendert nie SafetyState, nur
InteractionState-Uebergaenge (ueber den bestehenden
set_interaction_state-Service aus Entwicklungsauftrag 1) und den
eigenen Session-Zustand.

LLM-Provider: ueber ROS-Parameter waehlbar
(knowledge_llm_provider/gesture_llm_provider/response_llm_provider,
jeweils "mock"|"anythingllm"|"openai_compatible"|"kiconnect"|"offline",
Default "offline" -- sicherster Default, kein Netzwerkzugriff noetig).
Jede Rolle unabhaengig konfigurierbar (ProviderConfig.from_env, siehe
AP2). "kiconnect" (Ergaenzungsauftrag 04-A, Abschnitt 1) ist fuer
response_llm_provider (LLM 3) gedacht -- knowledge_llm_provider/
gesture_llm_provider bleiben technisch frei waehlbar, u.a. weiterhin
"offline"/"mock".
"""
import os
import threading
import time

import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, String

from ihk_pepper_audio.cancel_words import detect_command, is_hard_stop
from ihk_pepper_interfaces.action import PlayGesture, RunDialogue, Say
from ihk_pepper_interfaces.msg import DialogueState, PersonTrackArray, SafetyState
from ihk_pepper_interfaces.srv import GetPersonContext, SearchGestures, WriteMemorySummary

from ihk_pepper_llm_contracts.gesture_planner import GestureOption, GesturePlanRequest
from ihk_pepper_llm_contracts.knowledge_planner import KnowledgePlanRequest
from ihk_pepper_llm_contracts.knowledge_planner import PersonContext as PipelinePersonContext
from ihk_pepper_llm_contracts.pipeline import (
    run_gesture_planner,
    run_knowledge_planner,
    run_response_composer,
)
from ihk_pepper_llm_contracts.providers import (
    AnythingLLMProvider,
    KIConnectProvider,
    MockLLMProvider,
    OfflineFallbackProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
)
from ihk_pepper_llm_contracts.response_plan import PlanContext, ResponsePlanValidator
from ihk_pepper_llm_contracts.retriever import run_retrieval

from . import safety_topics
from .faq_cache import FaqCache
from .response_plan_executor import ResponsePlanExecutor
from .tts_sanitizer import prepare_for_speech

DEFAULT_SESSION_TIMEOUT_S = 180.0
DEFAULT_QUESTION_TIMEOUT_S = 20.0
MAX_TRACK_AGE_S = 2.0

# Entwicklungsauftrag 04-B, AP5A: maximales zulaessiges Alter je
# sicherheitsrelevantem Laufzeitsignal, bevor es als "unbekannt" gilt
# (siehe safety_topics.FreshBool.effective() -- fail-closed statt eines
# stillen Dataclass-Defaults). Werte an bestehende Konventionen angelehnt
# (MAX_TRACK_AGE_S=2.0, motion_guard_node.py/supervisor_node.py).
NAV2_MOVING_MAX_AGE_S = 1.0
MAPPING_ACTIVE_MAX_AGE_S = 2.0
GESTURE_IN_PROGRESS_MAX_AGE_S = 2.0
CONNECTION_STATE_MAX_AGE_S = 5.0
SAFETY_STATE_MAX_AGE_S = 2.0

# Beide Systemgesten (Ergaenzungsauftrag 04-A) bewegen den Kopf
# (HeadPitch) -- nie ueber die LLM-Allowlist gesteuert, deshalb hier als
# eigene, feste Menge fuer den Recheck in _recheck_before_gesture()
# (Abschnitt 8) statt ueber PlanContext.head_gesture_names.
SYSTEM_GESTURES_AFFECTING_HEAD = frozenset({"acknowledge_nod_small", "thinking_loop_subtle"})


def build_faq_cache(db_path: str):
    """Siehe dialog_manager_node.py::build_faq_cache() -- MUSS vor
    rclpy.init() aufgerufen werden (sentence-transformers/torch NACH
    einem bestehenden rclpy-Context fuehrt reproduzierbar zu einem
    RCLError, per Live-Test in Auftrag 1 gefunden)."""
    return FaqCache(db_path)


def _build_provider(kind: str, env_prefix: str, mock_fixed_response: str = ""):
    config = ProviderConfig.from_env(env_prefix)
    if kind == "mock":
        # mock_fixed_response existiert ausschliesslich fuer Tests (siehe
        # manual_dialogue_e2e_check.py) -- ermoeglicht, jede der drei
        # Stufen unabhaengig mit einer realistischen kanonischen Antwort
        # zu bestuecken, ohne einen echten LLM-Endpunkt zu brauchen.
        return MockLLMProvider(config, fixed_response=mock_fixed_response or "{}")
    if kind == "anythingllm":
        return AnythingLLMProvider(config)
    if kind == "openai_compatible":
        return OpenAICompatibleProvider(config)
    if kind == "kiconnect":
        # Ergaenzungsauftrag 04-A, Abschnitt 1.1: LLM 3 ueber FH Aachen
        # KI:connect. Ein fehlendes RESPONSE_LLM_MODEL ist ein
        # Konfigurationsfehler (KIConnectProvider.__init__ wirft dann
        # ValueError) -- das faellt hier bewusst NICHT auf
        # OfflineFallbackProvider zurueck, sondern propagiert den Fehler
        # direkt beim Start, damit eine falsche Konfiguration sofort
        # auffaellt statt erst beim ersten Dialogversuch.
        #
        # Entwicklungsauftrag 04-B, Abschnitt 3: KI:connect MUSS ein
        # eigenes Token verwenden, niemals automatisch ANYTHINGLLM_API_TOKEN
        # geteilt bekommen. config (oben via from_env()) kann diesen
        # geteilten Fallback bereits enthalten -- deshalb hier eine EIGENE
        # Konfiguration ohne Fallback aufbauen, statt der oben schon
        # aufgeloesten config zu vertrauen.
        kiconnect_config = ProviderConfig.from_env_dedicated_token(env_prefix)
        return KIConnectProvider(kiconnect_config)
    return OfflineFallbackProvider(config)


class RunDialogueActionServer(Node):
    def __init__(self, faq_cache: FaqCache):
        super().__init__("run_dialogue_action_server")

        self.declare_parameter("knowledge_llm_provider", "offline")
        self.declare_parameter("gesture_llm_provider", "offline")
        self.declare_parameter("response_llm_provider", "offline")
        self.declare_parameter("knowledge_llm_mock_response", "")
        self.declare_parameter("gesture_llm_mock_response", "")
        self.declare_parameter("response_llm_mock_response", "")
        self.declare_parameter("session_timeout_s", DEFAULT_SESSION_TIMEOUT_S)
        self.declare_parameter("question_timeout_s", DEFAULT_QUESTION_TIMEOUT_S)
        self.declare_parameter("post_speech_pause_s", 0.3)
        # Ergaenzungsauftrag 04-A, "Mhm"-/Denksequenz: erst NACH
        # thinking_loop_delay_s Wartezeit auf die LLM-Pipeline wird
        # ueberhaupt eine sichtbare Denkschleife gestartet (bei einer
        # schnellen Antwort soll gar keine sichtbare Zusatzbewegung
        # noetig sein). max_repetitions/max_duration_s sind BEIDE
        # wirksame Obergrenzen (welche zuerst erreicht wird, stoppt die
        # Schleife) -- siehe thinking_loop_subtle.yaml fuer die
        # Ein-Zyklus-pro-Aufruf-Bauweise und die "unterbrechbar an
        # Zyklusgrenzen"-Einschraenkung.
        self.declare_parameter("thinking_loop_delay_s", 2.0)
        self.declare_parameter("thinking_loop_max_repetitions", 3)
        self.declare_parameter("thinking_loop_max_duration_s", 6.0)

        # Entwicklungsauftrag 04-B, AP5A: Gesten-Vektordatenbank-Anbindung.
        # Faellt der Service aus/timed out/ist deaktiviert -> keine Geste,
        # die Antwort wird trotzdem gesprochen (siehe _search_gestures()).
        self.declare_parameter("gesture_search.enabled", True)
        self.declare_parameter("gesture_search.service_timeout_s", 0.75)
        self.declare_parameter("gesture_search.top_k", 5)
        self.declare_parameter("gesture_search.max_duration_s", 6.0)
        self.declare_parameter("gesture_search.minimum_tested_status_development", "dry_run_validated")
        self.declare_parameter("gesture_search.recent_gesture_window", 3)

        self.knowledge_provider = _build_provider(
            self.get_parameter("knowledge_llm_provider").value, "KNOWLEDGE_LLM",
            self.get_parameter("knowledge_llm_mock_response").value)
        self.gesture_provider = _build_provider(
            self.get_parameter("gesture_llm_provider").value, "GESTURE_LLM",
            self.get_parameter("gesture_llm_mock_response").value)
        self.response_provider = _build_provider(
            self.get_parameter("response_llm_provider").value, "RESPONSE_LLM",
            self.get_parameter("response_llm_mock_response").value)

        self.faq = faq_cache

        self._tracks = {}  # track_id -> (PersonTrack, empfangszeit)
        self._safety_state = None
        self._safety_state_received_at = None
        self._latest_transcript = None
        self._latest_transcript_event = threading.Event()
        self._voice_command = None

        # Entwicklungsauftrag 04-B, AP5A: fail-closed Laufzeitsignale fuer
        # die Gestenfreigabe -- "unbekannt" (kein/veraltetes Signal) wird
        # IMMER in die sichere Richtung aufgeloest (siehe
        # _runtime_gesture_context()), niemals stillschweigend als "false"
        # behandelt. Initialwerte folgen der bestehenden Konvention aus
        # motion_guard_node.py/supervisor_node.py: Aktivitaets-/
        # Gefahrensignale starten auf True (angenommen aktiv, bis
        # widerlegt), Erreichbarkeits-/Validitaetssignale auf False
        # (angenommen nicht bestaetigt, bis ein Signal eintrifft).
        self._nav2_moving = safety_topics.FreshBool(True)
        self._mapping_active = safety_topics.FreshBool(True)
        self._gesture_in_progress_fresh = safety_topics.FreshBool(True)
        self._pepper_connected = safety_topics.FreshBool(False)
        # Vom aktuell laufenden Dialog-Turn gesetzt (siehe _execute()),
        # von _gesture_and_wait() unmittelbar vor jeder Action gelesen
        # (Abschnitt 8) -- None ausserhalb eines Turns/fuer Systemgesten.
        self._current_gesture_recheck_context = None
        # Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: der jeweils
        # AKTUELL laufende Say-/PlayGesture-Goal-Handle -- ermoeglicht
        # _cancel_active_actions(), eine bereits laufende Action aktiv
        # abzubrechen (nicht nur zwischen zwei Segmenten zu pruefen).
        self._active_say_goal_handle = None
        self._active_gesture_goal_handle = None
        # Entwicklungsauftrag 04-B, AP8.8, Abschnitt 7/3.3 (bestaetigter
        # Fund): _send_goal_and_wait() setzte active_goal_attr bisher
        # OHNE Eigentuemerpruefung -- ein NACH dem eigenen Timeout
        # verspaetet eintreffendes on_goal_response() konnte den Handle
        # EINES ANDEREN, inzwischen neu gestarteten Aufrufs ueberschreiben
        # (oder der eigene finally-Block konnte einen bereits vom
        # naechsten Aufruf gesetzten Handle wieder loeschen). Ein
        # Call-Token pro _send_goal_and_wait()-Aufruf bindet jede
        # Schreib-/Loeschoperation auf active_goal_attr an genau DIESEN
        # Aufruf -- ein fremder/veralteter Aufruf darf sie nie beruehren.
        self._active_goal_tokens = {}
        # Entwicklungsauftrag 04-B, AP8.8, Abschnitt 4 (bestaetigter
        # Fund): _goal_callback() akzeptierte bisher JEDES eingehende
        # RunDialogue-Ziel bedingungslos -- mehrere gleichzeitig aktive
        # Sitzungen haetten sich dieselben, ungeschuetzten globalen
        # Action-Handles (oben) geteilt. Erzwingt jetzt Einzelaktivitaet:
        # ein zweites Ziel wird abgelehnt, waehrend eines bereits laeuft.
        self._active_execution_lock = threading.Lock()
        self._active_session_id = None

        cb_group = ReentrantCallbackGroup()

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_tracks, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)
        self.create_subscription(String, "/audio_node/transcript", self._on_transcript, 10)
        self.create_subscription(String, "/audio_node/voice_command", self._on_voice_command, 10)
        self.create_subscription(Bool, safety_topics.NAV2_MOVING_TOPIC, self._on_nav2_moving, 10)
        self.create_subscription(Bool, safety_topics.MAPPING_ACTIVE_TOPIC, self._on_mapping_active, 10)
        self.create_subscription(
            Bool, safety_topics.GESTURE_IN_PROGRESS_TOPIC, self._on_gesture_in_progress, 10)
        self.create_subscription(
            String, safety_topics.CONNECTION_STATE_TOPIC, self._on_connection_state, 10)

        self.speaking_pub = self.create_publisher(Bool, "speaking", 10)
        self.dialogue_state_pub = self.create_publisher(DialogueState, "dialogue_state", 10)

        self.say_client = ActionClient(self, Say, "/pepper_bridge/say", callback_group=cb_group)
        self.gesture_client = ActionClient(
            self, PlayGesture, "/pepper_bridge/play_gesture", callback_group=cb_group)
        self.get_person_context_client = self.create_client(
            GetPersonContext, "/get_person_context", callback_group=cb_group)
        self.write_memory_client = self.create_client(
            WriteMemorySummary, "/write_memory_summary", callback_group=cb_group)
        self.search_gestures_client = self.create_client(
            SearchGestures, "search_gestures", callback_group=cb_group)

        self._action_server = ActionServer(
            self, RunDialogue, "run_dialogue",
            execute_callback=self._execute,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )

        self.get_logger().info(
            f"run_dialogue_action_server gestartet -- Provider: "
            f"knowledge={self.knowledge_provider.name}, gesture={self.gesture_provider.name}, "
            f"response={self.response_provider.name}"
        )

    # ---- eingehende Daten ----

    def _on_tracks(self, msg: PersonTrackArray):
        now = time.time()
        for t in msg.tracks:
            self._tracks[t.track_id] = (t, now)

    def _on_safety_state(self, msg: SafetyState):
        self._safety_state = msg
        self._safety_state_received_at = time.time()

    def _on_transcript(self, msg: String):
        self._latest_transcript = msg.data
        self._latest_transcript_event.set()

    def _on_voice_command(self, msg: String):
        self._voice_command = detect_command(msg.data)

    def _on_nav2_moving(self, msg: Bool):
        self._nav2_moving.update(msg.data, time.time())

    def _on_mapping_active(self, msg: Bool):
        self._mapping_active.update(msg.data, time.time())

    def _on_gesture_in_progress(self, msg: Bool):
        self._gesture_in_progress_fresh.update(msg.data, time.time())

    def _on_connection_state(self, msg: String):
        self._pepper_connected.update(msg.data == "connected", time.time())

    def _track_alive(self, track_id) -> bool:
        entry = self._tracks.get(track_id)
        if entry is None:
            return False
        _, received_at = entry
        return (time.time() - received_at) <= MAX_TRACK_AGE_S

    def _safety_ok(self) -> bool:
        """Entwicklungsauftrag 04-B, AP5A: SafetyState unbekannt (nie
        empfangen ODER veraltet) sperrt den GESAMTEN Plan -- dieselbe
        fail-closed Regel wie ein fehlendes Signal in motion_guard_node.py."""
        if self._safety_state is None or self._safety_state_received_at is None:
            return False
        if (time.time() - self._safety_state_received_at) > SAFETY_STATE_MAX_AGE_S:
            return False
        return not self._safety_state.emergency_stop and not self._safety_state.bumper_active

    def _runtime_gesture_context(self) -> dict:
        """Fail-closed Momentaufnahme der gestenrelevanten Laufzeitsignale
        (Entwicklungsauftrag 04-B, AP5A, Abschnitt 4). Ein fehlendes/
        veraltetes Signal loest sich IMMER in die sichere Richtung auf:
        nav2_moving/mapping_active/gesture_in_progress -> True (sperrt),
        pepper_reachable -> False (sperrt). Diese Werte gehen 1:1 in
        PlanContext, das selbst KEINE eigene Fail-Closed-Logik mehr
        anwenden muss (vollstaendig vom Aufrufer befuellter Kontext,
        siehe PlanContext-Docstring in response_plan.py)."""
        now = time.time()
        return {
            "nav2_moving": self._nav2_moving.effective(now, NAV2_MOVING_MAX_AGE_S, True),
            "mapping_active": self._mapping_active.effective(now, MAPPING_ACTIVE_MAX_AGE_S, True),
            "gesture_in_progress": self._gesture_in_progress_fresh.effective(
                now, GESTURE_IN_PROGRESS_MAX_AGE_S, True),
            "pepper_reachable": self._pepper_connected.effective(
                now, CONNECTION_STATE_MAX_AGE_S, False),
        }

    # ---- Action-Server-Callbacks ----

    def _goal_callback(self, goal_request):
        # Entwicklungsauftrag 04-B, AP8.8, Abschnitt 4: erzwingt
        # Einzelaktivitaet fuer RunDialogue -- die Reservierung passiert
        # HIER (nicht erst in _execute()), unter demselben Lock geprueft
        # und gesetzt, damit zwei nahezu gleichzeitig eintreffende Ziele
        # nicht beide noch "frei" sehen koennen (TOCTOU).
        with self._active_execution_lock:
            if self._active_session_id is not None:
                self.get_logger().warn(
                    f"RunDialogue-Ziel fuer Sitzung '{goal_request.session_id}' abgelehnt -- "
                    f"Sitzung '{self._active_session_id}' laeuft bereits."
                )
                return GoalResponse.REJECT
            self._active_session_id = goal_request.session_id
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        session_id = goal_handle.request.session_id
        result = RunDialogue.Result()

        def feedback(state_value, state_name, partial_transcript=""):
            fb = RunDialogue.Feedback()
            fb.dialogue_state = state_value
            fb.state_name = state_name
            fb.partial_transcript = partial_transcript
            goal_handle.publish_feedback(fb)
            # Behebt eine bisher bestehende Luecke: dialogue_state_pub
            # wurde seit seiner Einfuehrung (AP11) angelegt, aber nie
            # publiziert -- nur die eigene Action-Rueckmeldung war
            # sichtbar, kein unabhaengiger Topic-Konsument (z.B. eine
            # spaetere Tablet-Anzeige oder der BT) konnte den
            # Dialogzustand live mitlesen.
            ds = DialogueState()
            ds.header.stamp = self.get_clock().now().to_msg()
            ds.state = state_value
            ds.state_name = state_name
            ds.session_id = session_id
            ds.last_transcript = partial_transcript
            self.dialogue_state_pub.publish(ds)

        track_id = _try_parse_int(session_id)
        session_start = time.time()
        person_context = self._load_person_context(session_id)

        feedback(DialogueState.LISTENING, "LISTENING")
        executor = ResponsePlanExecutor(
            say_fn=self._say_and_wait,
            gesture_fn=self._gesture_and_wait,
            set_speaking_fn=lambda flag: self.speaking_pub.publish(Bool(data=flag)),
            segment_status_cb=lambda seg_id, status: self.get_logger().debug(
                f"Segment {seg_id}: {status}"),
            post_speech_pause_s=self.get_parameter("post_speech_pause_s").value,
            cancel_active_fn=self._cancel_active_actions,
        )
        # Entwicklungsauftrag 04-B, AP5A, Abschnitt 7: Wiederholungsschutz
        # gilt NUR pro Sitzung (lokale Variable, nicht Node-weit -- zurueckgesetzt
        # bei jeder neuen RunDialogue-Session). Nur thematische (LLM-
        # ausgewaehlte) Gesten landen hier -- Systemgesten ("Mhm"/
        # Denkschleife) verfaelschen dieses Fenster nie, da sie ueber
        # separate Methoden laufen, die recent_gestures nie aktualisieren.
        recent_gestures = []
        recent_gesture_window = self.get_parameter("gesture_search.recent_gesture_window").value

        try:
            while True:
                if goal_handle.is_cancel_requested:
                    result.success = False
                    result.final_state = "CANCELLED"
                    result.error_message = "explizit abgebrochen"
                    goal_handle.canceled()
                    return result

                if (time.time() - session_start) > self.get_parameter("session_timeout_s").value:
                    return self._finish(goal_handle, result, "SESSION_TIMEOUT", success=True, feedback=feedback)

                if track_id is not None and not self._track_alive(track_id):
                    return self._finish(goal_handle, result, "PERSON_LOST", success=True, feedback=feedback)

                if not self._safety_ok():
                    return self._finish(goal_handle, result, "SAFETY_EVENT", success=False,
                                         error="Sicherheitsereignis waehrend des Dialogs", feedback=feedback)

                feedback(DialogueState.LISTENING, "LISTENING")
                question = self._wait_for_question(goal_handle)
                if question is None:
                    return self._finish(goal_handle, result, "QUESTION_TIMEOUT", success=True, feedback=feedback)
                if question == "__STOP__":
                    executor.cancel()
                    return self._finish(goal_handle, result, "USER_STOP", success=True, feedback=feedback)

                pipeline_output = self._acknowledge_and_run_pipeline(
                    goal_handle, feedback, question, session_id, person_context, recent_gestures)
                if pipeline_output is None:
                    continue  # Sicherheitsfehler -- Segment/Runde ueberspringen, Session laeuft weiter

                response_plan, memory_summary_candidate, gesture_recheck_context = pipeline_output
                # Entwicklungsauftrag 04-B, AP5A, Abschnitt 8: unmittelbar
                # vor jeder tatsaechlichen PlayGesture-Action liest
                # _gesture_and_wait() diesen Kontext erneut -- zusaetzliche
                # Schutzschicht, kein Ersatz fuer den spaeteren zentralen
                # Aktuator-Arbiter (AP5B).
                self._current_gesture_recheck_context = gesture_recheck_context
                feedback(DialogueState.SPEAKING, "SPEAKING")
                # Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: laeuft in
                # einem Hintergrund-Thread, damit ein waehrenddessen
                # eintreffender RunDialogue-Cancel TATSAECHLICH bemerkt
                # und an executor.cancel() (-> _cancel_active_actions())
                # durchgereicht wird -- vorher blockierte
                # executor.execute() den Hauptthread komplett, ein
                # Cancel waehrend des Sprechens/Gestikulierens wurde erst
                # nach dem natuerlichen Ende ueberhaupt bemerkt.
                exec_done = threading.Event()
                exec_result_holder = {}

                def _run_exec():
                    exec_result_holder["value"] = executor.execute(response_plan)
                    exec_done.set()

                exec_thread = threading.Thread(target=_run_exec, daemon=True)
                exec_thread.start()
                while not exec_done.wait(timeout=0.1):
                    if goal_handle.is_cancel_requested:
                        self.get_logger().info("RunDialogue-Cancel waehrend der Ausfuehrung -- "
                                                "aktive Say-/Gesture-Ziele werden abgebrochen.")
                        executor.cancel()
                        exec_done.wait(5.0)
                        break
                exec_result = exec_result_holder.get("value")
                if exec_result is None:
                    # Selbst nach der Cancel-Kulanzzeit noch nicht fertig --
                    # ehrlich als nicht bestaetigt behandeln, keine neuen
                    # Segmente/keine Erinnerung auf Basis eines unsicheren
                    # Zustands.
                    self.get_logger().warning(
                        "ResponsePlanExecutor nach Cancel nicht rechtzeitig bestaetigt.")
                    continue
                if not exec_result.success and not exec_result.cancelled:
                    self.get_logger().warn("ResponsePlanExecutor meldete einen Fehlschlag.")

                executed_gestures = _successfully_executed_gesture_names(response_plan, exec_result)
                recent_gestures.extend(executed_gestures)
                if recent_gesture_window > 0:
                    del recent_gestures[:-recent_gesture_window]  # nur die letzten N behalten
                else:
                    recent_gestures.clear()

                if memory_summary_candidate and person_context.get("known"):
                    self._write_memory_summary(session_id, memory_summary_candidate, question)

                feedback(DialogueState.WAITING_FOR_FOLLOWUP, "WAITING_FOR_FOLLOWUP")
        except Exception as e:
            self.get_logger().error(f"run_dialogue: unerwarteter Fehler: {e}")
            result.success = False
            result.final_state = "ERROR"
            result.error_message = str(e)
            goal_handle.abort()
            return result
        finally:
            # Entwicklungsauftrag 04-B, AP8.8, Abschnitt 4: gibt die in
            # _goal_callback() reservierte Einzelaktivitaet UNBEDINGT
            # wieder frei -- ueber JEDEN Rueckgabepfad (Erfolg, Cancel,
            # Fehler, Ausnahme), sonst wuerde nach der ERSTEN Sitzung nie
            # wieder ein RunDialogue-Ziel akzeptiert.
            with self._active_execution_lock:
                if self._active_session_id == session_id:
                    self._active_session_id = None

    def _finish(self, goal_handle, result, final_state, success, error="", feedback=None):
        """feedback() MUSS -- falls uebergeben -- vor goal_handle.succeed()/
        .abort() aufgerufen werden: ein bereits abgeschlossenes Ziel
        akzeptiert kein publish_feedback() mehr (Ergaenzungsauftrag
        04-A: PERSON_LOST/ENDING sollen als Live-Feedback sichtbar sein,
        nicht nur nachtraeglich in result.final_state)."""
        if feedback is not None:
            if final_state == "PERSON_LOST":
                feedback(DialogueState.PERSON_LOST, "PERSON_LOST")
            elif final_state in ("SESSION_TIMEOUT", "USER_STOP", "QUESTION_TIMEOUT"):
                # Nur die "geordnet zu Ende gegangenen" Faelle -- ein
                # SAFETY_EVENT/ERROR/CANCELLED ist kein geordnetes ENDING,
                # das wuerde eine ruhige Verabschiedung vortaeuschen, die
                # dort nicht stattfindet.
                feedback(DialogueState.ENDING, "ENDING")
        result.success = success
        result.final_state = final_state
        result.error_message = error
        if success:
            goal_handle.succeed()
        else:
            goal_handle.abort()
        return result

    # ---- Pipeline ----

    def _load_person_context(self, session_id) -> dict:
        if not self.get_person_context_client.wait_for_service(timeout_sec=2.0):
            return {"known": False, "display_name": None, "person_id": None}
        req = GetPersonContext.Request()
        req.person_id = session_id
        future = self.get_person_context_client.call_async(req)
        deadline = time.time() + 3.0
        while not future.done() and time.time() < deadline:
            time.sleep(0.02)
        if not future.done():
            return {"known": False, "display_name": None, "person_id": None}
        resp = future.result()
        return {
            "known": resp.known,
            "display_name": resp.display_name or None,
            "person_id": session_id if resp.known else None,
        }

    def _wait_for_question(self, goal_handle):
        self._latest_transcript_event.clear()
        self._voice_command = None
        timeout = self.get_parameter("question_timeout_s").value
        deadline = time.time() + timeout
        while time.time() < deadline:
            if goal_handle.is_cancel_requested:
                return None
            if self._voice_command is not None and is_hard_stop(self._voice_command):
                return "__STOP__"
            if self._latest_transcript_event.is_set():
                text = self._latest_transcript
                self._latest_transcript_event.clear()
                return text
            time.sleep(0.05)
        return None

    # ---- "Mhm"-/Denksequenz (Ergaenzungsauftrag 04-A) ----

    def _run_acknowledge_gesture(self):
        """Fire-and-forget kurzes Bestaetigungsnicken direkt nach dem
        Empfang einer Frage -- blockiert bewusst NICHT den Beginn der
        LLM-Pipeline (laeuft in einem eigenen Thread). system_only-Geste
        (acknowledge_nod_small.yaml), wird NIE von LLM 2 gewaehlt."""
        try:
            self._gesture_and_wait("acknowledge_nod_small", 1.0)
        except Exception as e:
            self.get_logger().warn(f"acknowledge_nod_small fehlgeschlagen: {e}")

    def _run_thinking_loop(self, stop_event: threading.Event, max_repetitions: int, max_total_duration_s: float):
        """Spielt thinking_loop_subtle.yaml wiederholt (je EIN Zyklus pro
        Aufruf, siehe dortiger Docstring), bis stop_event gesetzt ist
        ODER eine der beiden Obergrenzen erreicht wird. 'Unterbrechbar'
        heisst hier bewusst: stop_event wird NUR ZWISCHEN zwei Zyklen
        geprueft, nicht als Unterbrechung innerhalb eines einzelnen
        laufenden Aufrufs dieser Methode.

        Korrektur (Entwicklungsauftrag 04-B, AP8.8, Abschnitt 12): eine
        fruehere Fassung dieses Docstrings behauptete, PlayGesture
        unterstuetze GAR KEINE echte Unterbrechung waehrend der
        Ausfuehrung und bridge_node.py::_execute_gesture() pruefe
        goal_handle.is_cancel_requested ueberhaupt nicht -- das ist
        inzwischen falsch und wurde hier korrigiert. Tatsaechlich prueft
        _execute_gesture() goal_handle.is_cancel_requested in seiner
        Polling-Schleife und setzt bei einem Cancel ein cancel_event,
        das bis in gesture_catalog.py::_play_v1()/_play_v2() durch-
        gereicht wird und dort ZWISCHEN Keyframes/Segmenten abgefragt
        wird (echte Implementierung, kein Blindflug). Die verbleibende,
        ehrliche Einschraenkung ist eine andere: das ist Unterbrechung
        MIT Keyframe-/Segment-Granularitaet, kein hardwareseitig
        bestaetigtes Mid-Servo-Stop mitten in einer einzelnen
        Trajektorienbewegung -- diese feinere Garantie haengt von
        qicli/NAOqi ab und ist ohne echten Hardwaretest nicht
        nachweisbar (hwverificationrequired, siehe
        docs/DIALOGUE_GESTURE_LIFECYCLE.md)."""
        started_at = time.time()
        repetitions = 0
        while (
            not stop_event.is_set()
            and repetitions < max_repetitions
            and (time.time() - started_at) < max_total_duration_s
        ):
            try:
                self._gesture_and_wait("thinking_loop_subtle", 1.0)
            except Exception as e:
                self.get_logger().warn(f"thinking_loop_subtle fehlgeschlagen: {e}")
                return
            repetitions += 1

    def _acknowledge_and_run_pipeline(
        self, goal_handle, feedback, question, session_id, person_context, recent_gestures,
    ):
        """Orchestriert ACKNOWLEDGING -> (optional) WAITING_FOR_RESPONSE
        um die eigentliche _run_pipeline()-Ausfuehrung herum. Die
        LLM-Pipeline selbst laeuft dabei in einem eigenen Thread, damit
        hier parallel auf Zeitueberschreitung (Denkschleife starten) und
        Abbruch (Denkschleife stoppen) reagiert werden kann.

        Entwicklungsauftrag 04-B, AP8.8, Abschnitt 7 (bestaetigter Fund):
        ein Cancel waehrend der Pipeline wurde bisher NUR benutzt, um die
        Denkschleife zu stoppen -- der Aufrufer wartete danach TROTZDEM
        bis zum natuerlichen (moeglicherweise nicht abbrechbaren)
        Pipeline-Ende, BEVOR ueberhaupt wieder Kontrolle an _execute()
        zurueckging, dessen Cancel-Pruefung erst am Anfang der NAECHSTEN
        Schleifenrunde greift. Ein bereits fertiges response_plan aus
        einer solchen verspaeteten Rueckkehr haette _execute() dann
        TROTZDEM noch gesprochen/gestikuliert, bevor die Cancel-Pruefung
        ueberhaupt zum Zug kam. Jetzt: sobald ein Cancel erkannt wird,
        bricht diese Methode SOFORT (begrenzt) ab und liefert None --
        _execute() behandelt None bereits als 'Runde ueberspringen,
        sofort zur naechsten Schleifenpruefung' (die den Cancel dann
        korrekt erkennt). Der Pipeline-Thread laeuft im Hintergrund
        (daemon) weiter, falls der Provider selbst nicht abbrechbar ist
        (ehrlich dokumentiert, kein Vorspiegeln eines echten Provider-
        Cancels) -- sein Ergebnis wird nie wieder gelesen (pipeline_result
        ist eine frische, lokale Variable dieses Aufrufs).

        Ausserdem wird jetzt auch waehrend ACKNOWLEDGING/THINKING (nicht
        erst waehrend SPEAKING) sofort _cancel_active_actions() aufgerufen,
        damit eine noch laufende Bestaetigungsgeste bei einem Cancel
        tatsaechlich abgebrochen wird, statt unbeaufsichtigt weiterzulaufen."""
        feedback(DialogueState.ACKNOWLEDGING, "ACKNOWLEDGING", question)
        acknowledge_done = threading.Event()

        def _run_acknowledge():
            try:
                self._run_acknowledge_gesture()
            finally:
                acknowledge_done.set()

        acknowledge_thread = threading.Thread(target=_run_acknowledge, daemon=True)
        acknowledge_thread.start()

        feedback(DialogueState.THINKING, "THINKING", question)
        pipeline_result = {}
        pipeline_done = threading.Event()

        def _run():
            pipeline_result["value"] = self._run_pipeline(
                question, session_id, person_context, recent_gestures)
            pipeline_done.set()

        pipeline_thread = threading.Thread(target=_run, daemon=True)
        pipeline_thread.start()

        thinking_loop_stop = threading.Event()
        thinking_loop_thread = None
        loop_started = False
        deadline = time.time() + self.get_parameter("thinking_loop_delay_s").value
        cancelled = False

        while not pipeline_done.wait(timeout=0.05):
            if goal_handle.is_cancel_requested:
                cancelled = True
                thinking_loop_stop.set()
                self._cancel_active_actions()
                break
            if not loop_started and time.time() >= deadline:
                feedback(DialogueState.WAITING_FOR_RESPONSE, "WAITING_FOR_RESPONSE", question)
                thinking_loop_thread = threading.Thread(
                    target=self._run_thinking_loop,
                    args=(
                        thinking_loop_stop,
                        self.get_parameter("thinking_loop_max_repetitions").value,
                        self.get_parameter("thinking_loop_max_duration_s").value,
                    ),
                    daemon=True,
                )
                thinking_loop_thread.start()
                loop_started = True

        thinking_loop_stop.set()
        if thinking_loop_thread is not None:
            thinking_loop_thread.join(timeout=self.get_parameter("thinking_loop_max_duration_s").value + 2.0)
        if not acknowledge_done.wait(timeout=2.0):
            self.get_logger().warning(
                "acknowledge_nod_small nach Cancel/Timeout nicht rechtzeitig bestaetigt -- "
                "bleibt unbeaufsichtigt im Hintergrund nachverfolgt (daemon-Thread)."
            )

        if cancelled:
            # Bewusst KEIN pipeline_thread.join() auf das (evtl. nicht
            # abbrechbare) Pipeline-Ende -- der Thread laeuft im
            # Hintergrund weiter, sein Ergebnis wird nie mehr gelesen.
            return None

        pipeline_thread.join(timeout=1.0)  # sollte durch pipeline_done bereits fertig sein
        return pipeline_result.get("value")

    def _search_gestures(self, query: str, interaction_state: str, exclude_recent: list) -> list:
        """Entwicklungsauftrag 04-B, AP5A, Abschnitt 3: liefert bereits
        durch harte Sicherheitsfilter eingeschraenkte Kandidaten aus der
        Gesten-Vektordatenbank (list[GestureCandidate]). Bei
        deaktiviertem Service, fehlendem Server, Zeitueberschreitung
        oder einem Fehler: leere Liste -- KEINE Geste, die Antwort wird
        trotzdem gesprochen (siehe _run_pipeline())."""
        if not self.get_parameter("gesture_search.enabled").value:
            return []
        timeout_s = self.get_parameter("gesture_search.service_timeout_s").value
        if not self.search_gestures_client.wait_for_service(timeout_sec=timeout_s):
            self.get_logger().warn("search_gestures-Service nicht erreichbar -- keine Geste.")
            return []

        runtime_ctx = self._runtime_gesture_context()
        request = SearchGestures.Request()
        request.query = query
        request.interaction_state = interaction_state
        # Echte Laufzeitwerte (nicht nur ein platzhalterhaftes False) --
        # eine Geste, die JETZT sowieso gesperrt waere, wird LLM 2 gar
        # nicht erst angeboten (weniger nutzlose Vorschlaege, siehe
        # Auftrag Abschnitt 6, Regel 5 "Schnittmenge aus LLM-2-Auswahl
        # und weiterhin gueltigen Laufzeitbedingungen" -- hier bereits an
        # der Quelle vorweggenommen, der Recheck in Abschnitt 8 bleibt
        # trotzdem zusaetzlich bestehen, falls sich der Zustand zwischen
        # Suche und Ausfuehrung aendert).
        request.nav2_moving = runtime_ctx["nav2_moving"]
        request.mapping_active = runtime_ctx["mapping_active"]
        request.production_mode = False  # gesture_memory_node's eigener Node-Parameter bleibt die massgebliche Sperre
        request.minimum_tested_status = self.get_parameter(
            "gesture_search.minimum_tested_status_development").value
        request.max_duration_s = self.get_parameter("gesture_search.max_duration_s").value
        request.exclude_recent = list(exclude_recent)
        request.top_k = self.get_parameter("gesture_search.top_k").value
        request.include_system_only = False  # Auftrag Abschnitt 6, Regel 2

        future = self.search_gestures_client.call_async(request)
        deadline = time.time() + timeout_s
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            self.get_logger().warn("search_gestures: Zeitueberschreitung -- keine Geste.")
            return []
        try:
            response = future.result()
        except Exception as e:
            self.get_logger().warn(f"search_gestures: Fehler ({e}) -- keine Geste.")
            return []
        if not response.success:
            self.get_logger().warn(f"search_gestures meldete Fehlschlag: {response.message}")
            return []
        # Verteidigung in der Tiefe (Regel 2): system_only/nicht LLM-
        # waehlbare Kandidaten duerfen NIE hier ankommen
        # (include_system_only=False oben), werden aber zusaetzlich
        # clientseitig nochmal ausgeschlossen.
        return [c for c in response.candidates if not c.system_only and c.selectable_by_llm]

    def _run_pipeline(self, question, session_id, person_context, recent_gestures):
        """Gibt (ResponsePlan, memory_summary_candidate,
        gesture_recheck_context) zurueck, oder None bei einem
        Sicherheitsfehler (Sprache+Geste MUESSEN dann gemeinsam
        abbrechen, siehe ResponsePlanValidator-Regel 'safety_ok').

        gesture_recheck_context wird von _gesture_and_wait() unmittelbar
        vor jeder PlayGesture-Action nochmal konsultiert (Abschnitt 8) --
        zusaetzliche Schutzschicht, ersetzt nicht den spaeteren
        zentralen Aktuator-Arbiter (AP5B)."""
        interaction_state = "CONVERSATION_READY"
        knowledge_request = KnowledgePlanRequest(
            normalized_question=question.strip().lower(),
            person_context=PipelinePersonContext(
                known=person_context.get("known", False),
                display_name=person_context.get("display_name"),
                session_id=session_id,
            ),
            mode="faq",
        )
        knowledge_plan = run_knowledge_planner(self.knowledge_provider, knowledge_request)

        answer_brief = run_retrieval(
            knowledge_plan, question,
            faq_lookup_fn=self._faq_lookup,
            person_context=person_context,
        )

        # Entwicklungsauftrag 04-B, AP5A, Abschnitt 3: Suchanfrage NUR aus
        # bereits geprueften Daten -- keine Namen/Personen-IDs/Track-IDs/
        # vollstaendigen Personenakten.
        search_query_parts = [
            knowledge_plan.normalized_intent,
            question.strip(),
        ] + [f.text for f in answer_brief.facts[:2]]
        search_query = " ".join(p for p in search_query_parts if p).strip()

        database_candidates = self._search_gestures(
            search_query, interaction_state, exclude_recent=recent_gestures)

        # database_candidates (Auftrag Abschnitt 6): einzige Menge, aus
        # der LLM 2 waehlen darf.
        allowed_gesture_names = [c.name for c in database_candidates]
        gesture_options = [
            GestureOption(
                name=c.name, description=c.description, duration_s=c.duration_s,
                score=c.score, allowed_interaction_states=list(c.allowed_interaction_states),
            )
            for c in database_candidates
        ]
        gesture_request = GesturePlanRequest(
            answer_brief=answer_brief.question, robot_situation=interaction_state,
            allowed_gesture_names=allowed_gesture_names,
            gesture_options=gesture_options,
        )
        gesture_plan = run_gesture_planner(self.gesture_provider, gesture_request)

        # llm2_selected_gestures (Auftrag Abschnitt 6): NUR was LLM 2
        # tatsaechlich ausgewaehlt hat -- run_gesture_planner() hat das
        # bereits gegen allowed_gesture_names validiert (siehe
        # GesturePlanResponse.validate() in gesture_planner.py), ein
        # erfundener/nicht ausgewaehlter Name kann hier nicht mehr stehen.
        llm2_selected_gestures = [s.gesture_name for s in gesture_plan.suggestions]

        # LLM 3 darf AUSSCHLIESSLICH aus llm2_selected_gestures waehlen --
        # NICHT aus der vollen database_candidates-Menge (sonst koennte
        # LLM 3 einen von LLM 2 nie gewaehlten Datenbankkandidaten
        # nachtraeglich verwenden, Auftrag Abschnitt 6, Regel 4).
        response_plan = run_response_composer(
            self.response_provider, question, answer_brief, gesture_plan,
            llm2_selected_gestures, person_context=person_context,
        )

        head_gesture_names = {c.name for c in database_candidates if c.affects_head}
        allowed_interaction_states_for_gestures = {
            c.name: list(c.allowed_interaction_states) for c in database_candidates
        }

        runtime_ctx = self._runtime_gesture_context()
        plan_context = PlanContext(
            allowed_gesture_names=llm2_selected_gestures,
            current_interaction_state=interaction_state,
            allowed_interaction_states_for_gestures=allowed_interaction_states_for_gestures,
            safety_ok=self._safety_ok(),
            known_source_ids=answer_brief.source_ids(),
            nav2_moving=runtime_ctx["nav2_moving"],
            mapping_active=runtime_ctx["mapping_active"],
            gesture_in_progress=runtime_ctx["gesture_in_progress"],
            pepper_reachable=runtime_ctx["pepper_reachable"],
            tts_available=self._tts_available(),
            head_gesture_names=list(head_gesture_names),
        )
        validation = ResponsePlanValidator().validate(response_plan, plan_context)
        if not validation.valid:
            self.get_logger().warn(f"ResponsePlan abgelehnt: {validation.errors}")
            if not plan_context.safety_ok or not plan_context.tts_available:
                return None  # Sicherheitsfehler: Sprache+Geste gemeinsam abbrechen
            # sonst: einfache saetze aus dem AnswerBrief als sicherer Fallback,
            # NIE mit Geste (Auftrag Abschnitt 6, Regel 7: leere Auswahl
            # bzw. verworfener Plan -> Pepper spricht ohne Geste).
            from ihk_pepper_llm_contracts.response_plan import ResponsePlan, ResponseSegment
            fallback_segments = [
                ResponseSegment(segment_id=f"safe_{i}", text=prepare_for_speech(f.text, 400)[0])
                for i, f in enumerate(answer_brief.facts)
            ] or [ResponseSegment(segment_id="safe_no_info",
                                   text="Dazu habe ich aktuell keine verlaessliche Information.")]
            response_plan = ResponsePlan(segments=fallback_segments, source_ids=answer_brief.source_ids())
            final_allowlist = set()
        else:
            # endgueltige Allowlist (Auftrag Abschnitt 6, Regel 5): nur
            # Segmente, die der Validator TATSAECHLICH akzeptiert hat,
            # sind noch mit einer Geste verknuepft -- ein abgelehntes
            # Segment behaelt keinen gesture_name im validierten Plan
            # (der Validator laesst den Plan nur durchgehen, wenn ALLE
            # Regeln erfuellt sind; ein zurueckgewiesener gesture_name
            # bedeutet also, dass validation.valid bereits False waere).
            final_allowlist = {
                seg.gesture_name for seg in response_plan.segments if seg.gesture_name
            }

        self.get_logger().debug(
            f"Gesten-Datenfluss: {len(database_candidates)} Kandidaten -> "
            f"{len(llm2_selected_gestures)} von LLM 2 gewaehlt -> "
            f"{len(final_allowlist)} endgueltig ausfuehrbar."
        )

        gesture_recheck_context = {
            "final_allowlist": final_allowlist,
            "head_gesture_names": {n for n in final_allowlist if n in head_gesture_names},
            "allowed_interaction_states_for_gestures": allowed_interaction_states_for_gestures,
            "current_interaction_state": interaction_state,
        }
        return response_plan, response_plan.memory_summary_candidate, gesture_recheck_context

    def _faq_lookup(self, query, mode):
        if mode == "exact":
            return self.faq.lookup_exact(query)
        return self.faq.lookup_semantic(query)

    def _write_memory_summary(self, session_id, summary_text, question):
        if not self.write_memory_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().warn("write_memory_summary-Service nicht erreichbar -- nicht gespeichert.")
            return
        req = WriteMemorySummary.Request()
        req.person_id = session_id
        req.session_id = session_id
        req.source = "dialog_session"
        req.topics = [question[:64]]
        req.summary = summary_text
        req.sources = []
        req.valid_until_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 180 * 86400))
        future = self.write_memory_client.call_async(req)
        deadline = time.time() + 3.0
        while not future.done() and time.time() < deadline:
            time.sleep(0.02)

    # ---- blockierende Action-Aufrufe (Muster wie presentation_manager_node::_say_and_wait) ----

    def _tts_available(self) -> bool:
        """Nicht-blockierende Verfuegbarkeitspruefung fuer die Say-Action
        (Entwicklungsauftrag 04-B, AP5A, Abschnitt 4) -- geht in
        PlanContext.tts_available ein, dessen Fehlen den GESAMTEN Plan
        blockiert (nicht nur Gestensegmente)."""
        return self.say_client.server_is_ready()

    def _recheck_before_gesture(self, gesture_name: str) -> bool:
        """Entwicklungsauftrag 04-B, AP5A, Abschnitt 8: erneute Pruefung
        UNMITTELBAR vor jeder PlayGesture-Action -- der Systemzustand
        kann sich zwischen Vektorsuche/Planung und Ausfuehrung geaendert
        haben. Zusaetzliche Schutzschicht, ERSETZT NICHT den spaeteren
        zentralen Aktuator-Arbiter (AP5B)."""
        if not self._safety_ok():
            self.get_logger().warn(f"Geste '{gesture_name}' abgelehnt: SafetyState nicht ok/veraltet.")
            return False
        runtime_ctx = self._runtime_gesture_context()
        if runtime_ctx["nav2_moving"]:
            self.get_logger().warn(f"Geste '{gesture_name}' abgelehnt: Nav2 faehrt (oder Signal veraltet).")
            return False
        if runtime_ctx["gesture_in_progress"]:
            self.get_logger().warn(
                f"Geste '{gesture_name}' abgelehnt: bereits eine Geste aktiv (oder Signal veraltet).")
            return False
        if not runtime_ctx["pepper_reachable"]:
            self.get_logger().warn(f"Geste '{gesture_name}' abgelehnt: Pepper nicht erreichbar (oder unbekannt).")
            return False

        recheck_ctx = self._current_gesture_recheck_context
        if recheck_ctx is not None:
            # Thematische (LLM-ausgewaehlte) Geste -- muss weiterhin in
            # der endgueltigen Allowlist stehen (Abschnitt 6, Regel 5/6).
            if gesture_name not in recheck_ctx["final_allowlist"]:
                self.get_logger().warn(
                    f"Geste '{gesture_name}' abgelehnt: nicht (mehr) in der endgueltigen Allowlist.")
                return False
            if runtime_ctx["mapping_active"] and gesture_name in recheck_ctx["head_gesture_names"]:
                self.get_logger().warn(f"Geste '{gesture_name}' abgelehnt: Mapping aktiv, Kopfgeste gesperrt.")
                return False
            allowed_states = recheck_ctx["allowed_interaction_states_for_gestures"].get(gesture_name)
            if allowed_states and recheck_ctx["current_interaction_state"] not in allowed_states:
                self.get_logger().warn(f"Geste '{gesture_name}' abgelehnt: Interaktionszustand nicht mehr erlaubt.")
                return False
        else:
            # Systemgeste ("Mhm"/Denkschleife) -- keine LLM-Allowlist,
            # aber beide bewegen den Kopf, die Mapping-Sperre gilt trotzdem.
            if runtime_ctx["mapping_active"] and gesture_name in SYSTEM_GESTURES_AFFECTING_HEAD:
                self.get_logger().warn(f"Systemgeste '{gesture_name}' abgelehnt: Mapping aktiv.")
                return False
        return True

    def _say_and_wait(self, text: str) -> bool:
        spoken, _full_text, _truncated = prepare_for_speech(text, 400)
        if not self.say_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("Say-Action nicht erreichbar.")
            return False
        goal = Say.Goal()
        goal.text = spoken
        goal.allow_interrupt = True
        goal.max_duration_s = 0.0
        return self._send_goal_and_wait(
            self.say_client, goal, timeout_s=30.0, active_goal_attr="_active_say_goal_handle")

    def _gesture_and_wait(self, gesture_name: str, speed_scale: float) -> bool:
        if not self._recheck_before_gesture(gesture_name):
            return False
        if not self.gesture_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("PlayGesture-Action nicht erreichbar.")
            return False
        goal = PlayGesture.Goal()
        goal.gesture_name = gesture_name
        goal.speed_scale = speed_scale
        return self._send_goal_and_wait(
            self.gesture_client, goal, timeout_s=15.0, active_goal_attr="_active_gesture_goal_handle")

    def _send_goal_and_wait(self, client, goal, timeout_s: float, active_goal_attr: str = None) -> bool:
        """Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: speichert den
        angenommenen Goal-Handle (active_goal_attr, falls angegeben --
        siehe _cancel_active_actions()) und ruft bei EIGENEM Timeout
        tatsaechlich cancel_goal_async() auf, statt das Ziel einfach
        unbeaufsichtigt weiterlaufen zu lassen. Wartet danach begrenzt
        (nicht unbegrenzt) auf eine Cancel-Bestaetigung.

        Entwicklungsauftrag 04-B, AP8.8, Abschnitt 3.3/7 (bestaetigter
        Fund): trifft die Goal-Acceptance ERST NACH dem eigenen Timeout
        ein (goal_state["handle"] war zu diesem Zeitpunkt noch None),
        setzte das SPAETER eintreffende on_goal_response() active_goal_attr
        TROTZDEM -- ohne Pruefung, ob inzwischen ein ANDERER, neuer Aufruf
        (z.B. das naechste Segment) bereits SEINEN eigenen Handle dort
        abgelegt hat. Ein solcher verspaeteter Callback konnte damit den
        Handle eines fremden, noch aktiven Aufrufs ueberschreiben (oder der
        eigene finally-Block eines laengst aufgegebenen Aufrufs konnte
        umgekehrt den Handle des naechsten, echten Aufrufs wieder loeschen).
        Ein Call-Token pro _send_goal_and_wait()-Aufruf bindet jetzt JEDE
        Schreib-/Loeschoperation auf active_goal_attr an genau DIESEN
        Aufruf (self._active_goal_tokens[active_goal_attr] muss auf den
        eigenen Token zeigen) -- ein fremder/veralteter Aufruf kann den
        Attributwert nie mehr beruehren. Eine NACH dem eigenen Timeout
        verspaetet eintreffende Annahme wird ausserdem sofort storniert
        (keine normale Fortsetzung), ihr Ergebnis wird nur noch
        konsumiert, nie mehr verwendet."""
        done = threading.Event()
        outcome = {"success": False}
        goal_state = {"handle": None}
        abandoned = threading.Event()
        call_token = object()

        def _release_if_owner():
            if active_goal_attr and self._active_goal_tokens.get(active_goal_attr) is call_token:
                setattr(self, active_goal_attr, None)
                self._active_goal_tokens.pop(active_goal_attr, None)

        def on_result(fut):
            try:
                outcome["success"] = fut.result().result.success
            except Exception as e:
                self.get_logger().warn(f"Action-Ergebnis nicht abrufbar: {e}")
            done.set()
            _release_if_owner()

        def on_goal_response(fut):
            gh = fut.result()
            if not gh.accepted:
                done.set()
                return
            goal_state["handle"] = gh
            if abandoned.is_set():
                # Verspaetete Annahme NACH eigenem Timeout -- das Ziel
                # sofort stornieren, KEINE normale Fortsetzung, NIE
                # active_goal_attr beruehren (koennte einem inzwischen
                # neu gestarteten, fremden Aufruf gehoeren).
                self.get_logger().warning(
                    "Verspaetete Goal-Acceptance nach eigenem Timeout -- Ziel wird sofort storniert."
                )
                try:
                    gh.cancel_goal_async()
                except Exception:
                    self.get_logger().warning(
                        "Stornierung des verspaetet angenommenen Ziels fehlgeschlagen.", exc_info=True)
                gh.get_result_async()  # terminales Ergebnis wird weiterhin konsumiert, nie mehr verwendet
                return
            if active_goal_attr:
                setattr(self, active_goal_attr, gh)
                self._active_goal_tokens[active_goal_attr] = call_token
            rf = gh.get_result_async()
            rf.add_done_callback(on_result)

        send_future = client.send_goal_async(goal)
        send_future.add_done_callback(on_goal_response)
        try:
            if done.wait(timeout_s):
                return outcome["success"]
            abandoned.set()
            self.get_logger().warn(
                "Action-Aufruf hat das Timeout ueberschritten -- Cancel wird angefordert.")
            gh = goal_state["handle"]
            if gh is not None:
                try:
                    gh.cancel_goal_async()
                except Exception:
                    self.get_logger().warning("cancel_goal_async() fehlgeschlagen.", exc_info=True)
                # Begrenzt auf eine Cancel-Bestaetigung warten -- kein
                # unbegrenztes Blockieren mehr.
                done.wait(2.0)
            return False
        finally:
            _release_if_owner()

    def _cancel_active_actions(self):
        """Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: von
        ResponsePlanExecutor.cancel() SOFORT aufgerufen -- bricht das
        GERADE LAUFENDE Say-/PlayGesture-Ziel aktiv ab, statt passiv auf
        die naechste Segmentgrenze zu warten."""
        for gh in (self._active_say_goal_handle, self._active_gesture_goal_handle):
            if gh is not None:
                try:
                    gh.cancel_goal_async()
                except Exception:
                    self.get_logger().warning("Aktives Ziel konnte nicht abgebrochen werden.", exc_info=True)


def _try_parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _successfully_executed_gesture_names(response_plan, exec_result) -> list:
    """Entwicklungsauftrag 04-B, AP5A, Abschnitt 7: welche Gesten aus
    einem ResponsePlan tatsaechlich erfolgreich ausgefuehrt wurden --
    fuer den Wiederholungsschutz (recent_gestures). SegmentExecutionResult
    traegt selbst keinen gesture_name, daher hier ueber segment_id mit
    dem urspruenglichen Plan verknuepft."""
    segments_by_id = {seg.segment_id: seg for seg in response_plan.segments}
    names = []
    for seg_result in exec_result.segment_results:
        segment = segments_by_id.get(seg_result.segment_id)
        if segment is not None and segment.gesture_name and seg_result.gesture_success:
            names.append(segment.gesture_name)
    return names


def main(args=None):
    # Reihenfolge wichtig, siehe build_faq_cache()/dialog_manager_node.py:
    # sentence-transformers/torch MUSS vor rclpy.init() geladen werden.
    default_db = os.path.expanduser("~/.ihk_pepper/faq_cache.sqlite")
    faq_db_path = os.environ.get("PEPPER_FAQ_DB_PATH", default_db)
    faq_cache = build_faq_cache(faq_db_path)

    rclpy.init(args=args)
    node = RunDialogueActionServer(faq_cache)
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.faq.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
