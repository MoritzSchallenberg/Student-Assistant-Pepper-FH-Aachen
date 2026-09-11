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

# Entwicklungsauftrag 04-B, AP8.4 (bestaetigter Fund, siehe
# DEVELOPMENT_ORDER_04_B_REPORT.md AP8 Commit 1/11, Abschnitt 3.4):
# dieselbe Grenze/Herkunft wie gesture_catalog.py::MAX_JOINT_VELOCITY_RAD_S
# (die YAML-Ladepruefung selbst, auf der UNSKALIERTEN Zeitachse). Hier
# als eigene Konstante gefuehrt statt importiert, um denselben
# Zirkel-Import wie bei MAX_JOINT_ACCEL_RAD_S2 zu vermeiden
# (gesture_catalog.py importiert bereits von diesem Modul) -- KEIN neuer
# Grenzwert, derselbe dokumentierte Wert. Wird HIER auf der SKALIERTEN
# Zeitachse erneut geprueft (Auftrag Abschnitt 3.4: "Geschwindigkeit wird
# nach Speed-Skalierung erneut geprueft" -- die YAML-Ladepruefung allein
# haette einen speed_scale > 1 nicht erfasst).
MAX_JOINT_VELOCITY_RAD_S = 3.0

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


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))  # value==value ist False fuer NaN


def _check_velocity(joint: str, times: list, angles: list) -> None:
    """Entwicklungsauftrag 04-B, AP8.4: Geschwindigkeit zwischen JEDEM
    Punktepaar auf der SKALIERTEN Zeitachse (times/angles koennen hier
    zusaetzlich einen vorangestellten Startpose-Punkt bei t=0 enthalten,
    siehe compile() -- ein Keyframe bei time_from_start_s==0, dessen
    Winkel von der tatsaechlichen Startpose abweicht, verlangt dann
    dt==0 bei d_angle!=0 -> Geschwindigkeit unendlich -> wird hier
    zuverlaessig abgelehnt, ohne einen separaten Sondercode fuer den
    "t=0-Sprung"-Fall zu brauchen)."""
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        d_angle = abs(angles[i] - angles[i - 1])
        if dt > 0:
            velocity = d_angle / dt
        else:
            velocity = float("inf") if d_angle > 0 else 0.0
        if velocity > MAX_JOINT_VELOCITY_RAD_S:
            raise KinematicCompileError(
                f"Gelenk '{joint}': Geschwindigkeit {velocity:.2f} rad/s bei t={times[i]:.2f}s "
                f"ueber der Grenze ({MAX_JOINT_VELOCITY_RAD_S} rad/s, nach speed_scale-Skalierung "
                "erneut geprueft)"
            )


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
        # Entwicklungsauftrag 04-B, AP8.4 (bestaetigter Fund): "scale <= 0"
        # allein faengt KEIN NaN ab (NaN <= 0 ist in Python False) -- ein
        # NaN/inf speed_scale waere sonst stillschweigend durchgerutscht.
        if not _is_finite(scale) or scale <= 0:
            raise KinematicCompileError(f"speed_scale muss endlich und > 0 sein, war {scale!r}")

        all_joints = gesture.affected_joints()
        effective_start_pose = dict(NEUTRAL_STAND_POSE)
        if start_pose is not None:
            # Entwicklungsauftrag 04-B, AP8.4 (bestaetigter Fund): ein
            # TEILWEISE fehlgeschlagener Startpose-Snapshot (get_angle()
            # scheiterte fuer einzelne Gelenke, siehe pepper_client.py::
            # restore_joints()' bestehende "if angle is not None"-Pruefung
            # fuer denselben Fall) wurde bisher STILLSCHWEIGEND durch
            # NEUTRAL_STAND_POSE ersetzt -- eine erratene Neutralpose ist
            # aber KEINE sichere Aussage ueber die tatsaechliche aktuelle
            # Position. Jetzt fail-closed: ein von DIESER Geste
            # benoetigtes Gelenk mit explizitem None im uebergebenen
            # start_pose bricht die Kompilierung ab, statt einen
            # Uebergang zu bewerten, der gar nicht sicher bewertbar ist.
            failed_joints = sorted(
                j for j in all_joints if j in start_pose and start_pose[j] is None)
            if failed_joints:
                raise KinematicCompileError(
                    f"Geste '{gesture.name}': Startpose-Snapshot fuer {failed_joints} nicht "
                    "lesbar -- kein sicherer Startpose-Uebergang bewertbar, Abbruch statt einer "
                    "geschaetzten Neutralpose."
                )
            effective_start_pose.update({j: a for j, a in start_pose.items() if a is not None})

        filled = fill_missing_joint_holds(gesture.keyframes, all_joints, effective_start_pose)

        # Verteidigung in der Tiefe (siehe Moduldoku): auch synthetisch
        # eingefuegte Haltewerte (aus start_pose/NEUTRAL_STAND_POSE) werden
        # hier validiert, nicht nur die woertlich in der YAML stehenden.
        for kf in filled:
            for joint, angle in kf["joints"].items():
                if not _is_finite(float(angle)):
                    raise KinematicCompileError(
                        f"Geste '{gesture.name}': Winkel fuer '{joint}' bei "
                        f"t={kf['time_from_start_s']} ist NaN/inf."
                    )
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
            # Entwicklungsauftrag 04-B, AP8.4: Uebergang von der
            # tatsaechlichen Startpose zum ERSTEN Keyframe mitpruefen --
            # ein virtueller Punkt bei t=0 mit dem Startpose-Winkel wird
            # NUR fuer diese Geschwindigkeitspruefung vorangestellt
            # (nicht Teil der eigentlichen Trajektorie/Beschleunigungs-
            # pruefung). Deckt strukturell auch den "t=0-Sprung"-Fall ab:
            # steht der erste Keyframe bereits bei t=0 UND weicht sein
            # Winkel von der Startpose ab, ist dt=0 bei d_angle!=0 ->
            # Geschwindigkeit unendlich -> wird von _check_velocity()
            # zuverlaessig abgelehnt.
            times_with_start = [0.0] + times
            angles_with_start = [effective_start_pose[joint]] + angles
            _check_velocity(joint, times_with_start, angles_with_start)
            _check_acceleration(joint, times, angles)
            angle_lists.append(angles)
            time_lists.append(list(times))  # jetzt fuer JEDES Gelenk identisch

        effective_duration_s = times[-1] if times else 0.0
        # Entwicklungsauftrag 04-B, AP8.4: max_duration_s gilt fuer die
        # EFFEKTIVE (skalierte) Dauer -- unabhaengige Pruefung zusaetzlich
        # zur Ausfuehrungsrichtlinie (gesture_execution_policy.py), greift
        # auch fuer Aufrufer, die den Compiler direkt nutzen (z.B.
        # gesturectl dry-run/preview).
        if gesture.max_duration_s is not None and effective_duration_s > gesture.max_duration_s:
            raise KinematicCompileError(
                f"Geste '{gesture.name}': effektive Dauer {effective_duration_s:.2f}s "
                f"ueberschreitet max_duration_s={gesture.max_duration_s}s bei speed_scale={scale:.2f}."
            )

        return TrajectoryPlan(
            joint_names=joint_names,
            angle_lists=angle_lists,
            time_lists=time_lists,
            source_gesture_name=gesture.name,
            max_duration_s=effective_duration_s,
            disable_breathing_parts=list(gesture.disable_breathing),
        )
