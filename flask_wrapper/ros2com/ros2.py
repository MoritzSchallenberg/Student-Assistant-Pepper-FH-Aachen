import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from example_interfaces.srv import AddTwoInts
import threading
import signal

class TestPublisher(Node):
    def __init__(self):
        super().__init__('test_publisher')
        self.publisher = self.create_publisher(String, 'flask_pub_topic', 10)
        self.subscription = self.create_subscription(
            String,
            '/topic',
            self.chatter_callback,
            10)
        self.latest_message = None

        # Client for AddTwoInts service
        self.add_two_ints_client = self.create_client(AddTwoInts, 'add_two_ints')
        while not self.add_two_ints_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('Service add_two_ints not available, waiting again...')

    def chatter_callback(self, msg):
        print(f'chatter cb received: {msg.data}')
        self.latest_message = msg.data

    def publish_message(self,text):
        msg = String()
        msg.data = text
        self.publisher.publish(msg)

    def call_add_two_ints(self, a, b):
        request = AddTwoInts.Request()
        request.a = a
        request.b = b

        future = self.add_two_ints_client.call_async(request)

        def response_callback(future):
            if future.result() is not None:
                self.get_logger().info(f'Service result: {future.result().sum}')
                self.latest_service_result = future.result().sum
            else:
                self.get_logger().error('Service call failed')
                self.latest_service_result = None

        future.add_done_callback(response_callback)

    def get_latest_service_result(self):
        return getattr(self, 'latest_service_result', None)

def ros2_thread(node):
    print('entering ros2 thread')
    rclpy.spin(node)
    print('leaving ros2 thread')

def initialize_ros2_node():
    rclpy.init(args=None)
    ros2_node = TestPublisher()
    threading.Thread(target=ros2_thread, args=[ros2_node]).start()

    # Set up signal handling to cleanly shut down ROS 2
    prev_sigint_handler = signal.signal(signal.SIGINT, lambda signal, frame: _sigint_handler(signal, frame, prev_sigint_handler))
    return ros2_node

def _sigint_handler(signal, frame, prev_sigint_handler):
    rclpy.shutdown()
    if prev_sigint_handler is not None:
        prev_sigint_handler(signal, frame)
