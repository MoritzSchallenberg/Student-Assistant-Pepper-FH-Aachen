import subprocess

class adbhelper:
    def __init__(self, ip, port):
        self.adb_path = "/usr/bin/adb"
        if not self._check_adb():
            raise EnvironmentError("ADB is not found. Please ensure it is installed and added to your PATH.")

        self.set_adb_port(port)
        self.connect_adb(ip)
        self.list_devices()

    def _check_adb(self):
        """Check if adb is installed and accessible."""
        try:
            result = self.exec("--version")
            return result.returncode == 0
        except Exception as e:
            print(f"Error checking ADB: {e}")
            return False

    def list_devices(self):
        result = self.exec("devices")
        print(f"Devices:\n{result.stdout}")
        return result

    def set_adb_port(self, port):
        self.exec(f"tcpip {port}")

    def connect_adb(self, ip):
        self.exec(f"connect {ip}")

    def exec(self, command):
        """Execute a single ADB command."""
        full_command = [self.adb_path, command]
        print(f"Executing: {' '.join(full_command)}")
        try:
            result = subprocess.run(full_command, capture_output=True, text=True, check=False)
            return result
        except Exception as e:
            raise RuntimeError(f"An error occurred while executing adb command '{command}': {e}")

    def call_number(self, number):    
        if '*' in number or '#' in number:
            # Special codes like *#06# require the DIAL action
            command = f"shell am start -a android.intent.action.DIAL -d tel:{number}"
        else:
            # Regular phone numbers use the CALL action
            command = f"shell am start -a android.intent.action.CALL -d tel:{number}"
        return self.exec(command)

    def send_sms(self, number, message):
        command = f"shell am start -a android.intent.action.SENDTO -d sms:{number} --es sms_body \"{message}\""
        return self.exec(command)