"""
Kinematischer Compiler fuer v2-Gesten (Entwicklungsauftrag 3, AP12):
Gesture (Keyframes) -> TrajectoryPlan (vollstaendig aufgeloest, EINE
gemeinsame Zeitachse fuer alle Gelenke).

Behebt drei zuvor moegliche Schwaechen des direkten Keyframe->
play_trajectory-Mappings in gesture_catalog.py::_play_v2 (siehe
docs/DEVELOPMENT_ORDER_03_REPORT.md AP12):

1. Ein Gelenk, das nicht in jedem Keyframe vorkommt, bekam bisher NUR an
   den Zeitpunkten einen Eintrag, an denen es explizit genannt wird --
   andere Gelenke bekamen dadurch faktisch eine ANDERE Zeitachse als
   dieses Gelenk, obwohl beide in DEMSELBEN play_trajectory()-Aufruf
   landen (der laut qicli.py genau EINE gemeinsame Zeitachse je Gelenk
   erwartet). fill_missing_joint_holds() gleicht das an, indem fehlende
   Werte durch den zuletzt bekannten Winkel (oder den Startwinkel)
   aufgefuellt werden -- kein Sprung, keine Fantasieposition.
2. Der Startzustand eines Gelenks, das erst in einem spaeteren Keyframe
   auftaucht, war zuvor undefiniert. compile() verlangt einen expliziten
   start_pose (typischerweise ein snapshot_joints()-Ergebnis) oder faellt
   auf NEUTRAL_STAND_POSE zurueck -- niemals "aktuelle Ist-Position
   unbekannt, irgendein Wert wird schon passen".
3. Nur Geschwindigkeit wurde geprueft (gesture_catalog.py::
   _validate_v2_velocity), nicht Beschleunigung. compile() prueft
   zusaetzlich die Beschleunigung (zweite Ableitung der Winkel-Zeit-
   Kurve, einfache Schwellenwertpruefung) NACH Anwendung des
   speed_scale -- ein hoher speed_scale kann eine an sich unauffaellige
   Geste beschleunigungsseitig unzulaessig machen.

Verteidigung in der Tiefe: Gesture._validate_v2() prueft nur Winkel, die
WOERTLICH in einem Keyframe stehen. Ein durch fill_missing_joint_holds()
synthetisch eingefuegter Haltewert (aus start_pose ODER NEUTRAL_STAND_POSE)
durchlief diese Pruefung nie. compile() validiert deshalb JEDEN --
auch jeden synthetisch eingefuegten -- Winkel zusaetzlich mit
validate_angle_with_margin(), bevor ein TrajectoryPlan zurueckgegeben
wird (gleiches Prinzip wie in pepper_client.py::play_trajectory()
dokumentiert: "kann theoretisch auch mit Werten aufgerufen werden, die
nicht aus einer geladenen Gesture stammen").
"""
from __future__ import annotations

from .joint_limits import ALLOWED_GESTURE_JOINTS, JointLimitError, validate_angle_with_margin

# Keine gemessene Referenz vorhanden (wie schon bei MAX_JOINT_VELOCITY_RAD_S
# in gesture_catalog.py dokumentiert) -- konservativ gewaehlt: bei der live
# getesteten wave_right-Oszillation (0.6->1.6 rad in 0.4s, danach wieder
# zurueck) ergibt sich eine Beschleunigung von grob (2.5 - (-2.5))/0.4 =
# 12.5 rad/s^2 am Umkehrpunkt -- die Grenze liegt großzügig darueber, damit
# dieser bewiesene Fall nicht faelschlich abgelehnt wird, waehrend klar
# ruckartigere, nie erprobte Bewegungen weiterhin blockiert werden.
MAX_JOINT_ACCEL_RAD_S2 = 25.0

# Neutrale Fallback-Haltung (rad) fuer Gelenke ohne uebergebenen start_pose
# UND ohne fruehere Erwaehnung in der Geste -- entspricht der in AP13 als
# eigene Geste "neutral_stand" hinterlegten Pose (0.0 bzw. dokumentierter
# neutraler Wert je Gelenk), hier als reine Zahlenkonstante, damit der
# Compiler ohne Zugriff auf den Gestenkatalog selbst funktioniert.
NEUTRAL_STAND_POSE = {joint: 0.0 for joint in ALLOWED_GESTURE_JOINTS}
# RShoulderRoll/LShoulderRoll: 0.0 liegt ausserhalb der bekannten Grenzen
# (siehe joint_limits.py, beide Grenzen schliessen 0 aus) -- neutrale Arme
# haengen leicht angewinkelt, nicht exakt am Koerper.
NEUTRAL_STAND_POSE["LShoulderRoll"] = 0.15
NEUTRAL_STAND_POSE["RShoulderRoll"] = -0.15
# LElbowRoll/RElbowRoll: 0.0 liegt jeweils GENAU auf der margenbereinigten
# Grenze (siehe joint_limits.py: LElbowRoll-Obergrenze 0.05, RElbowRoll-
# Untergrenze -0.05, SAFETY_MARGIN_RAD=0.05) -- funktional zwar noch
# zulaessig, aber ohne jeden Abstand. Bewusst leicht nach innen versetzt.
NEUTRAL_STAND_POSE["LElbowRoll"] = -0.02
NEUTRAL_STAND_POSE["RElbowRoll"] = 0.02


class KinematicCompileError(ValueError):
    pass


def fill_missing_joint_holds(keyframes: list, all_joints: list, start_pose: dict) -> list:
    """Reine Funktion: gibt eine NEUE Keyframe-Liste zurueck, in der JEDES
    Gelenk aus all_joints in JEDEM Keyframe einen Wert hat. Ein Gelenk ohne
    Eintrag im aktuellen Keyframe bekommt den Wert des zuletzt bekannten
    Keyframes (Haltewert); taucht es ueberhaupt noch nicht auf, den Wert aus
    start_pose (KeyError falls dort auch nicht vorhanden -- kein stilles
    Erraten)."""
    last_known = dict(start_pose)
    filled = []
    for kf in keyframes:
        joints = dict(kf["joints"])
        for joint in all_joints:
            if joint in joints:
                last_known[joint] = joints[joint]
            elif joint in last_known:
                joints[joint] = last_known[joint]
            else:
                raise KinematicCompileError(
                    f"Gelenk '{joint}' hat weder einen Keyframe-Wert vor "
                    f"time_from_start_s={kf['time_from_start_s']} noch einen Startwert -- "
                    "start_pose muss diesen Wert enthalten."
                )
        filled.append({"time_from_start_s": kf["time_from_start_s"], "joints": joints})
    return filled


def _check_acceleration(joint: str, times: list, angles: list) -> None:
    """Grobe Schwellenwertpruefung ueber finite Differenzen zweiter
    Ordnung. times/angles: gleiche Laenge, bereits speed-skaliert."""
    if len(times) < 3:
        return  # Beschleunigung braucht mindestens 3 Punkte
    velocities = []
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        velocities.append((angles[i] - angles[i - 1]) / dt if dt > 0 else float("inf"))
    for i in range(1, len(velocities)):
        dt = times[i + 1] - times[i]
        if dt <= 0:
            continue
        accel = abs(velocities[i] - velocities[i - 1]) / dt
        if accel > MAX_JOINT_ACCEL_RAD_S2:
            raise KinematicCompileError(
                f"Gelenk '{joint}': Beschleunigung {accel:.2f} rad/s^2 bei "
                f"t={times[i + 1]:.2f}s ueber der Grenze ({MAX_JOINT_ACCEL_RAD_S2} rad/s^2)"
            )


class KinematicCompiler:
    """Baut aus einer v2-Gesture (siehe gesture_catalog.py::Gesture) einen
    ausfuehrbaren motion_transport.TrajectoryPlan. Rein/ROS-frei, keine
    Hardwarezugriffe -- start_pose wird injiziert, nicht selbst abgefragt."""

    def compile(self, gesture, speed_scale: float | None = None, start_pose: dict | None = None):
        from .motion_transport import TrajectoryPlan  # lokal, um Zirkel-Import in Tests zu vermeiden

        if gesture.schema_version != 2:
            raise KinematicCompileError(
                f"Geste '{gesture.name}': KinematicCompiler kompiliert nur schema_version 2 "
                f"(v1 bleibt bewusst sequenziell, siehe gesture_catalog.py-Moduldoku)"
            )
        scale = speed_scale if speed_scale is not None else gesture.speed_scale_default
        if scale <= 0:
            raise KinematicCompileError(f"speed_scale muss > 0 sein, war {scale}")

        all_joints = gesture.affected_joints()
        effective_start_pose = dict(NEUTRAL_STAND_POSE)
        if start_pose:
            effective_start_pose.update({j: a for j, a in start_pose.items() if a is not None})

        filled = fill_missing_joint_holds(gesture.keyframes, all_joints, effective_start_pose)

        # Verteidigung in der Tiefe (siehe Moduldoku): auch synthetisch
        # eingefuegte Haltewerte (aus start_pose/NEUTRAL_STAND_POSE) werden
        # hier validiert, nicht nur die woertlich in der YAML stehenden.
        for kf in filled:
            for joint, angle in kf["joints"].items():
                try:
                    validate_angle_with_margin(joint, float(angle))
                except JointLimitError as e:
                    raise KinematicCompileError(
                        f"Geste '{gesture.name}': synthetisch aufgefuellter Wert fuer '{joint}' "
                        f"ungueltig: {e}"
                    ) from e

        # Zeitachse skalieren (identisch zur bisherigen Semantik in
        # gesture_catalog.py::_play_v2: time_from_start_s / speed_scale).
        times = [kf["time_from_start_s"] / scale for kf in filled]

        joint_names = sorted(all_joints)
        angle_lists = []
        time_lists = []
        for joint in joint_names:
            angles = [kf["joints"][joint] for kf in filled]
            _check_acceleration(joint, times, angles)
            angle_lists.append(angles)
            time_lists.append(list(times))  # jetzt fuer JEDES Gelenk identisch

        return TrajectoryPlan(
            joint_names=joint_names,
            angle_lists=angle_lists,
            time_lists=time_lists,
            source_gesture_name=gesture.name,
            max_duration_s=times[-1] if times else 0.0,
            disable_breathing_parts=list(gesture.disable_breathing),
        )
