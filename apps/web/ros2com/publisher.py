import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class PublisherNode(Node):
    def __init__(self):
        super().__init__('publisher_node')
        self.publisher = self.create_publisher(String, 'flask_pub_topic', 10)

    def publish_message(self):
        msg = String()
        msg.data = 'hello, world!'
        self.publisher.publish(msg)

