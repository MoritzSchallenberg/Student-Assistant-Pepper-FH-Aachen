#!/usr/bin/env python3
"""
ihk_pepper_presentation: Tagesthema + Praesentationsbetrieb
(Arbeitspaket 17-19).

Ablauf (Abschnitt 19, 10 Schritte) als PlayPresentation-ActionServer:
    auswaehlen -> Vorschau -> Anmoderation (Say) -> Video -> Untertitel
    -> Video-Ende/Abbruch -> Zusammenfassung (Say) -> Quiz -> Q&A -> Rueckkehr

WICHTIGER EHRLICHER HINWEIS (siehe IMPLEMENTATION_REPORT.md):
- Die eigentliche Video-/Untertitel-WIEDERGABE findet auf dem Tablet statt.
  Die noch nicht gebaute Tablet-UI (Arbeitspaket 20) existiert in dieser
  Session nicht -- dieser Node published lediglich einen JSON-Steuerbefehl
  auf 'tablet_command', den eine kuenftige Tablet-UI konsumieren kann/soll.
  Die hier simulierte Fortschrittsanzeige (progress_seconds) basiert auf
  der per ffprobe ermittelten (oder geschaetzten) Videolaenge, NICHT auf
  einer echten Wiedergabe-Rueckmeldung vom Tablet.
- Die Quiz-Fragen werden per TTS gestellt, die Antwortauswertung ist NICHT
  implementiert (erfordert Korrelation mit /audio_node/transcript -- siehe
  Bericht). Die Q&A-Phase reserviert nur ein Zeitfenster; die eigentliche
  Fragebeantwortung laeuft ueber den bereits laufenden dialog_manager_node,
  der kontinuierlich auf /audio_node/transcript hoert.
- pause/resume/repeat werden ueber ein eigenes String-Topic
  'presentation_control' gesteuert (keine dedizierte Action/Service dafuer
  in ihk_pepper_interfaces vorgesehen) -- dokumentierte, reversible
  Annahme gemaess Auftrag 3.2/"technisch sinnvolle Annahme".
"""
import json
import os
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, ActionClient, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from std_msgs.msg import String
from ament_index_python.packages import get_package_share_directory

from ihk_pepper_interfaces.action import PlayPresentation, Say
from ihk_pepper_interfaces.msg import PresentationState
from ihk_pepper_interfaces.srv import SelectDailyTopic

from .daily_topic import load_all_topics, select_active_topic

STATE_NAMES = {
    PresentationState.IDLE: "IDLE",
    PresentationState.SELECTING_TOPIC: "SELECTING_TOPIC",
    PresentationState.SHOWING_PREVIEW: "SHOWING_PREVIEW",
    PresentationState.SPEAKING_INTRO: "SPEAKING_INTRO",
    PresentationState.PLAYING_VIDEO: "PLAYING_VIDEO",
    PresentationState.SHOWING_SUBTITLES: "SHOWING_SUBTITLES",
    PresentationState.VIDEO_ENDED: "VIDEO_ENDED",
    PresentationState.SPEAKING_SUMMARY: "SPEAKING_SUMMARY",
    PresentationState.QUIZ: "QUIZ",
    PresentationState.QA: "QA",
    PresentationState.RETURNING: "RETURNING",
    PresentationState.PAUSED: "PAUSED",
    PresentationState.CANCELLED: "CANCELLED",
    PresentationState.ERROR: "ERROR",
}


def _default_topics_dir():
    try:
        return os.path.join(get_package_share_directory("ihk_pepper_presentation"),
                             "content", "daily_topics")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "content", "daily_topics",
        )


def _probe_video_duration_s(path: str):
    """Liefert die Videolaenge in Sekunden via ffprobe, oder None wenn
    ffprobe fehlt/fehlschlaegt (dann wird kein Fortschritt simuliert,
    siehe _run_video_step)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=5,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


class PresentationCancelled(Exception):
    pass


class PresentationManagerNode(Node):
    def __init__(self):
        super().__init__("presentation_manager")

        self.declare_parameter("topics_dir", _default_topics_dir())
        self.declare_parameter("say_timeout_s", 30.0)
        self.declare_parameter("preview_duration_s", 2.0)
        self.declare_parameter("no_video_duration_s", 5.0)
        self.declare_parameter("qa_window_s", 20.0)
        self.declare_parameter("quiz_question_pause_s", 3.0)
        self.declare_parameter("skip_quiz", False)

        self.topics = {}
        self._reload_topics()

        self._preferred_topic_id = ""
        self._state = PresentationState.IDLE
        self._current_topic_id = ""
        self._progress_seconds = 0.0
        self._paused = threading.Event()
        self._repeat_requested = threading.Event()

        cb_group = ReentrantCallbackGroup()

        self.tablet_pub = self.create_publisher(String, "tablet_command", 10)
        self.state_pub = self.create_publisher(PresentationState, "presentation_state", 10)
        self.create_timer(1.0, self._publish_state)

        self.create_subscription(String, "presentation_control", self._on_control, 10)

        self.say_client = ActionClient(self, Say, "/pepper_bridge/say", callback_group=cb_group)

        self.action_server = ActionServer(
            self, PlayPresentation, "play_presentation",
            execute_callback=self._execute,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=cb_group,
        )
        self.select_srv = self.create_service(
            SelectDailyTopic, "select_daily_topic", self._handle_select_topic
        )

        self.get_logger().info(
            f"presentation_manager gestartet. Themen geladen: {list(self.topics.keys())}"
        )

    # ---- Themen laden ----

    def _reload_topics(self):
        directory = self.get_parameter("topics_dir").value if self.has_parameter("topics_dir") \
            else _default_topics_dir()
        topics, errors = load_all_topics(directory)
        for e in errors:
            self.get_logger().error(f"Tagesthema ungueltig, uebersprungen: {e}")
        self.topics = topics
        return topics

    def _handle_select_topic(self, request, response):
        topics = self._reload_topics()
        if request.topic_id not in topics:
            response.success = False
            response.message = f"Unbekannte topic_id: {request.topic_id}"
            return response
        if not topics[request.topic_id].is_valid_today():
            response.success = False
            response.message = f"Thema '{request.topic_id}' ist heute nicht gueltig."
            return response
        self._preferred_topic_id = request.topic_id
        response.success = True
        response.message = "OK -- wird beim naechsten PlayPresentation-Ziel ohne topic_id verwendet."
        return response

    # ---- Steuerung (pause/resume/repeat) ----

    def _on_control(self, msg: String):
        cmd = msg.data.strip().lower()
        if cmd == "pause":
            self._paused.set()
            self.get_logger().info("Praesentation pausiert.")
        elif cmd == "resume":
            self._paused.clear()
            self.get_logger().info("Praesentation fortgesetzt.")
        elif cmd == "repeat":
            self._repeat_requested.set()
            self.get_logger().info("Wiederholung des aktuellen Schritts angefordert.")
        else:
            self.get_logger().warn(f"Unbekannter presentation_control-Befehl: {cmd}")

    # ---- State-Topic ----

    def _publish_state(self):
        msg = PresentationState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.state = self._state
        msg.state_name = STATE_NAMES.get(self._state, "UNKNOWN")
        msg.topic_id = self._current_topic_id
        msg.progress_seconds = self._progress_seconds
        self.state_pub.publish(msg)

    def _publish_tablet(self, cmd: str, **kwargs):
        payload = {"cmd": cmd, **kwargs}
        self.tablet_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    # ---- Say (blockierend, siehe Moduldoku) ----

    def _say_and_wait(self, text: str, timeout_s: float) -> bool:
        if not text.strip():
            return True
        if not self.say_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("Say-Action nicht erreichbar -- Text wird nur geloggt.")
            self.get_logger().info(f"[nicht gesprochen] {text}")
            return False

        goal = Say.Goal()
        goal.text = text
        goal.allow_interrupt = True
        goal.max_duration_s = 0.0

        done = threading.Event()
        outcome = {"success": False}

        def on_result(fut):
            try:
                result = fut.result().result
                outcome["success"] = result.success
            except Exception as e:
                self.get_logger().warn(f"Say-Ergebnis nicht abrufbar: {e}")
            done.set()

        def on_goal_response(fut):
            gh = fut.result()
            if not gh.accepted:
                done.set()
                return
            rf = gh.get_result_async()
            rf.add_done_callback(on_result)

        send_fut = self.say_client.send_goal_async(goal)
        send_fut.add_done_callback(on_goal_response)

        if not done.wait(timeout_s):
            self.get_logger().warn("Say-Aufruf hat das Timeout ueberschritten.")
            return False
        return outcome["success"]

    # ---- Action goal/cancel ----

    def _goal_callback(self, goal_request):
        if goal_request.topic_id and goal_request.topic_id not in self.topics:
            self._reload_topics()
        if goal_request.topic_id and goal_request.topic_id not in self.topics:
            self.get_logger().warn(f"PlayPresentation abgelehnt: unbekannte topic_id '{goal_request.topic_id}'")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def _check_cancel(self, goal_handle):
        if goal_handle.is_cancel_requested:
            raise PresentationCancelled()

    def _set_state(self, goal_handle, state, progress=0.0):
        self._state = state
        self._progress_seconds = progress
        fb = PlayPresentation.Feedback()
        fb.presentation_state = state
        fb.state_name = STATE_NAMES.get(state, "UNKNOWN")
        fb.progress_seconds = progress
        goal_handle.publish_feedback(fb)

    # ---- Hauptablauf ----

    def _execute(self, goal_handle):
        result = PlayPresentation.Result()
        self._repeat_requested.clear()
        self._paused.clear()

        try:
            topics = self._reload_topics()
            self._set_state(goal_handle, PresentationState.SELECTING_TOPIC)
            topic_id = goal_handle.request.topic_id or self._preferred_topic_id
            topic = topics.get(topic_id) if topic_id else select_active_topic(topics)
            if topic is None:
                result.success = False
                result.completed_fully = False
                result.error_message = "Kein gueltiges Tagesthema gefunden."
                goal_handle.abort()
                return result

            self._current_topic_id = topic.id
            self.get_logger().info(f"Praesentation gestartet: {topic.id}")

            self._check_cancel(goal_handle)
            self._set_state(goal_handle, PresentationState.SHOWING_PREVIEW)
            self._publish_tablet("preview", topic_id=topic.id, title=topic.title,
                                  short_description=topic.short_description,
                                  thumbnail_path=topic.thumbnail_path)
            self._wait_bounded(goal_handle, self.get_parameter("preview_duration_s").value)

            self._check_cancel(goal_handle)
            self._set_state(goal_handle, PresentationState.SPEAKING_INTRO)
            self._say_and_wait(topic.intro_text, self.get_parameter("say_timeout_s").value)

            self._check_cancel(goal_handle)
            self._run_video_step(goal_handle, topic)

            self._check_cancel(goal_handle)
            self._set_state(goal_handle, PresentationState.SPEAKING_SUMMARY)
            self._say_and_wait(topic.summary_text, self.get_parameter("say_timeout_s").value)

            if topic.quiz_questions and not self.get_parameter("skip_quiz").value:
                self._check_cancel(goal_handle)
                self._run_quiz_step(goal_handle, topic)

            if goal_handle.request.allow_qa and topic.closing_question:
                self._check_cancel(goal_handle)
                self._set_state(goal_handle, PresentationState.QA)
                self._say_and_wait(topic.closing_question, self.get_parameter("say_timeout_s").value)
                # Die eigentliche Fragebeantwortung laeuft ueber den
                # parallel laufenden dialog_manager_node (hoert kontinuierlich
                # auf /audio_node/transcript) -- hier nur ein Zeitfenster.
                self._wait_bounded(goal_handle, self.get_parameter("qa_window_s").value)

            self._check_cancel(goal_handle)
            self._set_state(goal_handle, PresentationState.RETURNING)
            self._publish_tablet("return")

            result.success = True
            result.completed_fully = True
            result.error_message = ""
            goal_handle.succeed()
            self._state = PresentationState.IDLE
            return result

        except PresentationCancelled:
            self._set_state(goal_handle, PresentationState.CANCELLED, self._progress_seconds)
            self._publish_tablet("cancelled")
            result.success = False
            result.completed_fully = False
            result.error_message = "abgebrochen"
            goal_handle.canceled()
            self._state = PresentationState.IDLE
            return result
        except Exception as e:
            self.get_logger().error(f"Praesentation fehlgeschlagen: {e}")
            self._set_state(goal_handle, PresentationState.ERROR)
            result.success = False
            result.completed_fully = False
            result.error_message = str(e)
            goal_handle.abort()
            self._state = PresentationState.IDLE
            return result

    def _wait_bounded(self, goal_handle, duration_s: float, step_s: float = 0.2):
        """Wartet duration_s Sekunden, respektiert dabei pause() und cancel()."""
        elapsed = 0.0
        while elapsed < duration_s:
            self._check_cancel(goal_handle)
            if self._paused.is_set():
                self._set_state(goal_handle, PresentationState.PAUSED, self._progress_seconds)
                time.sleep(step_s)
                continue
            time.sleep(step_s)
            elapsed += step_s

    def _run_video_step(self, goal_handle, topic):
        if not topic.has_video():
            self.get_logger().info(
                f"Kein Video fuer '{topic.id}' vorhanden ({topic.video_path or '(kein Pfad)'}) -- Fallback."
            )
            self._set_state(goal_handle, PresentationState.VIDEO_ENDED)
            self._say_and_wait(topic.fallback_no_video, self.get_parameter("say_timeout_s").value)
            return

        duration = _probe_video_duration_s(topic.video_path)
        self._publish_tablet("play_video", video_path=topic.video_path,
                              subtitle_path=topic.subtitle_path,
                              duration_s=duration)

        self._set_state(goal_handle, PresentationState.PLAYING_VIDEO, 0.0)
        if topic.subtitle_path and os.path.isfile(topic.subtitle_path):
            self._set_state(goal_handle, PresentationState.SHOWING_SUBTITLES, 0.0)

        if duration is None:
            # ffprobe nicht verfuegbar/Video nicht lesbar -- keine
            # Fortschrittssimulation, aber Ablauf nicht blockieren.
            self.get_logger().warn(
                f"Videolaenge fuer '{topic.video_path}' nicht ermittelbar (ffprobe) -- "
                "ueberspringe simulierte Wiedergabe."
            )
            self._set_state(goal_handle, PresentationState.VIDEO_ENDED)
            return

        elapsed = 0.0
        step = 0.5
        while elapsed < duration:
            self._check_cancel(goal_handle)
            if self._repeat_requested.is_set():
                self._repeat_requested.clear()
                elapsed = 0.0
                self.get_logger().info("Video-Wiederholung angefordert -- Fortschritt zurueckgesetzt.")
            if self._paused.is_set():
                self._set_state(goal_handle, PresentationState.PAUSED, elapsed)
                time.sleep(step)
                continue
            time.sleep(step)
            elapsed += step
            self._set_state(goal_handle, PresentationState.PLAYING_VIDEO, min(elapsed, duration))

        self._set_state(goal_handle, PresentationState.VIDEO_ENDED, duration)
        self._publish_tablet("video_ended")

    def _run_quiz_step(self, goal_handle, topic):
        self._set_state(goal_handle, PresentationState.QUIZ)
        self._publish_tablet("quiz", questions=topic.quiz_questions)
        for q in topic.quiz_questions:
            self._check_cancel(goal_handle)
            question_text = q.get("question", "") if isinstance(q, dict) else str(q)
            if not question_text:
                continue
            self._say_and_wait(question_text, self.get_parameter("say_timeout_s").value)
            # Antwortauswertung nicht implementiert, siehe Moduldoku oben.
            self._wait_bounded(goal_handle, self.get_parameter("quiz_question_pause_s").value)


def main(args=None):
    rclpy.init(args=args)
    node = PresentationManagerNode()
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
