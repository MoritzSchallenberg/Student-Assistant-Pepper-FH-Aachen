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
from ihk_pepper_interfaces.srv import GetPersonContext, WriteMemorySummary

from ihk_pepper_llm_contracts.gesture_planner import GesturePlanRequest
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

from .faq_cache import FaqCache
from .response_plan_executor import ResponsePlanExecutor
from .tts_sanitizer import prepare_for_speech

DEFAULT_SESSION_TIMEOUT_S = 180.0
DEFAULT_QUESTION_TIMEOUT_S = 20.0
MAX_TRACK_AGE_S = 2.0


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
        self._latest_transcript = None
        self._latest_transcript_event = threading.Event()
        self._voice_command = None

        cb_group = ReentrantCallbackGroup()

        self.create_subscription(PersonTrackArray, "/perception_node/person_tracks",
                                  self._on_tracks, 10)
        self.create_subscription(SafetyState, "/safety_state", self._on_safety_state, 10)
        self.create_subscription(String, "/audio_node/transcript", self._on_transcript, 10)
        self.create_subscription(String, "/audio_node/voice_command", self._on_voice_command, 10)

        self.speaking_pub = self.create_publisher(Bool, "speaking", 10)
        self.dialogue_state_pub = self.create_publisher(DialogueState, "dialogue_state", 10)

        self.say_client = ActionClient(self, Say, "/pepper_bridge/say", callback_group=cb_group)
        self.gesture_client = ActionClient(
            self, PlayGesture, "/pepper_bridge/play_gesture", callback_group=cb_group)
        self.get_person_context_client = self.create_client(
            GetPersonContext, "/get_person_context", callback_group=cb_group)
        self.write_memory_client = self.create_client(
            WriteMemorySummary, "/write_memory_summary", callback_group=cb_group)

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

    def _on_transcript(self, msg: String):
        self._latest_transcript = msg.data
        self._latest_transcript_event.set()

    def _on_voice_command(self, msg: String):
        self._voice_command = detect_command(msg.data)

    def _track_alive(self, track_id) -> bool:
        entry = self._tracks.get(track_id)
        if entry is None:
            return False
        _, received_at = entry
        return (time.time() - received_at) <= MAX_TRACK_AGE_S

    def _safety_ok(self) -> bool:
        if self._safety_state is None:
            return False
        return not self._safety_state.emergency_stop and not self._safety_state.bumper_active

    # ---- Action-Server-Callbacks ----

    def _goal_callback(self, goal_request):
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
        )

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

                plan_context = self._acknowledge_and_run_pipeline(
                    goal_handle, feedback, question, session_id, person_context)
                if plan_context is None:
                    continue  # Sicherheitsfehler -- Segment/Runde ueberspringen, Session laeuft weiter

                response_plan, memory_summary_candidate = plan_context
                feedback(DialogueState.SPEAKING, "SPEAKING")
                exec_result = executor.execute(response_plan)
                if not exec_result.success and not exec_result.cancelled:
                    self.get_logger().warn("ResponsePlanExecutor meldete einen Fehlschlag.")

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
        geprueft, NICHT mitten in einer laufenden Trajektorie --
        PlayGesture unterstuetzt aktuell keine echte Unterbrechung
        waehrend der Ausfuehrung (bridge_node.py::_execute_gesture()
        prueft goal_handle.is_cancel_requested nicht), das wird hier
        bewusst nicht faelschlich behauptet."""
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

    def _acknowledge_and_run_pipeline(self, goal_handle, feedback, question, session_id, person_context):
        """Orchestriert ACKNOWLEDGING -> (optional) WAITING_FOR_RESPONSE
        um die eigentliche _run_pipeline()-Ausfuehrung herum. Die
        LLM-Pipeline selbst laeuft dabei in einem eigenen Thread, damit
        hier parallel auf Zeitueberschreitung (Denkschleife starten) und
        Abbruch (Denkschleife stoppen) reagiert werden kann -- ein
        Abbruch waehrend der Pipeline stoppt HIER NUR die sichtbare
        Zwischen-Geste, NICHT den laufenden LLM-Aufruf selbst (die
        Pipeline-Stufen haben keinen eigenen Abbruch-Haken, siehe
        pipeline.py) -- die eigentliche Sitzungsbeendigung erfolgt wie
        bisher erst am Anfang der naechsten Schleifenrunde in _execute()."""
        feedback(DialogueState.ACKNOWLEDGING, "ACKNOWLEDGING", question)
        threading.Thread(target=self._run_acknowledge_gesture, daemon=True).start()

        feedback(DialogueState.THINKING, "THINKING", question)
        pipeline_result = {}
        pipeline_done = threading.Event()

        def _run():
            pipeline_result["value"] = self._run_pipeline(question, session_id, person_context)
            pipeline_done.set()

        pipeline_thread = threading.Thread(target=_run, daemon=True)
        pipeline_thread.start()

        thinking_loop_stop = threading.Event()
        thinking_loop_thread = None
        loop_started = False
        deadline = time.time() + self.get_parameter("thinking_loop_delay_s").value

        while not pipeline_done.wait(timeout=0.05):
            if goal_handle.is_cancel_requested:
                thinking_loop_stop.set()
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
        pipeline_thread.join(timeout=1.0)  # sollte durch pipeline_done bereits fertig sein

        return pipeline_result.get("value")

    def _run_pipeline(self, question, session_id, person_context):
        """Gibt (ResponsePlan, memory_summary_candidate) zurueck, oder
        None bei einem Sicherheitsfehler (Sprache+Geste MUESSEN dann
        gemeinsam abbrechen, siehe ResponsePlanValidator-Regel 'safety_ok')."""
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

        allowed_gesture_names = []  # AP12/13 wiring liefert die echte Allowlist
        gesture_request = GesturePlanRequest(
            answer_brief=answer_brief.question, robot_situation="CONVERSATION_READY",
            allowed_gesture_names=allowed_gesture_names,
        )
        gesture_plan = run_gesture_planner(self.gesture_provider, gesture_request)

        response_plan = run_response_composer(
            self.response_provider, question, answer_brief, gesture_plan,
            allowed_gesture_names, person_context=person_context,
        )

        plan_context = PlanContext(
            allowed_gesture_names=allowed_gesture_names,
            current_interaction_state="CONVERSATION_READY",
            safety_ok=self._safety_ok(),
            known_source_ids=answer_brief.source_ids(),
        )
        validation = ResponsePlanValidator().validate(response_plan, plan_context)
        if not validation.valid:
            self.get_logger().warn(f"ResponsePlan abgelehnt: {validation.errors}")
            if not plan_context.safety_ok:
                return None  # Sicherheitsfehler: Sprache+Geste gemeinsam abbrechen
            # sonst: einfache saetze aus dem AnswerBrief als sicherer Fallback
            from ihk_pepper_llm_contracts.response_plan import ResponsePlan, ResponseSegment
            fallback_segments = [
                ResponseSegment(segment_id=f"safe_{i}", text=prepare_for_speech(f.text, 400)[0])
                for i, f in enumerate(answer_brief.facts)
            ] or [ResponseSegment(segment_id="safe_no_info",
                                   text="Dazu habe ich aktuell keine verlaessliche Information.")]
            response_plan = ResponsePlan(segments=fallback_segments, source_ids=answer_brief.source_ids())

        return response_plan, response_plan.memory_summary_candidate

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

    def _say_and_wait(self, text: str) -> bool:
        spoken, _full_text, _truncated = prepare_for_speech(text, 400)
        if not self.say_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("Say-Action nicht erreichbar.")
            return False
        goal = Say.Goal()
        goal.text = spoken
        goal.allow_interrupt = True
        goal.max_duration_s = 0.0
        return self._send_goal_and_wait(self.say_client, goal, timeout_s=30.0)

    def _gesture_and_wait(self, gesture_name: str, speed_scale: float) -> bool:
        if not self.gesture_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("PlayGesture-Action nicht erreichbar.")
            return False
        goal = PlayGesture.Goal()
        goal.gesture_name = gesture_name
        goal.speed_scale = speed_scale
        return self._send_goal_and_wait(self.gesture_client, goal, timeout_s=15.0)

    def _send_goal_and_wait(self, client, goal, timeout_s: float) -> bool:
        done = threading.Event()
        outcome = {"success": False}

        def on_result(fut):
            try:
                outcome["success"] = fut.result().result.success
            except Exception as e:
                self.get_logger().warn(f"Action-Ergebnis nicht abrufbar: {e}")
            done.set()

        def on_goal_response(fut):
            gh = fut.result()
            if not gh.accepted:
                done.set()
                return
            rf = gh.get_result_async()
            rf.add_done_callback(on_result)

        send_future = client.send_goal_async(goal)
        send_future.add_done_callback(on_goal_response)
        if not done.wait(timeout_s):
            self.get_logger().warn("Action-Aufruf hat das Timeout ueberschritten.")
            return False
        return outcome["success"]


def _try_parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
