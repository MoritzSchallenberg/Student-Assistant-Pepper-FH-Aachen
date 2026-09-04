#!/usr/bin/env python3
"""
Manuelle (NICHT von `pytest test/` automatisch eingesammelte -- daher
"manual_" statt "test_" im Dateinamen) Verifikation, dass ApproachPerson
eine laufende Annaeherung SOFORT abbricht, wenn die Zielperson waehrend
der Fahrt verloren geht (Entwicklungsauftrag 2, Abschnitt 13 "AP10").

Warum nicht Teil der schnellen pytest-Suite: startet echte ROS2-Prozesse
(mock_nav2_server, person_approach_node) per subprocess -- gleiches
Muster wie manual_e2e_offline_check.py (Entwicklungsauftrag 1).

    cd ros2/autonomy_ws && source install/setup.bash
    python3 src/ihk_pepper_tests/test/manual_approach_monitor_check.py

Ablauf: publiziert eine Person (track_id=42, 3m entfernt im base_link-
Frame) + SafetyState.allow_person_approach=true, sendet ein ApproachPerson-
Ziel gegen mock_nav2_server (travel_time_s bewusst lang, damit genug Zeit
zum Eingreifen bleibt), stoppt nach 1.5s das Track-Publishing (simuliert
Personenverlust WAEHREND der Fahrt) und prueft, dass die Action aktiv
mit abort_reason="monitor_abort:person_lost" abbricht -- NICHT erst nach
einem 60s-Timeout. mock_nav2_server published NIEMALS /cmd_vel (siehe
dessen Moduldocstring), daher ist dieser Test auch ohne echte Hardware
sicher.
"""
import os
import signal
import subprocess
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from ihk_pepper_interfaces.action import ApproachPerson
from ihk_pepper_interfaces.msg import PersonTrack, PersonTrackArray, SafetyState

TRACK_ID = 42
TRACK_LOSS_AFTER_S = 1.5
RESULT_TIMEOUT_S = 15.0


class MonitorTestDriver(Node):
    def __init__(self):
        super().__init__("approach_monitor_test_driver")
        self.tracks_pub = self.create_publisher(PersonTrackArray, "/perception_node/person_tracks", 10)
        self.safety_pub = self.create_publisher(SafetyState, "/safety_state", 10)
        self.publish_tracks = True
        self.feedback_log = []
        self.create_timer(0.1, self._publish_mocks)

    def _publish_mocks(self):
        if self.publish_tracks:
            array = PersonTrackArray()
            track = PersonTrack()
            track.track_id = TRACK_ID
            track.confidence = 0.9
            track.has_3d_position = True
            track.position_3d.x = 3.0
            track.position_3d.y = 0.0
            track.frame_id = "base_link"
            track.distance_m = 3.0
            array.tracks = [track]
            self.tracks_pub.publish(array)

        safety = SafetyState()
        safety.allow_person_approach = True
        safety.reason = "manual_approach_monitor_check"
        self.safety_pub.publish(safety)

    def on_feedback(self, fb):
        self.feedback_log.append(fb.feedback.status)
        self.get_logger().info(
            f"feedback: {fb.feedback.status} dist_remaining={fb.feedback.distance_remaining_m:.2f}")


def _start(cmd, log_path):
    # Gleiches Muster wie manual_e2e_offline_check.py::_start -- siehe
    # dessen Kommentar fuer die Begruendung (verwaiste Prozesse,
    # Pipe-Puffer-Deadlock).
    log_file = open(log_path, "w")
    return subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True,
        start_new_session=True)


def _kill_group(p):
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


def main():
    log_dir = "/tmp/approach_monitor_check_logs"
    os.makedirs(log_dir, exist_ok=True)
    procs = [
        _start(["ros2", "run", "ihk_pepper_navigation", "mock_nav2_server",
                "--ros-args", "-p", "travel_time_s:=8.0"],
               f"{log_dir}/mock_nav2.log"),
        _start(["ros2", "run", "ihk_pepper_navigation", "person_approach_node"],
               f"{log_dir}/person_approach.log"),
    ]
    print(f"Logs unter {log_dir}/*.log")
    time.sleep(3.0)  # Discovery/Startzeit

    rclpy.init()
    driver = MonitorTestDriver()
    outcome = {"result": None}

    try:
        client = ActionClient(driver, ApproachPerson, "approach_person")
        if not client.wait_for_server(timeout_sec=10.0):
            print("ERGEBNIS: FEHLGESCHLAGEN -- approach_person-Action nicht erreichbar")
            return 1

        # wait_for_server() spint NICHT die eigenen Timer/Subscriptions des
        # Drivers -- ohne diese kurze Aufwaermphase kaeme beim Node noch
        # kein einziger Track/SafetyState an, das Ziel wuerde sofort mit
        # "person_lost" statt ueber den eigentlichen Monitor-Pfad abgelehnt.
        warmup_deadline = time.time() + 1.0
        while time.time() < warmup_deadline:
            rclpy.spin_once(driver, timeout_sec=0.05)

        goal = ApproachPerson.Goal()
        goal.track_id = TRACK_ID
        goal.target_distance_m = 1.0

        send_future = client.send_goal_async(goal, feedback_callback=driver.on_feedback)
        deadline = time.time() + 5.0
        while not send_future.done() and time.time() < deadline:
            rclpy.spin_once(driver, timeout_sec=0.05)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            print("ERGEBNIS: FEHLGESCHLAGEN -- Ziel nicht akzeptiert")
            return 1

        loss_triggered_at = time.time() + TRACK_LOSS_AFTER_S
        result_future = goal_handle.get_result_async()
        deadline = time.time() + RESULT_TIMEOUT_S
        while not result_future.done() and time.time() < deadline:
            rclpy.spin_once(driver, timeout_sec=0.05)
            if driver.publish_tracks and time.time() >= loss_triggered_at:
                print(">>> Track-Publishing gestoppt (simuliert Personenverlust waehrend der Fahrt) <<<")
                driver.publish_tracks = False

        outcome["result"] = result_future.result()
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

    result = outcome["result"]
    if result is None:
        print(f"ERGEBNIS: FEHLGESCHLAGEN -- kein Ergebnis innerhalb {RESULT_TIMEOUT_S}s")
        return 1

    success = result.result.success
    abort_reason = result.result.abort_reason
    print(f"RESULT: success={success} abort_reason={abort_reason!r}")

    if success:
        print("ERGEBNIS: FEHLGESCHLAGEN -- Annaeherung meldete Erfolg trotz Personenverlust")
        return 1
    if not abort_reason.startswith("monitor_abort:person_lost"):
        print(f"ERGEBNIS: FEHLGESCHLAGEN -- erwartete 'monitor_abort:person_lost*', "
              f"erhalten: {abort_reason!r}")
        return 1

    print("ERGEBNIS: OK -- Annaeherung wurde aktiv WAEHREND der Fahrt abgebrochen "
          "(nicht erst per Timeout).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
