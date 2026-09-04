#!/usr/bin/env python3
"""
mock_nav2_server: simuliert Nav2s NavigateToPose-Action-Server, OHNE
jemals /cmd_vel oder irgendeinen anderen Fahrbefehl zu veroeffentlichen
(Entwicklungsauftrag 1, Abschnitt 6/11/12: "kein Test darf echte
Fahrbefehle auf /cmd_vel veroeffentlichen").

Nur fuer offline_test/navigation_dry_run-artige Betriebsmodi -- laesst
person_approach_node.py (das echte NavigateToPose-Ziele an
"navigate_to_pose" schickt) den kompletten Ablauf bis CONVERSATION_READY
durchlaufen, ohne dass ein echtes Nav2 installiert/gestartet sein muss.

Simuliert Fortschritt ueber `travel_time_s` (konfigurierbar), meldet
zwischendurch Feedback (abnehmende distance_remaining), akzeptiert
Cancel-Anfragen sofort (fuer Safety-Abbruch-Tests).
"""
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node


class MockNav2Server(Node):
    def __init__(self):
        super().__init__("mock_nav2_server")

        self.declare_parameter("action_name", "navigate_to_pose")
        self.declare_parameter("travel_time_s", 2.0)
        self.declare_parameter("feedback_rate_hz", 5.0)

        self._server = ActionServer(
            self, NavigateToPose, self.get_parameter("action_name").value,
            execute_callback=self._execute,
            goal_callback=self._accept_goal,
            cancel_callback=self._accept_cancel,
            callback_group=ReentrantCallbackGroup(),
        )

        self.get_logger().warn(
            f"mock_nav2_server gestartet auf '{self.get_parameter('action_name').value}' -- "
            f"MOCK, published NIEMALS /cmd_vel. Nur fuer offline_test/navigation_dry_run."
        )

    def _accept_goal(self, goal_request):
        return GoalResponse.ACCEPT

    def _accept_cancel(self, goal_handle):
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        travel_time_s = self.get_parameter("travel_time_s").value
        feedback_rate = self.get_parameter("feedback_rate_hz").value
        target: PoseStamped = goal_handle.request.pose

        steps = max(1, int(travel_time_s * feedback_rate))
        for i in range(steps):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = NavigateToPose.Result()
                result.error_msg = "mock_cancelled"
                return result

            feedback = NavigateToPose.Feedback()
            feedback.current_pose = target  # Mock: "unterwegs" ohne echte Zwischenpositionen
            feedback.distance_remaining = max(0.0, 1.0 - (i / steps))
            goal_handle.publish_feedback(feedback)
            time.sleep(1.0 / feedback_rate)

        goal_handle.succeed()
        result = NavigateToPose.Result()
        result.error_code = NavigateToPose.Result.NONE
        return result


def main(args=None):
    rclpy.init(args=args)
    node = MockNav2Server()
    executor = rclpy.executors.MultiThreadedExecutor()
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
