import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from example_interfaces.action import Fibonacci

class ActionClientNode(Node):
    def __init__(self):
        super().__init__('action_client_node')
        self.fibonacci_action_client = ActionClient(self, Fibonacci, 'fibonacci')
        while not self.fibonacci_action_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().info('Waiting for Fibonacci action server...')

    def call_fibonacci_action(self, order):
        goal_msg = Fibonacci.Goal()
        goal_msg.order = order

        self.get_logger().info(f'Sending Fibonacci goal: {order}')
        future = self.fibonacci_action_client.send_goal_async(goal_msg, feedback_callback=self.feedback_callback)
        future.add_done_callback(self.goal_response_callback)

    def feedback_callback(self, feedback):
        self.get_logger().info(f'Feedback received: {feedback.feedback.partial_sequence}')

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Goal rejected')
            return

        self.get_logger().info('Goal accepted')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

    def result_callback(self, future):
        if future.result():
            self.get_logger().info(f'Fibonacci result: {future.result().result.sequence}')
        else:
            self.get_logger().error('Fibonacci action failed')