
class mission_controller:
    def __init__(self, functions):
        """
        Initialize with remote host details.
        :param ip: Remote host IP address.
        :param username: SSH username.
        :param password: SSH password.
        :param port: SSH port (default 22).
        :param timeout: Connection timeout in seconds.
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.client = None


def load_commands():
    """Read commands from the text file and store them in the global list."""
    global commands
    if os.path.exists("commands.txt"):
        with open("commands.txt", "r") as f:
            # Only include non-empty lines (and strip any whitespace)
            commands = [line.strip() for line in f if line.strip()]
    else:
        commands = []