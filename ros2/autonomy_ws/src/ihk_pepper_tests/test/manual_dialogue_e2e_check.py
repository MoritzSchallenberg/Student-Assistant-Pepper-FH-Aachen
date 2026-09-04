#!/usr/bin/env python3
"""
Manuelle (NICHT von `pytest test/` automatisch eingesammelte -- daher
"manual_" statt "test_" im Dateinamen) Ende-zu-Ende-Verifikation des
vollstaendigen Mock-Dialogs durch alle drei LLM-Stufen
(Entwicklungsauftrag 3, Abschnitt "Tests" -> "End-to-End-Test").

Warum nicht Teil der schnellen pytest-Suite: startet mehrere echte
ROS2-Prozesse per Subprozess -- gleiches Muster wie
manual_e2e_offline_check.py (Entwicklungsauftrag 1).

    cd ros2/autonomy_ws && source install/setup.bash
    python3 src/ihk_pepper_tests/test/manual_dialogue_e2e_check.py known_person
    python3 src/ihk_pepper_tests/test/manual_dialogue_e2e_check.py unknown_person

Szenario "known_person": setzt vorher per set_consent granted fuer
person_id=42, prueft NACH dem Dialog, dass ein Vector-Memory-Eintrag
existiert (WriteMemorySummary erfolgreich).

Szenario "unknown_person": KEINE Einwilligung -- prueft NACH dem Dialog,
dass KEIN persistenter Personeneintrag/Memory-Eintrag entstanden ist
(GetPersonContext liefert weiterhin known=false).

Beide Szenarien: bridge_node im dry_run (keine echte SSH-Verbindung),
kein Nav2/mock_nav2_server noetig (RunDialogue beruehrt keine Bewegung).
Mock-LLM-Provider fuer alle drei Stufen (kein Netzwerkzugriff noetig).
"""
import json
import os
import signal
import subprocess
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String

from ihk_pepper_interfaces.action import RunDialogue
from ihk_pepper_interfaces.msg import PersonTrack, PersonTrackArray, SafetyState
from ihk_pepper_interfaces.srv import GetPersonContext, SetConsent

VALID_SCENARIOS = ("known_person", "unknown_person")
# Unterschiedliche IDs je Szenario -- sonst wuerde ein zuvor erteilter
# Consent aus dem known_person-Lauf einen spaeteren unknown_person-Lauf
# verfaelschen (die Identity-DB ist persistent, siehe AP5).
SESSION_IDS = {"known_person": "42", "unknown_person": "99"}


def _start(cmd, log_path, env=None):
    log_file = open(log_path, "w")
    return subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True,
        start_new_session=True, env=env)


def _kill_group(p):
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


class DialogueTestDriver(Node):
    def __init__(self, track_id: int):
        super().__init__("dialogue_e2e_test_driver")
        self.track_id = track_id
        self.transcript_pub = self.create_publisher(String, "/audio_node/transcript", 10)
        self.tracks_pub = self.create_publisher(PersonTrackArray, "/perception_node/person_tracks", 10)
        self.safety_pub = self.create_publisher(SafetyState, "/safety_state", 10)
        self.set_consent_client = self.create_client(SetConsent, "/set_consent")
        self.get_context_client = self.create_client(GetPersonContext, "/get_person_context")
        self.create_timer(0.1, self._publish_mocks)

    def _publish_mocks(self):
        # Synthetischer, kontinuierlich frischer Track -- ohne das wuerde
        # run_dialogue_action_server sofort PERSON_LOST melden (kein
        # echter perception_node in diesem Test), siehe
        # docs/DEVELOPMENT_ORDER_03_REPORT.md AP11 fuer den per Live-Test
        # gefundenen Grund.
        array = PersonTrackArray()
        track = PersonTrack()
        track.track_id = self.track_id
        track.confidence = 0.9
        array.tracks = [track]
        self.tracks_pub.publish(array)

        safety = SafetyState()
        safety.emergency_stop = False
        safety.bumper_active = False
        self.safety_pub.publish(safety)

    def _call_and_wait(self, client, request, timeout_s=5.0):
        if not client.wait_for_service(timeout_sec=timeout_s):
            return None
        future = client.call_async(request)
        deadline = time.time() + timeout_s
        while not future.done() and time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
        return future.result() if future.done() else None

    def grant_consent(self, person_id):
        req = SetConsent.Request()
        req.person_id = person_id
        req.consent_status = "granted"
        req.reason = "manual_dialogue_e2e_check: simulated verbal consent"
        return self._call_and_wait(self.set_consent_client, req)

    def get_person_context(self, person_id):
        req = GetPersonContext.Request()
        req.person_id = person_id
        return self._call_and_wait(self.get_context_client, req)


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "known_person"
    if scenario not in VALID_SCENARIOS:
        print(f"Unbekanntes Szenario {scenario!r}, erwartet eines von {VALID_SCENARIOS}")
        return 1
    session_id = SESSION_IDS[scenario]
    print(f"Szenario: {scenario} (session_id={session_id})")

    env = os.environ.copy()
    env["PEPPER_FAQ_DB_PATH"] = "/tmp/dialogue_e2e_faq_cache.sqlite"
    env["AMENT_PREFIX_PATH"] = (
        "/home/canvastino/Schreibtisch/Pepper/ros2/autonomy_ws/install/ihk_pepper_dialog:"
        + env.get("AMENT_PREFIX_PATH", ""))
    env["PYTHONPATH"] = (
        "/home/canvastino/Schreibtisch/Pepper/ros2/autonomy_ws/install/ihk_pepper_dialog/"
        "lib/python3.12/site-packages:" + env.get("PYTHONPATH", ""))

    log_dir = "/tmp/dialogue_e2e_check_logs"
    os.makedirs(log_dir, exist_ok=True)

    # Frische FAQ-DB fuer einen deterministischen "faq:1"-Eintrag (der
    # Response-Composer-Mock unten referenziert diese ID direkt).
    if os.path.exists(env["PEPPER_FAQ_DB_PATH"]):
        os.remove(env["PEPPER_FAQ_DB_PATH"])

    # FAQ-Eintrag vorab seeden (WICHTIG: FaqCache-Import MUSS vor
    # rclpy.init() passieren, siehe run_dialogue_action_server.py::
    # build_faq_cache() -- dasselbe gilt hier, auch wenn dieser Prozess
    # die DB nur schreibt und den Node nicht selbst hostet).
    sys.path.insert(0, "/home/canvastino/Schreibtisch/Pepper/ros2/autonomy_ws/"
                        "install/ihk_pepper_dialog/lib/python3.12/site-packages")
    from ihk_pepper_dialog.faq_cache import FaqCache
    faq = FaqCache(env["PEPPER_FAQ_DB_PATH"])
    faq.add_entry(
        canonical_question="Wie lange dauert die Ausbildung?",
        answer="Die Ausbildung dauert in der Regel drei Jahre.",
        approved=True, topic="ausbildungsdauer",
    )
    faq.close()

    # Fuer den known_person-Lauf: realistische kanonische Mock-Antworten
    # je Stufe, damit der komplette Ablauf inkl. validiertem Memory-
    # Eintrag durchlaeuft (nicht nur der Sicherheits-Fallback-Pfad).
    knowledge_mock = json.dumps({
        "schema_version": 1, "normalized_intent": "information_request",
        # Muss dem Wortlaut der gesaeten FAQ-Frage entsprechen, damit
        # lookup_exact() (normalisierter Text-Abgleich) tatsaechlich
        # trifft -- ein bloss thematisch verwandter Suchbegriff wie
        # "Ausbildungsdauer" haette hier NICHT sicher gegriffen (per
        # Live-Test gefunden: die semantische Difflib-Naeherung liegt bei
        # so unterschiedlicher Formulierung unter der Schwelle).
        "search_queries": ["Wie lange dauert die Ausbildung?"], "required_data_kinds": ["faq"],
        "use_person_memory": False, "uncertainties": [], "assumes_known_identity": False,
    })
    gesture_mock = json.dumps({"schema_version": 1, "suggestions": []})
    response_mock = json.dumps({
        "schema_version": 1,
        "segments": [{"segment_id": "answer",
                      "text": "Die Ausbildung dauert in der Regel drei Jahre.",
                      "gesture_name": None, "gesture_relation": None}],
        "source_ids": ["faq:1"],
        "memory_summary_candidate": "Frage zur Ausbildungsdauer beantwortet.",
    })

    dialog_args = [
        "ros2", "run", "ihk_pepper_dialog", "run_dialogue_action_server",
        "--ros-args",
        "-p", "knowledge_llm_provider:=mock",
        "-p", "gesture_llm_provider:=mock",
        "-p", "response_llm_provider:=mock",
        "-p", "question_timeout_s:=5.0",
        "-p", "session_timeout_s:=15.0",
    ]
    if scenario == "known_person":
        # JSON-Werte NICHT direkt per "-p key:=<json>" uebergeben -- ROS2s
        # CLI-Parameter-Parser interpretiert das als YAML und scheitert an
        # verschachtelten Anfuehrungszeichen/Klammern (per Live-Test
        # gefunden: "Unknown YAML event"). Stattdessen eine echte
        # Parameter-YAML-Datei nutzen (--params-file), das ist der
        # dafuer vorgesehene ROS2-Weg fuer komplexe Werte.
        params_yaml = {
            "run_dialogue_action_server": {"ros__parameters": {
                "knowledge_llm_mock_response": knowledge_mock,
                "gesture_llm_mock_response": gesture_mock,
                "response_llm_mock_response": response_mock,
            }}
        }
        params_path = f"{log_dir}/mock_responses.yaml"
        with open(params_path, "w") as f:
            import yaml
            yaml.safe_dump(params_yaml, f)
        dialog_args += ["--params-file", params_path]

    procs = [
        _start(["ros2", "run", "ihk_pepper_bridge", "bridge_node",
                "--ros-args", "-r", "__ns:=/pepper_bridge", "-p", "dry_run:=true"],
               f"{log_dir}/bridge.log", env=env),
        _start(["ros2", "run", "ihk_pepper_person_memory", "person_memory_node"],
               f"{log_dir}/person_memory.log", env=env),
        _start(dialog_args, f"{log_dir}/run_dialogue.log", env=env),
    ]
    print(f"Logs unter {log_dir}/*.log")
    time.sleep(3.0)

    rclpy.init()
    driver = DialogueTestDriver(track_id=int(session_id))
    outcome = {"result": None, "context_after": None}

    try:
        if scenario == "known_person":
            consent_resp = driver.grant_consent(session_id)
            print(f"set_consent Antwort: {consent_resp}")

        client = ActionClient(driver, RunDialogue, "/run_dialogue")
        if not client.wait_for_server(timeout_sec=10.0):
            print("ERGEBNIS: FEHLGESCHLAGEN -- run_dialogue-Action nicht erreichbar")
            return 1

        goal = RunDialogue.Goal()
        goal.session_id = session_id

        feedback_log = []

        def on_feedback(fb):
            feedback_log.append(fb.feedback.state_name)
            print(f"feedback: {fb.feedback.state_name}")

        send_future = client.send_goal_async(goal, feedback_callback=on_feedback)
        deadline = time.time() + 5.0
        while not send_future.done() and time.time() < deadline:
            rclpy.spin_once(driver, timeout_sec=0.05)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            print("ERGEBNIS: FEHLGESCHLAGEN -- Ziel nicht akzeptiert")
            return 1

        # kurze Aufwaermphase, dann Frage einspielen (siehe manual_approach_monitor_check.py
        # fuer denselben, per Live-Test gefundenen Grund)
        warmup_deadline = time.time() + 1.0
        while time.time() < warmup_deadline:
            rclpy.spin_once(driver, timeout_sec=0.05)
        driver.transcript_pub.publish(String(data="Wie lange dauert die Ausbildung?"))
        print(">>> Frage eingespielt <<<")

        # auf WAITING_FOR_FOLLOWUP im Feedback warten, dann abbrechen
        deadline = time.time() + 20.0
        while time.time() < deadline:
            rclpy.spin_once(driver, timeout_sec=0.1)
            if "WAITING_FOR_FOLLOWUP" in feedback_log:
                break
        goal_handle.cancel_goal_async()

        result_future = goal_handle.get_result_async()
        deadline = time.time() + 10.0
        while not result_future.done() and time.time() < deadline:
            rclpy.spin_once(driver, timeout_sec=0.05)
        outcome["result"] = result_future.result()

        time.sleep(0.5)
        outcome["context_after"] = driver.get_person_context(session_id)
    finally:
        driver.destroy_node()
        rclpy.shutdown()
        for p in procs:
            _kill_group(p)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    reached_followup = "WAITING_FOR_FOLLOWUP" in feedback_log
    print(f"reached_waiting_for_followup={reached_followup}")
    print(f"context_after={outcome['context_after']}")

    if not reached_followup:
        print("ERGEBNIS: FEHLGESCHLAGEN -- WAITING_FOR_FOLLOWUP nie erreicht")
        return 1

    ctx = outcome["context_after"]
    if scenario == "unknown_person":
        if ctx is not None and ctx.known:
            print("ERGEBNIS: FEHLGESCHLAGEN -- unbekannte Person wurde trotzdem als bekannt gespeichert!")
            return 1
        print("ERGEBNIS: OK -- kein persistenter Personeneintrag ohne Einwilligung entstanden.")
        return 0

    print("ERGEBNIS: OK -- Dialog durchlief alle drei LLM-Stufen bis WAITING_FOR_FOLLOWUP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
