import paramiko
import time
import json

class qicli:
    def __init__(self, ip, username, password, port=22, timeout=10):
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

    def connect(self):
        """
        Establishes an SSH connection to the remote host.

        Pepper's sshd only advertises 'publickey' and 'keyboard-interactive'
        (no plain 'password' method). Newer paramiko versions no longer fall
        back to keyboard-interactive automatically when password auth is
        rejected, so we do that fallback ourselves here.
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                self.client.connect(hostname=self.ip,
                                    username=self.username,
                                    password=self.password,
                                    port=self.port,
                                    timeout=self.timeout)
            except paramiko.ssh_exception.BadAuthenticationType as e:
                if "keyboard-interactive" not in e.allowed_types:
                    raise
                transport = self.client.get_transport()

                def _handler(title, instructions, prompt_list):
                    return [self.password for _ in prompt_list]

                transport.auth_interactive(self.username, _handler)
            print(f"Connected to {self.ip}")
        except Exception as e:
            print(f"Error connecting to {self.ip}: {e}")
            raise

    def exec_command(self, command, use_tmux=False, tmux_session="persistent_session", retries=1):
        """
        Executes a command on the remote host.
        
        :param command: Command to execute.
        :param use_tmux: If True, run the command inside a tmux session.
        :param tmux_session: Name of the tmux session.
        :param retries: Number of retries if command execution fails.
        :return: (output, error) from the command.
        """
        if self.client is None:
            self.connect()

        # If using tmux, prepare the command to either create or use an existing session.
        if use_tmux:
            # Create a new detached tmux session if it doesn't exist,
            # otherwise send the command keys to the session.
            # The || operator helps in case the session already exists.
            command_to_run = (
                f"tmux new-session -d -s {tmux_session} '{command}' || "
                f"tmux send-keys -t {tmux_session} \"{command}\" C-m"
            )

        try:
            stdin, stdout, stderr = self.client.exec_command(f"{command}")
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            return output, error
        except Exception as e:
            print(f"Error executing command: {e}")
            # Attempt a reconnect if possible and retry.
            if retries > 0:
                print("Attempting to reconnect and retry the command...")
                time.sleep(2)  # brief pause before reconnecting
                self.connect()
                return self.exec_command(command, use_tmux, tmux_session, retries - 1)
            else:
                raise

    
    def say(self, annotated_text):
        print(f"qicli call ALAnimatedSpeech.say annotated_text")
        output, error = self.exec_command(f'qicli call ALAnimatedSpeech.say "{annotated_text}"')
        print(f"Output: {output}")
        print(f"Error: {error}")
        return output, error     

    def setVolume(self, value):
        print(f"qicli call ALTextToSpeech.setVolume {value}")
        output, error = self.exec_command(f'qicli call ALTextToSpeech.setVolume "{value}"')
        print(f"Output: {output}")
        print(f"Error: {error}")
        return output, error


    def setAutonomousLife(self, enabled):
        if enabled:
            self.exec_command(f"qicli call ALAutonomousLife.setState solitary")
        else:
            self.exec_command(f"qicli call ALAutonomousLife.setState disabled")
            time.sleep(1)  
            self.exec_command(f"qicli call ALMotion.wakeUp")
            
        
    def setBreathing(self, enabled, part=None):
        time.sleep(1)
        if part is None:
            print(f" {enabled} everything")
            print(f"qicli call ALMotion.setBreathEnabled Body {int(enabled)}")

            output, error  = self.exec_command(f"timeout 8 qicli call ALMotion.setBreathEnabled Body {int(enabled)}")
            time.sleep(0.1)
            self.exec_command(f"timeout 8 qicli call ALMotion.setBreathEnabled Head {int(enabled)}")
            time.sleep(0.1)
            self.exec_command(f"timeout 8 qicli call ALMotion.setBreathEnabled Arms {int(enabled)}")
            time.sleep(0.1)
            self.exec_command(f"timeout 8 qicli call ALMotion.setBreathEnabled Legs {int(enabled)}")
        else:
            self.exec_command(f"timeout 8 qicli call ALMotion.setBreathEnabled {part} {int(enabled)}")

    def setLanguage(self,language):
        output, error = self.exec_command(f"qicli call ALTextToSpeech.setLanguage {language}")
        print(f"Output: {output}")
        print(f"Error: {error}")
        return output, error    

    def moveTo(self, x,y,theta):
        output, error = self.exec_command(f"qicli call ALMotion.moveTo {x} {y} {theta}")
        return output, error     

    def showImage(self,url):
        output, error = self.exec_command(f"qicli call ALTabletService.showImage {url}")
        return output, error

    def showURL(self,url):
        output, error = self.exec_command(f"qicli call ALTabletService.showWebview {url}")
        return output, error

    def hideWebview(self):
        output, error = self.exec_command("qicli call ALTabletService.hideWebview")
        return output, error

    # ------------------------------------------------------------------
    # Generische Gelenk-Steuerung
    # (Basis fuer alle Gesten unten; siehe docs/CAPABILITIES.md fuer Details
    # zu Bool-Syntax/Fallstricken bei qicli)
    # ------------------------------------------------------------------

    def get_angle(self, joint):
        """Aktueller Winkel (rad) eines einzelnen Gelenks, oder None bei Fehler."""
        output, error = self.exec_command(f"timeout 8 qicli call ALMotion.getAngles {joint} 1")
        try:
            return float(output.strip("[]"))
        except (ValueError, AttributeError):
            return None

    def get_angles(self, joints):
        """Aktuelle Winkel mehrerer Gelenke als dict {gelenkname: winkel}."""
        return {j: self.get_angle(j) for j in joints}

    def set_angle(self, joint, angle, duration=1.0):
        """Bewegt ein einzelnes Gelenk zu einem absoluten Zielwinkel (rad).
        Blockiert bis die Bewegung fertig ist (NAOqi-Verhalten)."""
        output, error = self.exec_command(
            f"timeout {int(duration) + 5} qicli call ALMotion.angleInterpolation {joint} {angle} {duration} 1"
        )
        return error == ""

    def play_trajectory(self, joint_names, angle_lists, time_lists, is_absolute=True):
        """Synchrone Multi-Gelenk-Trajektorie in EINEM
        ALMotion.angleInterpolation-Aufruf -- alle Gelenke bewegen sich
        zueinander synchron (NAOqi fuehrt das selbst atomar aus), keine
        sequenziellen Einzelaufrufe wie set_angle(). NAOqis eigene API
        unterstuetzt names[]/angleLists[][]/timeLists[][]/isAbsolute
        nativ; die qicli-CLI-Argumente werden dafuer als JSON kodiert.

        WICHTIG (Entwicklungsauftrag 1, Abschnitt 7): ob die qicli-CLI auf
        diesem Pepper verschachtelte Listen als JSON-Argumente tatsaechlich
        korrekt an ALMotion durchreicht, konnte in dieser Session NICHT
        live geprueft werden (kein Zugriff auf einen echten Pepper). Diese
        Methode ist dry_run_validated, NICHT live_validated -- vor
        produktivem Einsatz einmal einzeln, langsam, unter Aufsicht
        gegenpruefen (siehe docs/GESTURE_AUTHORING.md). Falls die JSON-
        Kodierung nicht funktioniert, ist der sichere Fallback eine
        sequenzielle Ausfuehrung ueber mehrere set_angle()-Aufrufe (KEINE
        echte Synchronitaet -- dann so dokumentieren, nicht vortaeuschen)."""
        max_duration = max((t for times in time_lists for t in times), default=1.0)
        names_json = json.dumps(joint_names)
        angles_json = json.dumps(angle_lists)
        times_json = json.dumps(time_lists)
        output, error = self.exec_command(
            f"timeout {int(max_duration) + 10} qicli call ALMotion.angleInterpolation "
            f"'{names_json}' '{angles_json}' '{times_json}' {int(is_absolute)}"
        )
        return error == ""

    def set_stiffness(self, chain, value):
        """Setzt die Steifigkeit (0.0-1.0) einer Gelenkkette, z.B. 'LArm', 'RArm', 'Head', 'Body'."""
        output, error = self.exec_command(f"timeout 8 qicli call ALMotion.setStiffnesses {chain} {value}")
        return error == ""

    def snapshot_joints(self, joints):
        """Merkt sich die aktuellen Winkel mehrerer Gelenke zum spaeteren Wiederherstellen
        (siehe restore_joints). Nutzen: vor jeder Geste snapshotten, danach restaurieren."""
        return self.get_angles(joints)

    def restore_joints(self, snapshot, duration=1.5):
        """Faehrt Gelenke zurueck auf zuvor mit snapshot_joints() gemerkte Winkel."""
        for joint, angle in snapshot.items():
            if angle is not None:
                self.set_angle(joint, angle, duration)

    # ------------------------------------------------------------------
    # Zusammengesetzte Gesten (auf Basis der generischen Gelenk-Steuerung)
    # ------------------------------------------------------------------

    ARM_POSE_JOINTS = ["LShoulderPitch", "RShoulderPitch", "LShoulderRoll", "RShoulderRoll",
                       "LElbowRoll", "RElbowRoll"]

    def raise_arms_sideways(self, angle=1.3, duration=2.5):
        """
        Streckt beide Arme seitlich aus (T-Pose). Deaktiviert kurz das Breathing
        an den Armen, sonst driftet die Pose sofort zurueck.

        ACHTUNG: Haelt sich nur ca. 10 Sekunden, danach faellt die Pose von
        selbst zurueck (getestet, siehe docs/CAPABILITIES.md) -- fuer kurze
        Gesten gedacht, nicht zum Dauerhalten.

        :return: Snapshot-dict, zum Zuruecksetzen an lower_arms() uebergeben.
        """
        snapshot = self.snapshot_joints(self.ARM_POSE_JOINTS)
        self.setBreathing(False, "Arms")
        self.set_angle("LShoulderPitch", 0.0, duration)
        self.set_angle("RShoulderPitch", 0.0, duration)
        self.set_angle("LElbowRoll", 0.0, duration)
        self.set_angle("RElbowRoll", 0.0, duration)
        self.set_angle("LShoulderRoll", angle, duration)
        self.set_angle("RShoulderRoll", -angle, duration)
        return snapshot

    def lower_arms(self, snapshot, duration=1.5):
        """Faehrt Arme zurueck (Gegenstueck zu raise_arms_sideways) und aktiviert Breathing wieder."""
        self.restore_joints(snapshot, duration)
        self.setBreathing(True, "Arms")

    def wave(self, side="R", repeats=3):
        """Laesst Pepper mit einem Arm winken. side: 'L' oder 'R'."""
        sp, er, ey = f"{side}ShoulderPitch", f"{side}ElbowRoll", f"{side}ElbowYaw"
        snapshot = self.snapshot_joints([sp, er, ey])
        sign = 1 if side == "R" else -1
        self.set_angle(sp, -1.0, 1.0)
        self.set_angle(er, 0.9 * sign, 1.0)
        for _ in range(repeats):
            self.set_angle(ey, 0.6, 0.4)
            self.set_angle(ey, 1.6, 0.4)
        self.restore_joints(snapshot, 1.0)

    # ------------------------------------------------------------------
    # Sensoren / Status (fuer Bedingungs-Knoten im Behavior Tree)
    # ------------------------------------------------------------------

    def get_battery(self):
        """Akkustand in Prozent (int), oder None bei Fehler."""
        output, error = self.exec_command("timeout 8 qicli call ALBattery.getBatteryCharge")
        try:
            return int(output.strip())
        except (ValueError, AttributeError):
            return None

    def get_touch_status(self):
        """Alle Beruehrungssensoren mit aktuellem Zustand, als Python-Liste
        (z.B. [["Head", False, []], ["Bumper/Back", False, []], ...])."""
        output, error = self.exec_command("timeout 8 qicli call ALTouch.getStatus")
        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_mood(self):
        """Erkannte Stimmung der Person vor Pepper (valence/attention inkl.
        Konfidenz), als dict. None wenn gerade niemand erkannt wird."""
        output, error = self.exec_command("timeout 8 qicli call ALMood.currentPersonState")
        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_robot_mood(self):
        """Peppers eigene 'Stimmung' (pleasure/excitement), als dict."""
        output, error = self.exec_command("timeout 8 qicli call ALRobotMood.getState")
        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_posture(self):
        """Name der aktuellen Koerperhaltung, z.B. 'StandInit'."""
        output, error = self.exec_command("timeout 8 qicli call ALRobotPosture.getPosture")
        return output.strip('"') if output else None

    def set_posture(self, name, speed=0.5):
        """Faehrt Pepper in eine benannte Koerperhaltung (z.B. 'Stand', 'StandInit', 'Crouch').
        Vorsicht bei Posen, die groessere Bewegung brauchen -- vorher Platz pruefen."""
        output, error = self.exec_command(f'timeout 15 qicli call ALRobotPosture.goToPosture "{name}" {speed}')
        return output.strip() == "true"

    def get_autonomous_life_state(self):
        """Aktueller Autonomous-Life-Zustand: 'interactive', 'solitary', 'safeguard' oder 'disabled'."""
        output, error = self.exec_command("timeout 8 qicli call ALAutonomousLife.getState")
        return output.strip('"') if output else None

    def set_autonomous_life_state(self, state):
        """Setzt den Autonomous-Life-Zustand direkt (state: 'interactive'/'solitary'/'disabled').
        Vorsicht bei 'disabled' -- kann Steifigkeit/Verhalten grundlegend aendern."""
        output, error = self.exec_command(f'timeout 8 qicli call ALAutonomousLife.setState "{state}"')
        return error == ""

    def get_tactile_gestures(self):
        """Eingebautes Touch-Gesten-Vokabular (SingleTap, DoubleTap, TheClaw, ZoomIn/Out,
        Caress, SecretCode, ...) als dict {name: muster}."""
        output, error = self.exec_command("timeout 8 qicli call ALTactileGesture.getGestures")
        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

    # ------------------------------------------------------------------
    # LEDs
    # ------------------------------------------------------------------

    def set_led_color(self, group, color, duration=0.5):
        """Faerbt eine LED-Gruppe ein (group z.B. 'FaceLeds', 'EarLeds';
        color: Name wie 'blue'/'red' oder Hex-Wert), fuer duration Sekunden Fade-Zeit."""
        output, error = self.exec_command(f'timeout 8 qicli call ALLeds.fadeRGB "{group}" "{color}" {duration}')
        return error == ""

    def reset_led(self, group):
        """Setzt eine LED-Gruppe zurueck auf Standardfarbe."""
        output, error = self.exec_command(f'timeout 8 qicli call ALLeds.reset "{group}"')
        return error == ""

    # ------------------------------------------------------------------
    # Sound
    # ------------------------------------------------------------------

    def play_sound(self, path, loop=False):
        """Spielt eine Sound-Datei auf Pepper ab (Pfad MUSS auf Pepper selbst liegen,
        z.B. unter /opt/aldebaran/share/naoqi/wav/...). loop=True: Dauerschleife."""
        method = "playFileInLoop" if loop else "playFile"
        output, error = self.exec_command(f'timeout 8 qicli call ALAudioPlayer.{method} "{path}"')
        return error == ""

    def close(self):
        """
        Closes the SSH connection.
        """
        if self.client:
            self.client.close()
            print("SSH connection closed.")