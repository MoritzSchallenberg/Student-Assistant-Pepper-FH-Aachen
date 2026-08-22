#!/bin/bash
# Startet flask_wrapper mit ROS2-Anbindung (fuer die Tablet-UI,
# Abschnitt 20). Ohne ROS2 laeuft app.py trotzdem, die Tablet-Ansicht
# zeigt dann dauerhaft "offline" (siehe tablet/ros_bridge.py).
#
# Korrigiert (2026-08-20): source zeigte bisher auf ROS Humble, dieses
# System nutzt aber ROS2 Jazzy (siehe STATUS.md/INSTALL.md).
set -e
cd "$(dirname "$0")"
source /opt/ros/jazzy/setup.bash
if [ -f ../pepper_autonomy_ws/install/setup.bash ]; then
    source ../pepper_autonomy_ws/install/setup.bash
fi
source venv/bin/activate
python3 app.py
