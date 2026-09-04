#!/usr/bin/env python3
"""
Manuelle (NICHT von `pytest test/` automatisch eingesammelte -- daher
"manual_" statt "test_" im Dateinamen) Ende-zu-Ende-Verifikation des
vollstaendigen Offline-Ablaufs bis CONVERSATION_READY
(Entwicklungsauftrag 1, Abschnitt 12).

Warum nicht Teil der schnellen pytest-Suite: startet mehrere echte
ROS2-Prozesse (bridge_node, supervisor_node, mock_nav2_server,
person_approach_node, bt_executor_node) per subprocess und braucht ein
gebautes+gesourctes Workspace (inkl. ihk_pepper_behavior_tree, das die
CI-Pipeline aktuell noch NICHT baut, siehe .github/workflows/ci.yml) --
das haette die sonst ~50ms schnelle, hermetische pytest-Suite deutlich
verlangsamt/fragiler gemacht. Stattdessen: manuell mit

    cd ros2/autonomy_ws && source install/setup.bash
    python3 src/ihk_pepper_tests/test/manual_e2e_offline_check.py

ausfuehren. Setzt motion_capable=true, ruft EINMALIG /set_motion_permission
(allow_motion=true, allow_person_approach=true) -- das simuliert die
bewusste Freigabe-Entscheidung, die im echten Betrieb ein Mensch/ein
uebergeordnetes System explizit trifft (SafetyGate ist ein Zwei-
Schluessel-System: motion_capable ALLEIN reicht nicht, siehe
safety_gate.py::request_motion_permission()) -- UND injiziert per
Mock-Topics localization_valid/obstacle_data_valid/person_depth_valid=true.
Das ist NUR sicher moeglich, weil ApproachSelectedPerson ausschliesslich
gegen mock_nav2_server laeuft (published NIEMALS /cmd_vel, siehe
mock_nav2_server.py) und bridge_node mit dry_run=true laeuft (KEINE
SSH-Verbindung zu Pepper). Kein Test/keine Aktion hier fasst echte
Hardware an.
"""
import os
import signal
import subprocess
import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from geometry_msgs.msg import Point, Twist

from ihk_pepper_interfaces.msg import PersonTrack, PersonTrackArray, WaveGestureEvent
from ihk_pepper_interfaces.srv import SetMotionPermission

TIMEOUT_S = 40.0
TRACK_ID = 42


class E2EDriver(Node):
    def __init__(self):
        super().__init__("e2e_offline_driver")
        self.tracks_pub = self.create_publisher(PersonTrackArray, "/perception_node/person_tracks", 10)
        self.wave_pub = self.create_publisher(WaveGestureEvent, "/wave_gesture_events", 10)
        self.loc_pub = self.create_publisher(Bool, "/localization_valid", 10)
        self.obs_pub = self.create_publisher(Bool, "/obstacle_data_valid", 10)
        self.depth_pub = self.create_publisher(Bool, "/person_depth_valid", 10)
        self.charging_pub = self.create_publisher(Bool, "/charging_cable_connected", 10)
        self.interaction_state_name = None
        self.cmd_vel_seen = False
        self.create_subscription(String, "/interaction_state_name", self._on_state, 10)
        # Harter Test (Entwicklungsauftrag 1, Abschnitt 12): kein Testpfad
        # darf /cmd_vel jemals veroeffentlichen. Abonniert es hier aktiv --
        # ANY Nachricht, egal welcher Typ, zaehlt als Fehlschlag.
        self.create_subscription(Twist, "/cmd_vel", self._on_cmd_vel, 10)
        self.create_timer(0.2, self._publish_mocks)
        self._wave_sent = False

    def _on_cmd_vel(self, _msg):
        self.cmd_vel_seen = True

    def _on_state(self, msg: String):
        self.interaction_state_name = msg.data

    def _publish_mocks(self):
        now = self.get_clock().now().to_msg()

        self.loc_pub.publish(Bool(data=True))
        self.obs_pub.publish(Bool(data=True))
        self.depth_pub.publish(Bool(data=True))
        # "Nicht angeschlossen" simulieren -- sonst blockiert der sichere
        # Default (angeschlossen bis Gegenteil bekannt) die Freigabe fuer immer.
        self.charging_pub.publish(Bool(data=False))

        array = PersonTrackArray()
        array.header.stamp = now
        track = PersonTrack()
        track.header.stamp = now
        track.track_id = TRACK_ID
        track.confidence = 0.9
        track.has_3d_position = True
        track.position_3d = Point(x=1.5, y=0.0, z=0.0)
        track.frame_id = "base_link"
        track.last_seen = now
        track.distance_m = 1.5
        track.interest_score = 0.9
        track.stable = True
        track.stable_for_s = 5.0
        track.depth_confidence = 0.9
        track.source_camera = "synthetic_e2e_test"
        array.tracks.append(track)
        self.tracks_pub.publish(array)

        # Erst nach ein paar Sekunden "zurueckwinken" simulieren, damit
        # SelectStablePerson/HasGreetingCooldownExpired/PlayCatalogGesture
        # zuerst wirklich durchlaufen (realistischerer Ablauf als sofort
        # alles gleichzeitig zu senden).
        if self._wave_sent:
            return
        if not hasattr(self, "_start_t"):
            self._start_t = time.time()
        if time.time() - self._start_t > 3.0:
            event = WaveGestureEvent()
            event.header.stamp = now
            event.track_id = TRACK_ID
            event.gesture_name = "wave_right"
            event.confidence = 1.0
            event.stable = True
            event.observed_duration_s = 1.0
            event.last_seen = now
            event.state = "wave_confirmed"
            self.wave_pub.publish(event)
            self._wave_sent = True
            self.get_logger().info("Synthetisches wave_confirmed-Ereignis gesendet.")


def _start(cmd, log_path):
    # `ros2 run` spawnt das eigentliche Node-Executable als eigenen
    # Kind-Prozess (kein os.exec) -- p.terminate() auf den "ros2 run"-
    # Wrapper-PID toetet NUR den Wrapper, das eigentliche Node-Executable
    # laeuft als Waise weiter (per Live-Test gefunden: verwaiste bt_executor_
    # node/supervisor_node/... liefen nach Testlaeufen weiter und
    # verfaelschten den naechsten Lauf mit doppelten Action-Servern/
    # Publishern). start_new_session=True + os.killpg() beim Aufraeumen
    # toetet die GESAMTE Prozessgruppe, nicht nur den Wrapper.
    #
    # stdout/stderr NIE auf subprocess.PIPE ohne aktives Auslesen --
    # ein Node, der genug loggt (z.B. bt_executor bei jedem
    # PlayDailyPresentation-Fehlschlag), fuellt den OS-Pipe-Puffer
    # (typisch 64KB) und BLOCKIERT dann im write()-Aufruf, bis jemand
    # liest -- ein per Live-Test gefundener, echter Deadlock-Kandidat.
    # Stattdessen in eine Datei umleiten.
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
    log_dir = "/tmp/e2e_offline_check_logs"
    os.makedirs(log_dir, exist_ok=True)
    procs = [
        _start(["ros2", "run", "ihk_pepper_bridge", "bridge_node",
                "--ros-args", "-r", "__ns:=/pepper_bridge", "-p", "dry_run:=true"],
               f"{log_dir}/bridge.log"),
        _start(["ros2", "run", "ihk_pepper_interaction", "supervisor_node",
                "--ros-args", "-p", "motion_capable:=true"],
               f"{log_dir}/supervisor.log"),
        _start(["ros2", "run", "ihk_pepper_navigation", "mock_nav2_server",
                "--ros-args", "-p", "travel_time_s:=1.0"],
               f"{log_dir}/mock_nav2.log"),
        _start(["ros2", "run", "ihk_pepper_navigation", "person_approach_node"],
               f"{log_dir}/person_approach.log"),
        _start(["ros2", "run", "ihk_pepper_behavior_tree", "bt_executor_node",
                "--ros-args", "-p", "tick_rate_hz:=10.0"],
               f"{log_dir}/bt_executor.log"),
    ]
    print(f"Logs unter {log_dir}/*.log")
    time.sleep(3.0)  # Discovery/Startzeit

    rclpy.init()
    driver = E2EDriver()

    # Zwei-Schluessel-Freigabe (siehe Modul-Docstring): motion_capable=true
    # (Launch-Parameter oben) allein reicht nicht, SafetyGate verlangt
    # zusaetzlich diese explizite Anfrage.
    client = driver.create_client(SetMotionPermission, "/set_motion_permission")
    if client.wait_for_service(timeout_sec=10.0):
        req = SetMotionPermission.Request()
        req.allow_motion = True
        req.allow_person_approach = True
        future = client.call_async(req)
        rclpy.spin_until_future_complete(driver, future, timeout_sec=5.0)
        driver.get_logger().info(f"/set_motion_permission Antwort: {future.result()}")
    else:
        driver.get_logger().error("/set_motion_permission nicht erreichbar!")

    start_t = time.time()
    reached = False
    try:
        while time.time() - start_t < TIMEOUT_S:
            rclpy.spin_once(driver, timeout_sec=0.5)
            if driver.interaction_state_name == "CONVERSATION_READY":
                reached = True
                break
    finally:
        cmd_vel_seen = driver.cmd_vel_seen
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

    elapsed = time.time() - start_t
    if cmd_vel_seen:
        print("ERGEBNIS: FEHLGESCHLAGEN -- /cmd_vel wurde waehrend des Laufs veroeffentlicht! "
              "Das darf in KEINEM Testmodus passieren.")
        return 2
    if reached:
        print(f"ERGEBNIS: CONVERSATION_READY nach {elapsed:.1f}s erreicht, "
              f"kein /cmd_vel gesehen. E2E-Ablauf OK.")
        return 0
    print(f"ERGEBNIS: CONVERSATION_READY NICHT erreicht innerhalb {TIMEOUT_S}s "
          f"(letzter Zustand: {driver.interaction_state_name}).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
