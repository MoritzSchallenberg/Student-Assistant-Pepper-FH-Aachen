#!/bin/bash
# Startet apps/web mit ROS2-Anbindung (fuer die Tablet-UI,
# Abschnitt 20). Ohne ROS2 laeuft app.py trotzdem, die Tablet-Ansicht
# zeigt dann dauerhaft "offline" (siehe tablet/ros_bridge.py).
#
# Korrigiert (2026-08-20): source zeigte bisher auf ROS Humble, dieses
# System nutzt aber ROS2 Jazzy (siehe docs/STATUS.md/docs/INSTALL.md).
set -e
cd "$(dirname "$0")"
source /opt/ros/jazzy/setup.bash
if [ -f ../ros2/autonomy_ws/install/setup.bash ]; then
    source ../ros2/autonomy_ws/install/setup.bash
fi
source venv/bin/activate
python3 app.py
