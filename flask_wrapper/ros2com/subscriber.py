import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SubscriberNode(Node):
    def __init__(self):
        super().__init__('subscriber_node')
        self.subscription = self.create_subscription(
            String,
            '/topic',
            self.chatter_callback,
            10)
        self.latest_message = None

    def chatter_callback(self, msg):
        self.get_logger().info(f'Received message: {msg.data}')