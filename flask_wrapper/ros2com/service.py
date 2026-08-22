import rclpy
from rclpy.node import Node
from example_interfaces.srv import AddTwoInts

class ServiceClientNode(Node):
    def __init__(self):
        super().__init__('service_client_node')
        self.add_two_ints_client = self.create_client(AddTwoInts, 'add_two_ints')
        while not self.add_two_ints_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('Waiting for AddTwoInts service...')

    def call_add_two_ints(self, a, b):
        request = AddTwoInts.Request()
        request.a = a
        request.b = b

        future = self.add_two_ints_client.call_async(request)
        future.add_done_callback(self.response_callback)

    def response_callback(self, future):
        if future.result():
            self.get_logger().info(f'Service result: {future.result().sum}')
        else:
            self.get_logger().error('Service call failed')