#!/usr/bin/env python3
"""
ihk_pepper_dialog: verbindet den vollstaendigen Kreislauf
Audio-Transkript -> FAQ-Cache -> AnythingLLM-Fallback -> TTS-Aufbereitung
-> Say-Action -> zurueck zum Zuhoeren (Arbeitspaket 11).

Getestet (2026-08-19/20): FAQ-Cache (exakt+semantisch), TTS-Sanitizer,
State-Transitions per Unit-/Integrationstest mit einem AnythingLLM-Mock
(siehe ihk_pepper_tests). NICHT gegen eine echte laufende AnythingLLM-
Instanz getestet (auf diesem Rechner nicht erreichbar in dieser Session,
siehe docs/IMPLEMENTATION_REPORT.md) -- der Health-Check/Fallback-Pfad wurde
aber explizit fuer genau diesen Fall (Instanz nicht erreichbar) getestet
und funktioniert.
"""
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from std_msgs.msg import String

from ihk_pepper_interfaces.msg import DialogueState
from ihk_pepper_interfaces.action import Say
from ihk_pepper_interfaces.srv import CancelInteraction, ReloadKnowledge

from .anythingllm_client import RobustAnythingLLMClient, AnythingLLMError
from .faq_cache import FaqCache
from .session_memory import SessionManager
from .tts_sanitizer import prepare_for_speech

FALLBACK_ANSWER = "Dazu habe ich aktuell keine verlässliche Information."

def _find_flask_wrapper_path() -> str:
    """Siehe ihk_pepper_bridge/pepper_client.py::_find_flask_wrapper_path()
    -- bewusst eigenstaendige Kopie. PEPPER_FLASK_WRAPPER_PATH hat
    Vorrang, sonst wird 'apps/web' vom eigenen Verzeichnis aus nach oben
    gesucht (Entwicklungsauftrag 04-B, AP0: keine absoluten
    Entwicklerpfade im Laufzeitcode)."""
    env_value = os.environ.get("PEPPER_FLASK_WRAPPER_PATH")
    if env_value:
        return env_value
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(12):
        candidate = os.path.join(current, "apps", "web")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RuntimeError(
        "PEPPER_FLASK_WRAPPER_PATH ist nicht gesetzt und 'apps/web' wurde "
        "beim automatischen Suchen nicht gefunden -- bei getrennter "
        "Installation muss PEPPER_FLASK_WRAPPER_PATH explizit gesetzt werden."
    )


_FLASK_WRAPPER_PATH = _find_flask_wrapper_path()


def _load_web_app_config():
    import sys
    if _FLASK_WRAPPER_PATH not in sys.path:
        sys.path.insert(0, _FLASK_WRAPPER_PATH)
    import config.config as _cfg
    return _cfg


def build_faq_cache(db_path: str):
    """WICHTIG: MUSS vor rclpy.init() aufgerufen werden (siehe main()).
    Das Laden von sentence-transformers/torch NACH einem bereits
    existierenden rclpy-Node/-Context fuehrt reproduzierbar zu
    'RCLError: rcl node's context is invalid' bei der naechsten
    create_subscription/create_publisher-Aufruf -- vermutlich ein
    Fork-/Thread-Seiteneffekt der ML-Bibliotheken. Gefunden und verifiziert
    in dieser Session, siehe docs/IMPLEMENTATION_REPORT.md."""
    return FaqCache(db_path)


class DialogManagerNode(Node):
    def __init__(self, faq_cache: FaqCache, llm_client: RobustAnythingLLMClient):
        super().__init__("dialog_manager")

        self.declare_parameter("semantic_threshold", 0.75)
        self.declare_parameter("max_speech_chars", 400)
        self.declare_parameter("session_timeout_s", 120.0)
        self.declare_parameter("session_max_messages", 10)
        self.declare_parameter("allow_llm_fallback", True)

        self.llm = llm_client
        self.faq = faq_cache
        self.sessions = SessionManager(
            max_messages=self.get_parameter("session_max_messages").value,
            timeout_s=self.get_parameter("session_timeout_s").value,
        )

        self._state = DialogueState.LISTENING
        self._current_session = None
        self._active_say_goal_handle = None

        self.create_subscription(String, "/audio_node/transcript", self._on_transcript, 10)
        self.create_subscription(String, "/audio_node/voice_command", self._on_voice_command, 10)

        self.state_pub = self.create_publisher(DialogueState, "dialogue_state", 10)
        self.create_timer(1.0, self._publish_state)
        self.create_timer(10.0, self._cleanup_sessions)

        self.say_client = ActionClient(self, Say, "/pepper_bridge/say")

        self.cancel_srv = self.create_service(
            CancelInteraction, "cancel_interaction", self._handle_cancel
        )
        self.reload_srv = self.create_service(
            ReloadKnowledge, "reload_knowledge", self._handle_reload
        )

        self.get_logger().info(
            f"dialog_manager gestartet. FAQ-Eintraege: {self.faq.reload_count()}, "
            f"Embedding-Backend: {self.faq.embedding_backend.name}"
        )

    # ---- Zustands-Hilfsfunktionen ----

    def _set_state(self, state, transcript="", response="", error=""):
        self._state = state
        self._last_transcript = transcript or getattr(self, "_last_transcript", "")
        self._last_response = response or getattr(self, "_last_response", "")
        self._last_error = error

    def _publish_state(self):
        msg = DialogueState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.state = self._state
        msg.state_name = {
            DialogueState.WAITING_FOR_WAKEWORD: "WAITING_FOR_WAKEWORD",
            DialogueState.LISTENING: "LISTENING",
            DialogueState.TRANSCRIBING: "TRANSCRIBING",
            DialogueState.RETRIEVING: "RETRIEVING",
            DialogueState.THINKING: "THINKING",
            DialogueState.SPEAKING: "SPEAKING",
            DialogueState.WAITING_FOR_FOLLOWUP: "WAITING_FOR_FOLLOWUP",
            DialogueState.CANCELLED: "CANCELLED",
            DialogueState.ERROR: "ERROR",
        }.get(self._state, "UNKNOWN")
        msg.session_id = self._current_session.session_id if self._current_session else ""
        msg.last_transcript = getattr(self, "_last_transcript", "")
        msg.last_response = getattr(self, "_last_response", "")
        msg.error_message = getattr(self, "_last_error", "")
        self.state_pub.publish(msg)

    def _cleanup_sessions(self):
        self.sessions.cleanup_expired()

    # ---- Voice Commands (Stopp etc, siehe ihk_pepper_audio/cancel_words.py) ----

    def _on_voice_command(self, msg: String):
        command = msg.data
        if command in ("stop", "cancel"):
            self._cancel_current("voice_command")
        # repeat/volume_up/volume_down/quiet: fuer diese Session bewusst
        # nur protokolliert, keine vollstaendige Umsetzung (siehe Bericht)
        self.get_logger().info(f"Sprachbefehl erkannt: {command}")

    def _cancel_current(self, reason: str):
        if self._active_say_goal_handle is not None:
            self._active_say_goal_handle.cancel_goal_async()
        self._set_state(DialogueState.CANCELLED, error=reason)
        self.get_logger().info(f"Interaktion abgebrochen: {reason}")
        self._set_state(DialogueState.LISTENING)

    def _handle_cancel(self, request, response):
        self._cancel_current(request.reason or "service_call")
        response.success = True
        response.message = "abgebrochen"
        return response

    def _handle_reload(self, request, response):
        try:
            count = self.faq.reload_count()
            response.success = True
            response.faq_entries_loaded = count
            response.message = "OK"
        except Exception as e:
            response.success = False
            response.faq_entries_loaded = 0
            response.message = str(e)
        return response

    # ---- Kern-Dialogschleife ----

    def _on_transcript(self, msg: String):
        text = msg.data.strip()
        if not text:
            return

        if self._current_session is None or self.sessions.get_active() is None:
            self._current_session = self.sessions.start_session()

        self._set_state(DialogueState.TRANSCRIBING, transcript=text)
        self._current_session.add("user", text)

        self._set_state(DialogueState.RETRIEVING, transcript=text)
        t0 = time.time()
        answer, source, confidence = self._retrieve_answer(text)
        latency = time.time() - t0

        self.faq.log_question(text, source, confidence, latency)

        self._current_session.add("assistant", answer)
        self._set_state(DialogueState.SPEAKING, response=answer)
        self._speak(answer)
        self._set_state(DialogueState.WAITING_FOR_FOLLOWUP)

    def _retrieve_answer(self, text: str):
        """Reihenfolge gemaess Auftrag Abschnitt 16:
        1. Exakter Treffer  2. Semantischer Treffer  3. LLM  4. Fallback."""
        hit = self.faq.lookup_exact(text)
        if hit:
            return hit["answer"], "exact_match", hit["confidence"]

        hit = self.faq.lookup_semantic(text, threshold=self.get_parameter("semantic_threshold").value)
        if hit:
            return hit["answer"], "semantic_match", hit["confidence"]

        if self.get_parameter("allow_llm_fallback").value:
            self._set_state(DialogueState.THINKING, transcript=text)
            context = self._current_session.as_context_string() if self._current_session else ""
            prompt = f"{context}\nNutzer: {text}" if context else text
            try:
                answer = self.llm.ask(prompt)
                self.faq.add_candidate(text, answer, model="anythingllm")
                return answer, "llm", 0.5
            except AnythingLLMError as e:
                self.get_logger().warn(f"AnythingLLM-Fallback fehlgeschlagen: {e}")

        return FALLBACK_ANSWER, "fallback", 0.0

    def _speak(self, text: str):
        max_chars = self.get_parameter("max_speech_chars").value
        spoken, full_text, truncated = prepare_for_speech(text, max_chars)
        if truncated:
            self.get_logger().info("Antwort fuer Sprachausgabe gekuerzt, Volltext waere fuers Tablet gedacht.")

        if not self.say_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error(
                "Say-Action (ihk_pepper_bridge) nicht erreichbar -- "
                "Antwort wird nur geloggt, nicht gesprochen."
            )
            return

        goal = Say.Goal()
        goal.text = spoken
        goal.allow_interrupt = True
        goal.max_duration_s = 0.0

        future = self.say_client.send_goal_async(goal)
        future.add_done_callback(self._on_say_goal_response)

    def _on_say_goal_response(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn("Say-Ziel abgelehnt")
            return
        self._active_say_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_say_result)

    def _on_say_result(self, future):
        self._active_say_goal_handle = None
        try:
            result = future.result().result
            if not result.success:
                self.get_logger().warn(f"Say fehlgeschlagen: {result.error_message}")
        except Exception as e:
            self.get_logger().warn(f"Say-Ergebnis nicht abrufbar: {e}")


def main(args=None):
    # Reihenfolge ist wichtig, siehe Kommentar an build_faq_cache():
    # ALLES was sentence-transformers/torch laedt MUSS vor rclpy.init()
    # passieren.
    # ~/.ihk_pepper statt install/-Ordner: die FAQ-DB waechst zur Laufzeit
    # (Nutzungszaehler, question_log, answer_candidates) und soll einen
    # colcon build/rm -rf install nicht als Datenverlust erleben.
    default_db = os.path.expanduser("~/.ihk_pepper/faq_cache.sqlite")
    faq_db_path = os.environ.get("PEPPER_FAQ_DB_PATH", default_db)
    faq_cache = build_faq_cache(faq_db_path)

    cfg = _load_web_app_config()
    llm_client = RobustAnythingLLMClient(
        base_url=os.environ.get("ANYTHINGLLM_API_BASE_URL", cfg.API_BASE_URL),
        api_token=os.environ.get("ANYTHINGLLM_API_TOKEN", cfg.API_TOKEN),
        workspace=os.environ.get("ANYTHINGLLM_WORKSPACE", getattr(cfg, "ANYTHINGLLM_WORKSPACE", "")),
    )

    rclpy.init(args=args)
    node = DialogManagerNode(faq_cache, llm_client)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.faq.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
