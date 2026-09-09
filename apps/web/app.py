# app.py
from flask import Flask, request, render_template, url_for
import signal, sys
import config.config as _cfg
try:
    # example_interfaces (fuer den AddTwoInts-Demo-Service) ist auf diesem
    # System nicht per apt installiert; der ros2_node wird unten ohnehin
    # nicht aktiviert, daher soll ein fehlendes Paket hier nicht den ganzen
    # Server blockieren.
    from ros2com.ros2 import initialize_ros2_node
except Exception as e:
    print(f"ros2com nicht verfuegbar, ROS2-Demo-Routen deaktiviert: {e}")
    initialize_ros2_node = None
from adbcom.adb import adbhelper
from llm.anythingllm import anything_llm_helper
from pepper.qicli import qicli
from tablet.ros_bridge import bridge as tablet_bridge
from tablet_ui import tablet_bp

# Initialize the Flask app and ROS 2 node
app = Flask(__name__)
app.register_blueprint(tablet_bp)
# Startet den ROS2-Hintergrund-Thread fuer die Tablet-UI (Abschnitt 20).
# Faellt lautlos auf den "offline"-Modus zurueck, wenn ROS2 nicht gesourced
# ist -- siehe tablet/ros_bridge.py Moduldoku.
tablet_bridge.start()
#ros2_node = initialize_ros2_node()
ros2_node = None  # deaktiviert (example_interfaces fehlt, siehe oben) --
                  # ohne diese Zeile war der Name unten gar nicht definiert
                  # (NameError bei jedem Aufruf, gefunden per CI-Linting).
try:
    adb = adbhelper(_cfg.PHONE_IP, _cfg.ADB_PORT)
except Exception as e:
    # ADB/Tablet ist ein optionales Nebenfeature (Telefon waehlen) und soll
    # den Server nicht blockieren, wenn kein adb-Binary/Telefon vorhanden ist.
    print(f"ADB nicht verfuegbar, Telefon-Funktionen deaktiviert: {e}")
    adb = None
anyllm = anything_llm_helper(_cfg.API_BASE_URL,_cfg.API_TOKEN)
qicli = qicli(_cfg.QI_HOST, _cfg.QI_USER, _cfg.QI_PW)

# Entwicklungsauftrag 04-B, AP5B, Abschnitt 15: app.py ist ein manuelles
# Entwicklerwerkzeug aus einer FRUEHEN Projektphase -- jede Route, die
# qicli direkt anspricht, umgeht die gesamte Bridge-/Aktuator-Arbiter-
# Sicherheitskette (Lease/Cancel/tts_guard, siehe
# ihk_pepper_bridge/bridge_node.py). Sicherer Default: gesperrt (siehe
# _hardware_test_guard() unten und config.py). NIE automatisch als Teil
# eines Produktions-/Live-Starts aktivieren.
if _cfg.WEB_HARDWARE_TEST_ENABLED:
    print(
        "WARNUNG: PEPPER_WEB_HARDWARE_TEST_ENABLED=true -- app.py kann Pepper "
        "DIREKT ansteuern, an Bridge/Aktuator-Arbiter vorbei. Nur fuer einen "
        "bewusst beaufsichtigten Hardwaretest verwenden."
    )
else:
    print(
        "app.py: direkte Hardwareaktionen sind gesperrt "
        "(PEPPER_WEB_HARDWARE_TEST_ENABLED=false, Standard)."
    )


def _hardware_test_guard():
    """Gibt (payload, 403) zurueck, wenn direkte Hardwareaktionen gesperrt
    sind, sonst None. JEDE Route, die qicli anspricht, ruft das zuerst auf."""
    if _cfg.WEB_HARDWARE_TEST_ENABLED:
        return None
    return {
        "error": (
            "Direkte Hardwareaktionen sind in app.py per Default gesperrt "
            "(manuelles Entwicklerwerkzeug, umgeht Bridge/Aktuator-Arbiter). "
            "Nur mit PEPPER_WEB_HARDWARE_TEST_ENABLED=true in einem bewusst "
            "beaufsichtigten Hardwaretest aktivierbar."
        )
    }, 403



#qicli.setAutonomousLife(False)


# qicli.setLanguage("English")
# qicli.say("Hello")
# qicli.setLanguage("German")
# qicli.say("Deutschland")
#qicli.setBreathing(True)



@app.route('/')
def index():
    return render_template('index.html')

@app.route('/execute', methods=['POST'])
def execute():
    func_name = request.form.get("function")
    result = None
    error = None

    guard = _hardware_test_guard()
    if guard is not None:
        error = guard[0]["error"]
        return render_template('result.html', function=func_name, result=result, error=error), 403

    try:
        if func_name == "say":
            message = request.form.get("message")
            result = qicli.say(message)
        elif func_name == "moveTo":
            x = float(request.form.get("x"))
            y = float(request.form.get("y"))
            theta = float(request.form.get("theta"))
            result = qicli.moveTo(x, y, theta)
        elif func_name == "enableAutonomousLife":
            # The select element returns "True" or "False" strings.
            enabled = request.form.get("enabled") == "True"
            result = qicli.setAutonomousLife(enabled)
        elif func_name == "setLanguage":
            language = request.form.get("language")
            result = qicli.setLanguage(language)
        elif func_name == "setBreathing":
            enabled = request.form.get("enabled") == "True"
            result = qicli.setBreathing(enabled)
        elif func_name == "showImage":
            image_path = request.form.get("image_path")
            result = qicli.showImage(image_path)
        else:
            error = f"Unknown function: {func_name}"
    except Exception as e:
        error = str(e)

    return render_template('result.html', function=func_name, result=result, error=error)


@app.route('/latest_message')
def get_latest_message():
    # ros2_node bleibt deaktiviert (example_interfaces fehlt, siehe oben) --
    # ohne diese Absicherung wuerde dieser Demo-Endpunkt mit einem
    # NameError abstuerzen (gefunden per CI-Linting, siehe
    # docs/GITHUB_DEPLOYMENT_REPORT.md). Kein Verlust echter Funktionalitaet:
    # ros2_node war nie aktiviert.
    if ros2_node is None:
        return {'error': 'ROS2-Demo-Node nicht aktiv (example_interfaces fehlt)'}, 503
    return {'message': ros2_node.latest_message}

@app.route('/publish_message')
def publish_message():
    if ros2_node is None:
        return {'error': 'ROS2-Demo-Node nicht aktiv (example_interfaces fehlt)'}, 503
    ros2_node.publish_message("Hello World")
    return {}


@app.route('/al/<enable>', methods=['GET', 'POST'])
def alenable(enable):
#    ros2_node.publish_message(text)
    guard = _hardware_test_guard()
    if guard is not None:
        return guard
    if enable:
        output, error = qicli.setAutonomousLife(True)
    else:
        output, error = qicli.setAutonomousLife(False)
    return{}

@app.route('/logo', methods=['GET', 'POST'])
def showLogo():
#    ros2_node.publish_message(text)
    guard = _hardware_test_guard()
    if guard is not None:
        return guard
    output, error = qicli.showImage(f"http://{_cfg.PC_IP}:5000/static/images/spotai.jpg")
    return{}



@app.route('/say/<text>', methods=['GET', 'POST'])
def say(text):
#    ros2_node.publish_message(text)
    guard = _hardware_test_guard()
    if guard is not None:
        return guard
    output, error = qicli.say(text)
    return{}

@app.route('/call_service')
def call_service(a=1,b=2):
    if ros2_node is None:
        return {'error': 'ROS2-Demo-Node nicht aktiv (example_interfaces fehlt)'}, 503
    ros2_node.call_add_two_ints(a,b)
    return {}

@app.route('/add_two_ints', methods=['POST'])
def add_two_ints():
    if ros2_node is None:
        return {'error': 'ROS2-Demo-Node nicht aktiv (example_interfaces fehlt)'}, 503
    data = request.json
    a = data.get('a')
    b = data.get('b')
    if a is None or b is None:
        return {'error': 'Both a and b must be provided'}, 400
    ros2_node.call_add_two_ints(a, b)
    result = ros2_node.get_latest_service_result()
    if result is not None:
        return {'sum': result}
    return {'error': 'Service result not available yet'}, 202

@app.route('/list_devices',  methods=['GET', 'POST'])
def list_devices():
    if adb is None:
        return {'error': 'ADB nicht verfuegbar (kein adb-Binary installiert)'}, 503
    print("listing devices")
    devices = adb.list_devices()
    if devices.returncode == 0:
        return {'devices': f"{devices.stdout}"}, 200
    else:
        return {'error': f"process finished with code: {devices.returncode}"}

@app.route('/call_phone/<number>', methods=['GET', 'POST'])
def call_phone(number):
    if adb is None:
        return {'error': 'ADB nicht verfuegbar (kein adb-Binary installiert)'}, 503
    result = adb.call_number(number)
    return {'OUTPUT': f"{result.stdout}"}, 200 



def handle_sigint(signum, frame):
    qicli.close()
    tablet_bridge.stop()
    sys.exit(0)

# Register the SIGINT handler.
signal.signal(signal.SIGINT, handle_sigint)


if __name__ == "__main__":
    # Vorgefunden: app.py hatte bisher KEINEN Einstiegspunkt (kein
    # app.run()) -- .flaskenv/run.sh verwiesen auf ein nicht mehr
    # existierendes 'flask_rclpy.py' und run.sh sourcte ROS Humble statt
    # Jazzy. Direkter Start ("python3 app.py") ist robuster als von einer
    # FLASK_APP-Umgebungsvariable abzuhaengen -- daher hier ergaenzt,
    # bestehende Routen/Variablen bleiben unveraendert (Auftrag 3.1).
    app.run(host="0.0.0.0", port=5000, debug=False)