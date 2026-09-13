"""
Entwicklungsauftrag 04-B, AP8.8, Commit 13/14, Abschnitt 10: mindestens
EIN Offline-Integrationstest muss ECHTE ROS2-Action-Kommunikation
pruefen (RunDialogue-Client -> realer RunDialogue-ActionServer ->
Say-/PlayGesture-Action-Kommunikation -> Ergebnis/Cancel). Startet einen
ECHTEN RunDialogueActionServer (rclpy.init(), MultiThreadedExecutor)
gegen kontrollierte Fake-Action-Server fuer /pepper_bridge/say und
/pepper_bridge/play_gesture -- kein echter Pepper-Client, kein SSH/
qicli, kein externer LLM-Aufruf (alle drei LLM-Rollen laufen ueber
MockLLMProvider mit fest verdrahteten Antworten, identisches Muster wie
manual_dialogue_e2e_check.py). Kein Live-Nav2, kein /cmd_vel.
"""
import json
import os
import tempfile
import threading
import time

import pytest
import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, String

from ihk_pepper_dialog.faq_cache import FaqCache
from ihk_pepper_dialog.run_dialogue_action_server import RunDialogueActionServer
from ihk_pepper_interfaces.action import PlayGesture, RunDialogue, Say
from ihk_pepper_interfaces.msg import DialogueState, SafetyState
from ihk_pepper_interfaces.srv import GetPersonContext, WriteMemorySummary

_KNOWLEDGE_MOCK = json.dumps({
    "schema_version": 1, "normalized_intent": "information_request",
    "search_queries": [], "required_data_kinds": [],
    "use_person_memory": False, "uncertainties": [], "assumes_known_identity": False,
})
_GESTURE_MOCK = json.dumps({"schema_version": 1, "suggestions": []})
# Entwicklungsauftrag 04-B, AP8.9, Abschnitt 9 (Testpunkte 1/2): ein
# echtes memory_summary_candidate -- ohne das koennte der Memory-Write-
# Ausschluss nach Cancel/Fehlschlag gar nicht sichtbar geprueft werden
# (die bestehende Bedingung wuerde ohnehin schon an einem leeren
# Kandidaten scheitern, unabhaengig vom neuen exec_result.success-Gate).
_RESPONSE_MOCK = json.dumps({
    "schema_version": 1,
    "segments": [{"segment_id": "answer", "text": "Das ist die Testantwort.",
                  "gesture_name": None, "gesture_relation": None}],
    "source_ids": [], "memory_summary_candidate": "Test-Zusammenfassung.",
})


class _FakeSayServer(Node):
    """Kontrollierter Fake-ActionServer fuer /pepper_bridge/say -- echte
    rclpy_action-Kommunikation, keine SSH-/qicli-Verbindung zu Pepper."""

    def __init__(self, delay_s: float = 0.0, allow_cancel: bool = True, fail_immediately: bool = False):
        super().__init__("fake_say_server")
        self.calls = []
        self.cancel_requests = 0
        self._delay_s = delay_s
        self._allow_cancel = allow_cancel
        # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 9 (Testpunkt 2): ein
        # NACH der Konstruktion auf der Instanz ueberschriebenes _execute
        # haette KEINE Wirkung mehr -- ActionServer erfasst den zum
        # Konstruktionszeitpunkt gebundenen Methoden-Callable, keine
        # spaetere Neuzuweisung. Deshalb ein echter Konstruktorparameter.
        self._fail_immediately = fail_immediately
        self._server = ActionServer(
            self, Say, "/pepper_bridge/say",
            execute_callback=self._execute, cancel_callback=self._cancel,
            callback_group=ReentrantCallbackGroup(),
        )

    def _cancel(self, goal_handle):
        self.cancel_requests += 1
        return CancelResponse.ACCEPT if self._allow_cancel else CancelResponse.REJECT

    def _execute(self, goal_handle):
        self.calls.append(goal_handle.request.text)
        if self._fail_immediately:
            result = Say.Result()
            result.success = False
            goal_handle.abort()
            return result
        deadline = time.monotonic() + self._delay_s
        while time.monotonic() < deadline:
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = Say.Result()
                result.success = False
                return result
            time.sleep(0.01)
        result = Say.Result()
        result.success = True
        goal_handle.succeed()
        return result


class _FakeGestureServer(Node):
    """Kontrollierter Fake-ActionServer fuer /pepper_bridge/play_gesture."""

    def __init__(self, delay_s: float = 0.0):
        super().__init__("fake_gesture_server")
        self.calls = []
        self.cancel_requests = 0
        self._delay_s = delay_s
        self._server = ActionServer(
            self, PlayGesture, "/pepper_bridge/play_gesture",
            execute_callback=self._execute, cancel_callback=self._cancel,
            callback_group=ReentrantCallbackGroup(),
        )

    def _cancel(self, goal_handle):
        self.cancel_requests += 1
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        self.calls.append(goal_handle.request.gesture_name)
        deadline = time.monotonic() + self._delay_s
        while time.monotonic() < deadline:
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = PlayGesture.Result()
                result.success = False
                return result
            time.sleep(0.01)
        result = PlayGesture.Result()
        result.success = True
        goal_handle.succeed()
        return result


class _FakePersonMemoryServices(Node):
    """Entwicklungsauftrag 04-B, AP8.9, Abschnitt 9 (Testpunkte 1/2):
    echte rclpy-Services fuer /get_person_context und
    /write_memory_summary -- macht 'kein Memory-Write nach Cancel/
    Fehlschlag' ueber ECHTE ROS2-Service-Kommunikation nachweisbar
    (statt nur ueber person_context.get('known')==False strukturell
    unerreichbar zu sein, wie in den uebrigen Tests dieser Datei)."""

    def __init__(self, known: bool = True):
        super().__init__("fake_person_memory_services")
        self.known = known
        self.write_memory_calls = []
        self.create_service(
            GetPersonContext, "/get_person_context", self._get_person_context,
            callback_group=ReentrantCallbackGroup())
        self.create_service(
            WriteMemorySummary, "/write_memory_summary", self._write_memory_summary,
            callback_group=ReentrantCallbackGroup())

    def _get_person_context(self, request, response):
        response.known = self.known
        response.display_name = "Testperson" if self.known else ""
        return response

    def _write_memory_summary(self, request, response):
        self.write_memory_calls.append(request.summary)
        response.success = True
        return response


class _DriverNode(Node):
    """Testtreiber: publiziert die Laufzeitsignale, die
    run_dialogue_action_server.py fail-closed benoetigt (Abschnitt 4/5
    von AP5A/AP8.8), und stellt Transkript-/RunDialogue-Zugriff bereit."""

    def __init__(self):
        super().__init__("dialogue_integration_test_driver")
        self.transcript_pub = self.create_publisher(String, "/audio_node/transcript", 10)
        self.safety_pub = self.create_publisher(SafetyState, "/safety_state", 10)
        self.nav2_moving_pub = self.create_publisher(Bool, "/nav2_moving", 10)
        self.mapping_active_pub = self.create_publisher(Bool, "/mapping_active", 10)
        self.gesture_in_progress_pub = self.create_publisher(Bool, "/pepper_bridge/gesture_in_progress", 10)
        self.connection_state_pub = self.create_publisher(String, "/pepper_bridge/connection_state", 10)
        self.dialogue_states = []
        self.create_subscription(DialogueState, "dialogue_state", self._on_state, 10)
        self._keepalive_timer = self.create_timer(0.3, self._publish_keepalive)

    def _on_state(self, msg):
        self.dialogue_states.append(msg.state_name)

    def _publish_keepalive(self):
        self.safety_pub.publish(SafetyState())  # alle bool-Felder default False -> sicher
        self.nav2_moving_pub.publish(Bool(data=False))
        self.mapping_active_pub.publish(Bool(data=False))
        self.gesture_in_progress_pub.publish(Bool(data=False))
        self.connection_state_pub.publish(String(data="connected"))


@pytest.fixture()
def dialogue_env():
    # RunDialogueActionServer.__init__() liest seine Parameter (u.a. die
    # LLM-Provider-Auswahl) SOFORT beim Konstruieren -- ein
    # set_parameters()-Aufruf danach kaeme zu spaet (die Provider waeren
    # bereits mit den Defaults gebaut). Parameter muessen deshalb VOR der
    # Knoten-Erzeugung als globale ROS-Argumente vorliegen. JSON-Werte
    # NICHT direkt per '-p key:=<json>' uebergeben (ROS2s CLI-Parameter-
    # Parser interpretiert das als YAML und scheitert an verschachtelten
    # Anfuehrungszeichen) -- stattdessen eine echte Parameter-YAML-Datei
    # nutzen, identisches Muster wie manual_dialogue_e2e_check.py.
    import yaml
    params_yaml = {
        "run_dialogue_action_server": {"ros__parameters": {
            "knowledge_llm_provider": "mock",
            "gesture_llm_provider": "mock",
            "response_llm_provider": "mock",
            "knowledge_llm_mock_response": _KNOWLEDGE_MOCK,
            "gesture_llm_mock_response": _GESTURE_MOCK,
            "response_llm_mock_response": _RESPONSE_MOCK,
            "gesture_search.enabled": False,
            "question_timeout_s": 5.0,
            "session_timeout_s": 20.0,
            "thinking_loop_delay_s": 10.0,  # in diesen Tests nie erreicht
            "post_speech_pause_s": 0.05,
        }}
    }
    params_fd, params_path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(params_fd, "w") as f:
        yaml.safe_dump(params_yaml, f)

    rclpy.init(args=["--ros-args", "--params-file", params_path])
    faq_fd, faq_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(faq_fd)
    os.unlink(faq_path)  # FaqCache legt die Datei selbst an
    faq = FaqCache(faq_path)

    say_server = _FakeSayServer()
    gesture_server = _FakeGestureServer()
    person_memory = _FakePersonMemoryServices(known=True)
    dialog_node = RunDialogueActionServer(faq)
    driver = _DriverNode()

    executor = MultiThreadedExecutor()
    for n in (say_server, gesture_server, person_memory, dialog_node, driver):
        executor.add_node(n)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    # etwas Zeit fuer Discovery + die ersten Keepalive-Publikationen.
    time.sleep(1.0)

    env = {
        "say_server": say_server, "gesture_server": gesture_server,
        "person_memory": person_memory, "dialog_node": dialog_node, "driver": driver,
    }
    yield env

    # Kurze Gnadenfrist: ein Test kann am Ende noch ein Cancel
    # angestossen haben (fire-and-forget Aufraeumen) -- laesst dessen
    # Hintergrund-Ausfuehrung noch kurz auslaufen, bevor der Executor/
    # rclpy heruntergefahren wird (rein kosmetisch, vermeidet laute, aber
    # harmlose 'feedback publisher is invalid'-Fehler durch eine
    # Race zwischen Test-Teardown und einer noch laufenden
    # Action-Callback-Ausfuehrung).
    time.sleep(0.3)
    executor.shutdown()
    for n in (say_server, gesture_server, person_memory, dialog_node, driver):
        n.destroy_node()
    faq.close()
    for p in (faq_path, params_path):
        try:
            os.unlink(p)
        except OSError:
            pass
    rclpy.shutdown()


def _wait_for(predicate, timeout_s=10.0, interval_s=0.05):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _publish_transcript_until_seen(driver, text, predicate, timeout_s=3.0):
    """Ein einzelner publish()-Aufruf direkt nach dem Verbindungsaufbau
    kann durch die uebliche ROS2-Discovery-Verzoegerung (Publisher/
    Subscriber muessen sich erst gegenseitig finden) verloren gehen,
    bevor der Subscriber ueberhaupt registriert ist. Republiziert
    deshalb wiederholt, bis `predicate()` wahr wird (typischerweise:
    die erwartete Reaktion des Dialogservers ist eingetroffen)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        driver.transcript_pub.publish(String(data=text))
        time.sleep(0.1)
    return predicate()


def test_full_dialogue_round_trip_uses_real_say_and_gesture_actions(dialogue_env):
    driver = dialogue_env["driver"]
    say_server = dialogue_env["say_server"]
    gesture_server = dialogue_env["gesture_server"]

    client = ActionClient(driver, RunDialogue, "/run_dialogue")
    assert client.wait_for_server(timeout_sec=5.0)

    goal = RunDialogue.Goal()
    goal.session_id = "session-101"
    send_future = client.send_goal_async(goal)
    assert _wait_for(send_future.done, timeout_s=5.0)
    goal_handle = send_future.result()
    assert goal_handle.accepted

    # Erst JETZT (im LISTENING-Zustand) wartet der Server auf eine
    # Frage -- die Bestaetigungsgeste startet ausgeloest davon, NICHT
    # schon beim reinen Goal-Start. Wiederholt publizieren, bis die
    # Bestaetigungsgeste tatsaechlich ankommt (ein einzelner publish()
    # kann durch die ueblichen ROS2-Discovery-Verzoegerung verloren
    # gehen, siehe _publish_transcript_until_seen()).
    assert _publish_transcript_until_seen(
        driver, "Testfrage?", lambda: len(gesture_server.calls) >= 1, timeout_s=5.0)
    assert "acknowledge_nod_small" in gesture_server.calls

    result_future = goal_handle.get_result_async()
    assert _wait_for(result_future.done, timeout_s=10.0)
    result = result_future.result().result

    assert say_server.calls  # echte Say-Action-Kommunikation fand statt
    assert "Das ist die Testantwort." in say_server.calls
    assert "ACKNOWLEDGING" in driver.dialogue_states
    assert "THINKING" in driver.dialogue_states
    assert "SPEAKING" in driver.dialogue_states


def test_cancel_during_dialogue_cancels_the_real_action_and_the_active_say_goal(dialogue_env):
    driver = dialogue_env["driver"]
    say_server = dialogue_env["say_server"]
    say_server._delay_s = 3.0  # haelt die Say-Action lang genug offen, um sie abzubrechen

    client = ActionClient(driver, RunDialogue, "/run_dialogue")
    assert client.wait_for_server(timeout_sec=5.0)

    goal = RunDialogue.Goal()
    goal.session_id = "session-102"
    send_future = client.send_goal_async(goal)
    assert _wait_for(send_future.done, timeout_s=5.0)
    goal_handle = send_future.result()
    assert goal_handle.accepted

    assert _publish_transcript_until_seen(
        driver, "Noch eine Frage?", lambda: len(say_server.calls) >= 1, timeout_s=5.0)

    cancel_future = goal_handle.cancel_goal_async()
    assert _wait_for(cancel_future.done, timeout_s=5.0)

    result_future = goal_handle.get_result_async()
    assert _wait_for(result_future.done, timeout_s=10.0)

    # Die echte Say-Action wurde tatsaechlich ueber cancel_goal_async()
    # storniert (Entwicklungsauftrag 04-B, AP5B/AP8.8 -- kein passives
    # Warten auf die naechste Segmentgrenze).
    assert say_server.cancel_requests >= 1


def test_a_second_concurrent_run_dialogue_goal_is_rejected(dialogue_env):
    # Entwicklungsauftrag 04-B, AP8.8, Abschnitt 4: Einzelaktivitaet fuer
    # RunDialogue -- ueber ECHTE ROS2-Action-Kommunikation nachgewiesen.
    driver = dialogue_env["driver"]
    say_server = dialogue_env["say_server"]
    say_server._delay_s = 3.0

    client = ActionClient(driver, RunDialogue, "/run_dialogue")
    assert client.wait_for_server(timeout_sec=5.0)

    goal_a = RunDialogue.Goal()
    goal_a.session_id = "session-201"
    send_future_a = client.send_goal_async(goal_a)
    assert _wait_for(send_future_a.done, timeout_s=5.0)
    handle_a = send_future_a.result()
    assert handle_a.accepted

    assert _publish_transcript_until_seen(
        driver, "Erste Sitzung fragt etwas.", lambda: len(say_server.calls) >= 1, timeout_s=5.0)

    goal_b = RunDialogue.Goal()
    goal_b.session_id = "session-202"
    send_future_b = client.send_goal_async(goal_b)
    assert _wait_for(send_future_b.done, timeout_s=5.0)
    handle_b = send_future_b.result()
    assert handle_b.accepted is False  # abgelehnt, waehrend Sitzung 201 noch laeuft

    # Aufraeumen: Sitzung 201 abbrechen, damit der Executor sauber
    # herunterfaehrt.
    handle_a.cancel_goal_async()


def test_cancel_during_speaking_writes_no_memory_summary_even_for_a_known_person(dialogue_env):
    # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 3.1/9 (Testpunkt 1,
    # bestaetigter Fund): die alte Bedingung schrieb Memory bereits bei
    # 'memory_summary_candidate vorhanden UND person_context.known' --
    # OHNE exec_result je zu konsultieren. Hier ECHT ueber ROS2-Service-
    # Kommunikation bewiesen: eine bekannte Person (known=True) UND ein
    # echter memory_summary_candidate reichen NICHT mehr, wenn die
    # Ausfuehrung selbst abgebrochen wurde.
    driver = dialogue_env["driver"]
    say_server = dialogue_env["say_server"]
    person_memory = dialogue_env["person_memory"]
    say_server._delay_s = 3.0

    client = ActionClient(driver, RunDialogue, "/run_dialogue")
    assert client.wait_for_server(timeout_sec=5.0)

    goal = RunDialogue.Goal()
    goal.session_id = "session-301"
    send_future = client.send_goal_async(goal)
    assert _wait_for(send_future.done, timeout_s=5.0)
    goal_handle = send_future.result()
    assert goal_handle.accepted

    assert _publish_transcript_until_seen(
        driver, "Kennst du mich?", lambda: len(say_server.calls) >= 1, timeout_s=5.0)

    cancel_future = goal_handle.cancel_goal_async()
    assert _wait_for(cancel_future.done, timeout_s=5.0)
    result_future = goal_handle.get_result_async()
    assert _wait_for(result_future.done, timeout_s=10.0)

    assert say_server.cancel_requests >= 1
    assert person_memory.write_memory_calls == []


def test_say_failure_writes_no_memory_summary_even_for_a_known_person(dialogue_env):
    # Entwicklungsauftrag 04-B, AP8.9, Abschnitt 3.1/9 (Testpunkt 2):
    # dieselbe Anforderung, diesmal ueber einen regulaeren Say-
    # Fehlschlag (kein Cancel) -- der ResponsePlanExecutor bricht den
    # GESAMTEN Plan ab (siehe docs/RESPONSE_PLAN_EXECUTION.md), exec_result.success
    # wird False, kein Memory-Write darf erfolgen.
    driver = dialogue_env["driver"]
    say_server = dialogue_env["say_server"]
    person_memory = dialogue_env["person_memory"]
    say_server._fail_immediately = True

    client = ActionClient(driver, RunDialogue, "/run_dialogue")
    assert client.wait_for_server(timeout_sec=5.0)

    goal = RunDialogue.Goal()
    goal.session_id = "session-302"
    send_future = client.send_goal_async(goal)
    assert _wait_for(send_future.done, timeout_s=5.0)
    goal_handle = send_future.result()
    assert goal_handle.accepted

    assert _publish_transcript_until_seen(
        driver, "Wie war das nochmal?", lambda: len(say_server.calls) >= 1, timeout_s=5.0)

    result_future = goal_handle.get_result_async()
    assert _wait_for(result_future.done, timeout_s=10.0)

    assert person_memory.write_memory_calls == []
    handle_cleanup = goal_handle.cancel_goal_async()
    _wait_for(handle_cleanup.done, timeout_s=2.0)
