#!/usr/bin/env python3
"""
gesturectl -- CLI-Werkzeug fuer den Gestenkatalog (Entwicklungsauftrag 3,
AP14). KEIN Shell-Passthrough, KEINE freien ROS2-/qicli-/SSH-Befehle --
jeder Unterbefehl ruft ausschliesslich die bestehende, bereits validierte
Katalog-/Compiler-/Transport-API auf (gesture_catalog.py,
kinematic_compiler.py, motion_transport.py, pepper_client.py).

Unterbefehle: list, validate, show, dry-run, preview, capture-pose,
capture-sequence, compare, live-test, audit, validate-all,
verify-offline. Siehe docs/GESTURE_LIVE_TEST_CHECKLIST.md fuer den
live-test-Ablauf, docs/GESTURE_CAPTURE_WORKFLOW.md fuer capture-sequence,
docs/GESTURE_OFFLINE_EVIDENCE.md fuer verify-offline/validate-all.

Nutzung (nach colcon build):
    ros2 run ihk_pepper_bridge gesturectl list
    ros2 run ihk_pepper_bridge gesturectl show wave_right
    ros2 run ihk_pepper_bridge gesturectl dry-run wave_right
    ros2 run ihk_pepper_bridge gesturectl audit
    ros2 run ihk_pepper_bridge gesturectl validate-all
    ros2 run ihk_pepper_bridge gesturectl verify-offline wave_right --report /tmp/wave_right.json
"""
import argparse
import glob
import os
import sys

from .gesture_capture import (
    CAPTURE_MAX_DURATION_MARGIN_S,
    CAPTURE_SPEED_SCALE_DEFAULT,
    GestureCaptureError,
    atomic_create_exclusive,
    build_candidate_gesture_data,
    capture_sequence,
    derive_name_from_output_path,
    parse_and_validate_joint_list,
    validate_safe_gesture_name,
)
from .gesture_catalog import Gesture, GestureCatalog, GestureValidationError
from .gesture_catalog_audit import audit_catalog, render_audit_report
from .gesture_offline_evidence import (
    verdict_to_exitcode,
    verify_gesture_offline,
    write_report_atomically,
)
from .kinematic_compiler import KinematicCompileError, KinematicCompiler
from .motion_transport import DryRunMotionTransport
from .trajectory_safety import TrajectorySafetyValidator


def _default_gesture_dir():
    """Gleiche Herleitung wie bridge_node.py::_default_gesture_dir() --
    bewusst hier dupliziert statt aus bridge_node.py importiert, damit
    gesturectl OHNE rclpy lauffaehig bleibt (bridge_node.py importiert
    rclpy.node.Node auf Modulebene)."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory("ihk_pepper_bridge"), "config", "gestures")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "gestures"
        )


def _find_robot_model_path() -> str:
    """PEPPER_ROBOT_MODEL_PATH hat Vorrang, sonst wird 'ros2/robot_model'
    vom eigenen Verzeichnis aus nach oben gesucht -- kein absoluter
    Entwicklerpfad im Laufzeitcode (Entwicklungsauftrag 04-B, AP0). Der
    Aufrufer faengt ein fehlendes sim_qicli.py bereits per ImportError
    ab, daher bewusst kein harter Absturz hier -- Fallback auf den
    relativen Pfad, wenn nichts gefunden wird."""
    env_value = os.environ.get("PEPPER_ROBOT_MODEL_PATH")
    if env_value:
        return env_value
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(12):
        candidate = os.path.join(current, "ros2", "robot_model")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return "ros2/robot_model"


def _load_catalog(gesture_dir):
    catalog = GestureCatalog(gesture_dir)
    errors = catalog.reload()
    return catalog, errors


def cmd_list(args):
    catalog, errors = _load_catalog(args.gesture_dir)
    for e in errors:
        print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    for name in catalog.names():
        g = catalog.get(name)
        print(f"{name:24s} v{g.schema_version}  {g.tested_status:18s}  "
              f"{g.duration_s():.2f}s  Gelenke: {', '.join(g.affected_joints())}")
    return 1 if errors else 0


def cmd_audit(args):
    """Entwicklungsauftrag 04-B, AP8 (11/14), Abschnitt 9: deterministische
    Katalogpruefung. Rein lesend -- instanziiert NIE einen Pepper-Client,
    ruft NIE SSH/qicli/eine ROS-Action auf, veraendert NIE eine YAML-Datei.
    Exitcode 0 nur, wenn KEIN Ladefehler und KEIN [ERROR]-Eintrag
    vorliegt -- ein uebersprungener Loader-Eintrag darf den Audit NIE
    faelschlich als Erfolg erscheinen lassen."""
    catalog, errors = _load_catalog(args.gesture_dir)
    total_files = len(glob.glob(os.path.join(args.gesture_dir, "*.yaml")))
    result = audit_catalog(catalog, load_errors=errors, total_yaml_files_found=total_files)
    print(render_audit_report(result), end="")
    return 1 if result.error_count > 0 else 0


def cmd_validate(args):
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
        return 1
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"'{args.name}': Katalog-Validierung OK (schema_version {gesture.schema_version}, "
          f"tested_status={gesture.tested_status}).")
    if gesture.schema_version == 2:
        try:
            plan = KinematicCompiler().compile(gesture, speed_scale=gesture.speed_scale_default)
            print(f"  Kinematik-Compiler OK: {len(plan.joint_names)} Gelenke, "
                  f"Endzeit {plan.max_duration_s:.2f}s.")
        except KinematicCompileError as e:
            print(f"  KINEMATIK-COMPILER-FEHLER: {e}", file=sys.stderr)
            return 1
    return 0


def cmd_show(args):
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"name: {gesture.name}")
    print(f"schema_version: {gesture.schema_version}")
    print(f"description: {gesture.description.strip()}")
    print(f"requires_stationary: {gesture.requires_stationary}")
    print(f"allowed_interaction_states: {gesture.allowed_interaction_states or '(alle)'}")
    print(f"speed_scale_default: {gesture.speed_scale_default}")
    print(f"restore_after: {gesture.restore_after}")
    print(f"tested_status: {gesture.tested_status} (tested_date: {gesture.tested_date})")
    print(f"affects_head: {gesture.affects_head()}")
    print(f"duration_s: {gesture.duration_s():.2f}")
    if gesture.schema_version == 1:
        for i, s in enumerate(gesture.steps):
            print(f"  step {i}: {s}")
    else:
        for kf in gesture.keyframes:
            print(f"  t={kf['time_from_start_s']:.2f}s: {kf['joints']}")
    return 0


def cmd_dry_run(args):
    """Fuehrt die Geste durch die volle Compiler-/Transport-Pipeline, aber
    NIEMALS gegen echte Hardware -- DryRunMotionTransport loggt nur."""
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1

    if gesture.schema_version == 1:
        # v1 bleibt sequenziell -- GestureCatalog.play(dry_run=True) rührt
        # pepper_client nie an (siehe gesture_catalog.py-Tests), daher
        # gefahrlos mit pepper_client=None aufrufbar.
        result = catalog.play(None, args.name, dry_run=True, speed_scale=args.speed_scale)
        for step in result.plan:
            print(step)
        return 0

    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    plan = KinematicCompiler().compile(gesture, speed_scale=args.speed_scale or gesture.speed_scale_default)
    transport = DryRunMotionTransport()
    transport.prepare(plan)
    transport.start()
    transport.restore()
    print(f"Status: {transport.poll()}")
    return 0


def cmd_preview(args):
    """Spielt die Geste in RViz ab, ueber das bestehende URDF-/RViz-System
    (KEIN neues Simulationssystem) -- braucht zwei separat gestartete
    Prozesse:
      1) ros2 launch pepper_description display_scripted.launch.py
      2) gesturectl preview <name>  (dieser Befehl)
    Nutzt sim_qicli.py::SimQicli. Fuer v2-Gesten NUR eine sequenzielle
    Annaeherung (SimQicli kennt kein play_trajectory()) -- ausdruecklich
    NICHT repraesentativ fuer das echte synchrone Timing auf Pepper,
    ausschliesslich zur visuellen Kontrolle der Winkelwerte gedacht."""
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1

    robot_model_dir = _find_robot_model_path()
    if robot_model_dir not in sys.path:
        sys.path.insert(0, robot_model_dir)
    try:
        from sim_qicli import SimQicli
    except ImportError:
        print(
            "sim_qicli.py nicht gefunden (PEPPER_ROBOT_MODEL_PATH pruefen). "
            "Vorschau braucht: 'ros2 launch pepper_description display_scripted.launch.py' "
            "in einem zweiten Terminal, danach diesen Befehl erneut.",
            file=sys.stderr,
        )
        return 1

    print("Hinweis: 'ros2 launch pepper_description display_scripted.launch.py' "
          "muss in einem zweiten Terminal bereits laufen, sonst bewegt sich nichts sichtbar.")
    sim = SimQicli(log_path=f"/tmp/gesturectl_preview_{gesture.name}.json")
    try:
        speed = args.speed_scale or gesture.speed_scale_default
        if gesture.schema_version == 1:
            snapshot = sim.snapshot_joints(gesture.affected_joints()) if gesture.restore_after else None
            for step in gesture.steps:
                sim.set_angle(step["joint"], step["angle"], step["duration"] / speed)
            if snapshot is not None:
                sim.restore_joints(snapshot)
        else:
            plan = KinematicCompiler().compile(gesture, speed_scale=speed, start_pose=sim.get_angles(gesture.affected_joints()))
            snapshot = sim.snapshot_joints(plan.joint_names) if gesture.restore_after else None
            # Sequenzielle Annaeherung (siehe Docstring): jeden Zeitschritt
            # der Reihe nach anfahren, NICHT synchron wie auf echtem Pepper.
            for i, t in enumerate(plan.time_lists[0]):
                dt = t - (plan.time_lists[0][i - 1] if i > 0 else 0.0)
                for j, joint in enumerate(plan.joint_names):
                    sim.set_angle(joint, plan.angle_lists[j][i], max(dt, 0.1), steps=5)
            if snapshot is not None:
                sim.restore_joints(snapshot)
        print(f"Vorschau '{gesture.name}' fertig. Log: /tmp/gesturectl_preview_{gesture.name}.json")
    finally:
        sim.close()
    return 0


def cmd_preview_trajectory(args):
    """Entwicklungsauftrag 04-B, AP8.5/AP8.7: SYNCHRONISIERTE Vorschau aus
    dem tatsaechlichen TrajectoryPlan -- im Unterschied zu 'preview'
    (sequenzielle Annaeherung, siehe dortiger Docstring) bewegen sich hier
    ALLE betroffenen Gelenke GLEICHZEITIG entlang derselben Zeitachse
    (SimQicli.play_synchronized_trajectory(), siehe robot_model/
    sim_qicli.py). Druckt VOR der Wiedergabe den vollen
    TrajectorySafetyReport (Gelenk-/Timing-Ergebnis, Kollisions-Backend-
    Status, Hinweisflaggen). WICHTIG: bleibt eine reine /joint_states-
    Visualisierung -- beweist WEDER Kollisionsfreiheit NOCH ein reales
    Timing auf der Hardware (qicli/ALMotion koennen abweichen). Ersetzt
    KEINEN beaufsichtigten Hardwaretest (docs/GESTURE_HARDWARE_ACCEPTANCE.md)."""
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    if gesture.schema_version != 2:
        print("preview-trajectory ist nur fuer schema_version 2 sinnvoll (v1 hat keinen "
              "gemeinsamen TrajectoryPlan) -- 'preview' fuer v1 verwenden.", file=sys.stderr)
        return 1

    robot_model_dir = _find_robot_model_path()
    if robot_model_dir not in sys.path:
        sys.path.insert(0, robot_model_dir)
    try:
        from sim_qicli import SimQicli
    except ImportError:
        print(
            "sim_qicli.py nicht gefunden (PEPPER_ROBOT_MODEL_PATH pruefen). "
            "Vorschau braucht: 'ros2 launch pepper_description display_scripted.launch.py' "
            "in einem zweiten Terminal, danach diesen Befehl erneut.",
            file=sys.stderr,
        )
        return 1

    print("Hinweis: 'ros2 launch pepper_description display_scripted.launch.py' "
          "muss in einem zweiten Terminal bereits laufen, sonst bewegt sich nichts sichtbar.")
    sim = SimQicli(log_path=f"/tmp/gesturectl_preview_trajectory_{gesture.name}.json")
    try:
        speed = args.speed_scale or gesture.speed_scale_default
        start_pose = sim.get_angles(gesture.affected_joints())
        try:
            plan = KinematicCompiler().compile(gesture, speed_scale=speed, start_pose=start_pose)
        except KinematicCompileError as e:
            print(f"KINEMATIK-COMPILER-FEHLER: {e}", file=sys.stderr)
            return 1

        report = TrajectorySafetyValidator().validate(gesture, start_pose=start_pose, plan=plan)
        print(f"=== TrajectorySafetyReport '{gesture.name}' (compiler_version={report.compiler_version}) ===")
        print(f"verdict: {report.verdict}")
        print(f"affected_joints: {report.affected_joints}")
        print(f"effective_duration_s: {report.effective_duration_s:.2f}" if report.effective_duration_s else "effective_duration_s: n/a")
        print(f"collision_checked: {report.collision_checked} ({report.collision_backend_note})")
        for msg in report.requires_manual_review:
            print(f"  MANUELLE PRUEFUNG NOETIG: {msg}")
        for msg in report.joint_timing_errors:
            print(f"  FEHLER: {msg}", file=sys.stderr)
        if report.verdict == "fail":
            print("Abbruch: TrajectorySafetyReport meldet 'fail' -- keine Vorschau abgespielt.", file=sys.stderr)
            return 1

        snapshot = sim.snapshot_joints(plan.joint_names) if gesture.restore_after else None
        sim.play_synchronized_trajectory(plan.joint_names, plan.angle_lists, plan.time_lists)
        if snapshot is not None:
            sim.restore_joints(snapshot)
        print(
            f"Synchronisierte Vorschau '{gesture.name}' fertig (verdict={report.verdict}, "
            "KEIN Kollisionsnachweis, KEIN Hardwaretest). "
            f"Log: /tmp/gesturectl_preview_trajectory_{gesture.name}.json"
        )
    finally:
        sim.close()
    return 0


def cmd_capture_pose(args):
    """REINER Lesezugriff -- ruft NIE set_breathing/set_angle/
    play_trajectory/restore_joints/set_stiffness/stop_motion auf, loest
    also NIE eine Bewegung oder Steifigkeitsaenderung aus. Nutzt seit
    Entwicklungsauftrag 04-B, AP8.7 (Commit 12/14, Abschnitt 14)
    dieselbe gehaertete Gelenkvalidierung und dieselbe read-only
    PepperJointStateSource-Abstraktion wie 'capture-sequence' -- EIN
    Pruefpfad statt zweier."""
    from .joint_limits import ALLOWED_GESTURE_JOINTS
    from .joint_state_source import PepperJointStateSource
    from .pepper_client import ThreadSafePepperClient

    if args.joints:
        try:
            joints = parse_and_validate_joint_list(args.joints)
        except GestureCaptureError as e:
            print(f"FEHLER: {e}", file=sys.stderr)
            return 1
    else:
        joints = sorted(ALLOWED_GESTURE_JOINTS)

    client = ThreadSafePepperClient()
    if not client.is_reachable():
        print("Pepper nicht erreichbar (Port 22 antwortet nicht).", file=sys.stderr)
        return 1

    source = PepperJointStateSource(client.get_angle)
    reading = source.read(joints)

    invalid = []
    for joint in joints:
        value = reading.values.get(joint)
        print(f"{joint}: {value}")
        if value is None:
            invalid.append(joint)
    if reading.acquisition_mode == "sequential_per_joint":
        # Entwicklungsauftrag 04-B, AP8.7, Abschnitt 4.3: eine
        # sequenzielle Mehrgelenkmessung darf NIE als zeitgleich
        # dargestellt werden.
        print(
            f"# Hinweis: sequenziell gelesen (kein Batch, {reading.acquisition_span_s:.3f}s "
            "Messspanne) -- KEINE zeitgleiche Momentaufnahme.",
            file=sys.stderr,
        )
    if invalid:
        print(f"FEHLER: unvollstaendiger Snapshot -- Gelenke ohne Wert: {invalid}", file=sys.stderr)
        return 1
    return 0


def cmd_capture_sequence(args):
    """Entwicklungsauftrag 04-B, AP8.7, Commit 12/14: rein lesende
    Mehrpunkt-Aufnahme -- niemals Bewegung, niemals Steifigkeitsaenderung,
    keine ROS-Action, kein Aktuator-Lease, keine automatische Ausfuehrung.
    ALLE Argumente werden geprueft, BEVOR ueberhaupt ein Pepper-Client
    erzeugt wird -- ein ungueltiger Aufruf oeffnet keine Verbindung und
    hinterlaesst keine temporaere Datei."""
    try:
        joints = parse_and_validate_joint_list(args.joints)
    except GestureCaptureError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1

    if not _is_finite_cli(args.duration_s) or args.duration_s <= 0:
        print(f"FEHLER: --duration-s muss endlich und positiv sein (erhalten: {args.duration_s!r}).", file=sys.stderr)
        return 1
    if not _is_finite_cli(args.sample_rate_hz) or args.sample_rate_hz <= 0:
        print(f"FEHLER: --sample-rate-hz muss endlich und positiv sein (erhalten: {args.sample_rate_hz!r}).", file=sys.stderr)
        return 1
    from .gesture_capture import MAX_CAPTURE_SAMPLE_COUNT
    if args.duration_s * args.sample_rate_hz > MAX_CAPTURE_SAMPLE_COUNT:
        print(
            f"FEHLER: duration-s * sample-rate-hz ({args.duration_s * args.sample_rate_hz:.1f}) "
            f"ueberschreitet die Obergrenze von {MAX_CAPTURE_SAMPLE_COUNT} Samples.",
            file=sys.stderr,
        )
        return 1
    if not args.output.endswith(".yaml"):
        print("FEHLER: --output muss auf '.yaml' enden.", file=sys.stderr)
        return 1
    if os.path.exists(args.output):
        print(f"FEHLER: Zieldatei '{args.output}' existiert bereits -- wird NICHT ueberschrieben.", file=sys.stderr)
        return 1
    output_dir = os.path.dirname(os.path.abspath(args.output)) or "."
    if os.path.realpath(output_dir) == os.path.realpath(_default_gesture_dir()):
        print(
            "FEHLER: --output darf nicht im aktiven Produktionskatalog liegen "
            f"({_default_gesture_dir()}).",
            file=sys.stderr,
        )
        return 1
    try:
        name = args.name if args.name else derive_name_from_output_path(args.output)
        validate_safe_gesture_name(name)
    except GestureCaptureError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1

    from .joint_state_source import PepperJointStateSource
    from .pepper_client import ThreadSafePepperClient

    client = ThreadSafePepperClient()
    if not client.is_reachable():
        print("Pepper nicht erreichbar (Port 22 antwortet nicht) -- keine Aufnahme, keine Datei.", file=sys.stderr)
        return 1
    source = PepperJointStateSource(client.get_angle)

    try:
        result = capture_sequence(source, joints, args.duration_s, args.sample_rate_hz)
    except GestureCaptureError as e:
        print(f"FEHLER waehrend der Aufnahme: {e} -- keine Datei geschrieben.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Aufnahme abgebrochen (Ctrl+C) -- keine Datei geschrieben.", file=sys.stderr)
        return 1

    data = build_candidate_gesture_data(name, result)

    # Erst nach vollstaendiger Aufnahme UND erfolgreichem Testladen/
    # Testkompilieren schreiben (Abschnitt 7.4).
    try:
        gesture = Gesture(dict(data), f"{name}.yaml")
        KinematicCompiler().compile(
            gesture, speed_scale=gesture.speed_scale_default, start_pose=result.start_pose)
    except (GestureValidationError, KinematicCompileError) as e:
        print(f"FEHLER: erfasste Kandidatin besteht das Testladen nicht: {e} -- keine Datei geschrieben.", file=sys.stderr)
        return 1

    import yaml
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    try:
        atomic_create_exclusive(args.output, content)
    except GestureCaptureError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1

    print(
        f"Kandidatin geschrieben: {args.output} (name={name}, tested_status=draft, "
        f"selectable_by_llm=false, sample_count={result.sample_count}, "
        f"acquisition_mode={result.acquisition_mode})."
    )
    print(
        "Hinweis: KEINE Statusaenderung, KEINE automatische Aufnahme in den Produktionskatalog/"
        "Gesture-Memory-Index. Vor Nutzung: 'gesturectl verify-offline' bzw. 'gesturectl dry-run'."
    )
    return 0


def _is_finite_cli(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def cmd_verify_offline(args):
    """Entwicklungsauftrag 04-B, AP8.7, Commit 12/14: vollstaendig
    OFFLINE reproduzierbarer Evidenzreport fuer GENAU eine Geste. Kein
    Pepper-Client, kein Netzwerk, kein SSH/qicli, keine ROS-Action,
    schreibt NUR den ausdruecklich angeforderten JSON-Report -- niemals
    tested_status/tested_date/test_note/die YAML-Datei/den Gesture-
    Memory-Index."""
    catalog, errors = _load_catalog(args.gesture_dir)
    for e in errors:
        print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1

    explicit_start_pose = None
    if args.start_pose:
        import yaml
        try:
            with open(args.start_pose) as f:
                explicit_start_pose = yaml.safe_load(f)
        except OSError as e:
            print(f"FEHLER: --start-pose konnte nicht gelesen werden: {e}", file=sys.stderr)
            return 1
        if not isinstance(explicit_start_pose, dict):
            print("FEHLER: --start-pose muss ein Gelenk->Winkel-Mapping (YAML/JSON-Dict) sein.", file=sys.stderr)
            return 1

    captured_start_pose = None
    if explicit_start_pose is None:
        captured_start_pose = (gesture.metadata or {}).get("capture", {}).get("start_pose")
        if captured_start_pose is not None and not isinstance(captured_start_pose, dict):
            captured_start_pose = None  # unerwartetes Format -- fail-closed auf NEUTRAL_STAND_POSE zurueckfallen.

    report = verify_gesture_offline(
        gesture, gesture.source_path, speed_scale=args.speed_scale,
        explicit_start_pose=explicit_start_pose, captured_start_pose=captured_start_pose,
    )

    print(f"Geste '{gesture.name}': overall_verdict={report['overall_verdict']}")
    if report["errors"]:
        print(f"  Fehler: {report['errors']}", file=sys.stderr)
    if report["warnings"]:
        print(f"  Warnungen: {report['warnings']}")
    if report["requires_manual_review"]:
        print(f"  Manuelle Pruefung noetig: {report['requires_manual_review']}")

    try:
        write_report_atomically(args.report, report)
    except ValueError as e:
        print(f"FEHLER: Report konnte nicht geschrieben werden: {e}", file=sys.stderr)
        return 1
    print(f"Report geschrieben: {args.report}")

    return verdict_to_exitcode(report["overall_verdict"])


def cmd_validate_all(args):
    """Entwicklungsauftrag 04-B, AP8.7, Commit 12/14: prueft JEDE Geste
    im Katalog mit demselben Offline-Kern wie 'verify-offline'.
    Vollstaendig offline, kein Pepper-Client, kein Netzwerk, keine
    Dateischreiboperation (ausser einer ausdruecklich mit --report
    angeforderten Zusammenfassung)."""
    catalog, errors = _load_catalog(args.gesture_dir)
    for e in errors:
        print(f"FEHLER beim Laden: {e}", file=sys.stderr)

    rows = []
    reports_by_name = {}
    for name in catalog.names():  # bereits alphabetisch sortiert (GestureCatalog.names())
        gesture = catalog.get(name)
        captured_start_pose = (gesture.metadata or {}).get("capture", {}).get("start_pose")
        if captured_start_pose is not None and not isinstance(captured_start_pose, dict):
            captured_start_pose = None
        report = verify_gesture_offline(
            gesture, gesture.source_path, captured_start_pose=captured_start_pose)
        reports_by_name[name] = report
        rows.append((
            name, f"v{report['gesture']['schema_version']}", report["overall_verdict"],
            report["inputs"]["start_pose_source"], report["inputs"]["effective_speed_scale"],
            report["trajectory"]["effective_duration_s"], report["checks"]["joint_and_timing"],
            report["checks"]["collision_backend"], len(report["warnings"]),
        ))

    header = (
        f"{'Name':24s} {'Schema':7s} {'Status':13s} {'Startposequelle':20s} "
        f"{'SpeedScale':10s} {'Dauer':8s} {'Joint/Timing':13s} {'Kollision':18s} {'Warn':4s}"
    )
    print(header)
    for name, schema, verdict, sp_source, speed_scale, duration, jt, coll, warn_count in rows:
        print(
            f"{name:24s} {schema:7s} {verdict:13s} {sp_source:20s} "
            f"{str(speed_scale):10s} {str(duration):8s} {jt:13s} {coll:18s} {warn_count:4d}"
        )

    fail_count = sum(1 for r in rows if r[2] == "fail")
    inconclusive_count = sum(1 for r in rows if r[2] == "inconclusive")
    pass_count = sum(1 for r in rows if r[2] == "pass")
    print(
        f"\nZusammenfassung: {len(rows)} geprueft, {pass_count} pass, "
        f"{inconclusive_count} inconclusive, {fail_count} fail "
        f"({len(errors)} Ladefehler uebersprungen)."
    )

    if getattr(args, "report", None):
        summary = {
            "report_schema_version": 1,
            "load_errors": list(errors),
            "results": {name: reports_by_name[name] for name in sorted(reports_by_name)},
        }
        try:
            write_report_atomically(args.report, summary)
        except ValueError as e:
            print(f"FEHLER: Zusammenfassungsreport konnte nicht geschrieben werden: {e}", file=sys.stderr)
            return 1
        print(f"Zusammenfassungsreport geschrieben: {args.report}")

    if errors or fail_count > 0:
        return 1
    if inconclusive_count > 0:
        return 2
    return 0


def cmd_compare(args):
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture_a = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1

    def _final_pose(g):
        if g.schema_version == 1:
            pose = {}
            for s in g.steps:
                pose[s["joint"]] = s["angle"]
            return pose
        pose = {}
        for kf in g.keyframes:
            pose.update(kf["joints"])
        return pose

    if args.other:
        try:
            gesture_b = catalog.get(args.other)
        except KeyError as e:
            print(str(e), file=sys.stderr)
            return 1
        pose_a, pose_b, label_b = _final_pose(gesture_a), _final_pose(gesture_b), args.other
    else:
        from .pepper_client import ThreadSafePepperClient
        client = ThreadSafePepperClient()
        if not client.is_reachable():
            print("Pepper nicht erreichbar -- fuer 'compare' ohne zweite Geste wird ein "
                  "Live-Snapshot gebraucht (Port 22 antwortet nicht).", file=sys.stderr)
            return 1
        pose_a = _final_pose(gesture_a)
        pose_b, label_b = client.snapshot_joints(list(pose_a.keys())), "live-snapshot"

    all_joints = sorted(set(pose_a) | set(pose_b))
    for joint in all_joints:
        a, b = pose_a.get(joint), pose_b.get(joint)
        marker = "  " if a == b else "<>"
        print(f"{marker} {joint:16s} {args.name}={a!r:>10}  {label_b}={b!r:>10}")
    return 0


LIVE_TEST_QUESTIONS = [
    "Ist der Armraum um Pepper vollstaendig frei (keine Person/Gegenstaende in Reichweite)?",
    "Ist ein Bediener direkt am Not-Aus/Not-Stopp positioniert?",
    "Ist Pepper an der Ladestation/gesichert aufgestellt (nicht auf einer Rampe/Kante)?",
    "Wurde die Geste bereits per 'gesturectl dry-run' erfolgreich geprueft?",
]


def cmd_live_test(args):
    """Gate fuer einen beaufsichtigten Live-Test -- siehe
    docs/GESTURE_LIVE_TEST_CHECKLIST.md. Schreibt NIE selbst
    tested_status: live_validated in eine YAML (Auftrag-Vorgabe) --
    das bleibt ein manueller, bewusster Schritt nach dem Test.

    Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.11 (bestaetigter Fund
    2.9/'kein hardwarefaehiger CLI-Bypass'): dieser Befehl rief bisher
    KinematicCompiler -> QicliTrajectoryTransport -> Pepper-Client
    DIREKT auf -- vollstaendig AN Policy/Validator/Lease/Watchdog/Cancel/
    Quarantaene VORBEI. Nach der manuellen Checkliste wird jetzt
    stattdessen die ECHTE PlayGesture-Action der bereits laufenden Bridge
    (im Profil 'supervised_hardware_test') angesprochen -- derselbe
    Codepfad wie im Normalbetrieb, mit allen dort geltenden Sicherungen.
    Reine Lese-/Simulationsbefehle (capture-pose/preview/
    preview-trajectory/dry-run) bleiben bewusst direkt (Auftrag,
    Abschnitt 3.11 letzter Satz)."""
    catalog, errors = _load_catalog(args.gesture_dir)
    if errors:
        for e in errors:
            print(f"FEHLER beim Laden: {e}", file=sys.stderr)
    try:
        gesture = catalog.get(args.name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    if gesture.schema_version != 2:
        print("live-test ist aktuell nur fuer schema_version 2 vorgesehen "
              "(v1 lief bereits in frueheren Auftraegen live).", file=sys.stderr)
        return 1

    from .pepper_client import ThreadSafePepperClient
    probe_client = ThreadSafePepperClient()
    if not probe_client.is_reachable():
        print("Pepper nicht erreichbar (Port 22 antwortet nicht) -- live-test abgebrochen, "
              "bleibt bei tested_status aus der YAML.", file=sys.stderr)
        return 1

    print(f"=== Live-Test-Checkliste fuer '{gesture.name}' (siehe "
          "docs/GESTURE_LIVE_TEST_CHECKLIST.md) ===")
    for q in LIVE_TEST_QUESTIONS:
        answer = input(f"{q} [ja/NEIN] ").strip().lower()
        if answer != "ja":
            print("Nicht bestaetigt -- Abbruch, keine Bewegung ausgeloest.")
            return 1

    speed = 0.4 if not args.full_speed else min(args.speed_scale or gesture.speed_scale_default, 1.5)
    action_name = f"/{args.bridge_namespace}/play_gesture" if args.bridge_namespace else "/play_gesture"
    print(f"Sende PlayGesture-Ziel '{gesture.name}' mit speed_scale={speed} an "
          f"'{action_name}' (erster Aufruf: immer <= 0.4, siehe Checkliste). Voraussetzung: "
          "die Bridge laeuft bereits mit '-p execution_profile:=supervised_hardware_test "
          "-p dry_run:=false' -- Policy/Validator/Lease/Watchdog/Cancel/Quarantaene der "
          "Bridge gelten dabei genauso wie im Normalbetrieb.")

    import rclpy
    from rclpy.action import ActionClient
    from ihk_pepper_interfaces.action import PlayGesture as PlayGestureAction

    rclpy.init(args=None)
    client_node = rclpy.create_node("gesturectl_live_test_client")
    try:
        action_client = ActionClient(client_node, PlayGestureAction, action_name)
        if not action_client.wait_for_server(timeout_sec=10.0):
            print(
                f"FEHLER: PlayGesture-Action '{action_name}' nicht erreichbar -- laeuft die "
                "Bridge im Profil 'supervised_hardware_test'? Keine Bewegung ausgeloest.",
                file=sys.stderr,
            )
            return 1
        goal = PlayGestureAction.Goal()
        goal.gesture_name = gesture.name
        goal.speed_scale = float(speed)
        send_future = action_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(client_node, send_future, timeout_sec=10.0)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            print(
                "FEHLER: Ziel von der Bridge NICHT angenommen (Policy-/Lease-Ablehnung?) -- "
                "keine Bewegung ausgeloest.", file=sys.stderr,
            )
            return 1
        result_future = goal_handle.get_result_async()
        # Bewusst KEIN zusaetzliches CLI-seitiges Timeout hier -- die
        # Bridge selbst erzwingt den echten Bewegungsdeckel
        # (gesture.max_duration_s) UND die separate Vorbereitungszeit-
        # grenze (GESTURE_PREPARATION_TIMEOUT_S); ein zweites,
        # unabhaengiges CLI-Timeout wuerde diese Deckel nur verdoppeln,
        # ohne selbst irgendeine Hardwareaktion beeinflussen zu koennen.
        rclpy.spin_until_future_complete(client_node, result_future)
        action_result = result_future.result()
        if action_result is None:
            print("FEHLER: keine Ergebnis-Antwort von der Bridge erhalten.", file=sys.stderr)
            return 1
        result = action_result.result
        print(f"Ergebnis: success={result.success} error_message={result.error_message!r}")
        if not result.success:
            print(f"FEHLER: {result.error_message}", file=sys.stderr)
            return 1
    finally:
        client_node.destroy_node()
        rclpy.shutdown()

    print(
        "Test durchgefuehrt. gesturectl setzt tested_status NICHT automatisch -- "
        f"bei erfolgreichem, beaufsichtigtem Test 'tested_status: live_validated' und "
        "'tested_date'/'test_note' manuell in "
        f"config/gestures/{gesture.name}.yaml eintragen."
    )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="gesturectl", description=__doc__)
    parser.add_argument("--gesture-dir", default=_default_gesture_dir())
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="alle Kataloggesten auflisten")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser(
        "audit",
        help="deterministische Katalogpruefung (Metadaten/Spiegelpaare/Systemgesten), rein lesend",
    )
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("validate", help="eine Geste laden+kompilieren, ohne sie abzuspielen")
    p.add_argument("name")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("show", help="Metadaten/Keyframes einer Geste anzeigen")
    p.add_argument("name")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("dry-run", help="volle Pipeline, ohne jede Hardwareaktion")
    p.add_argument("name")
    p.add_argument("--speed-scale", type=float, default=None)
    p.set_defaults(func=cmd_dry_run)

    p = sub.add_parser("preview", help="in RViz abspielen (braucht display_scripted.launch.py)")
    p.add_argument("name")
    p.add_argument("--speed-scale", type=float, default=None)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser(
        "preview-trajectory",
        help="synchronisierte RViz-Vorschau aus dem echten TrajectoryPlan + TrajectorySafetyReport",
    )
    p.add_argument("name")
    p.add_argument("--speed-scale", type=float, default=None)
    p.set_defaults(func=cmd_preview_trajectory)

    p = sub.add_parser("capture-pose", help="aktuelle Gelenkwinkel lesen (REIN lesend)")
    p.add_argument("--joints", default=None, help="kommagetrennt, sonst alle freigegebenen Gelenke")
    p.set_defaults(func=cmd_capture_pose)

    p = sub.add_parser(
        "capture-sequence",
        help="rein lesende Mehrpunkt-Aufnahme -> sichere v2-Kandidatendatei (KEINE Bewegung)",
    )
    p.add_argument("--joints", required=True, help="kommagetrennt, z.B. HeadYaw,HeadPitch")
    p.add_argument("--duration-s", type=float, required=True)
    p.add_argument("--sample-rate-hz", type=float, required=True)
    p.add_argument("--output", required=True, help="Zieldatei, muss auf .yaml enden, darf noch nicht existieren")
    p.add_argument("--name", default=None, help="sonst deterministisch aus --output abgeleitet")
    p.set_defaults(func=cmd_capture_sequence)

    p = sub.add_parser(
        "verify-offline",
        help="vollstaendig offline reproduzierbarer Evidenzreport fuer EINE Geste (JSON)",
    )
    p.add_argument("name")
    p.add_argument("--report", required=True, help="Zieldatei fuer den JSON-Report (wird nicht ueberschrieben)")
    p.add_argument("--speed-scale", type=float, default=None)
    p.add_argument("--start-pose", default=None, help="YAML/JSON-Datei mit einem Gelenk->Winkel-Mapping")
    p.set_defaults(func=cmd_verify_offline)

    p = sub.add_parser(
        "validate-all",
        help="prueft JEDE Kataloggeste offline (derselbe Kern wie verify-offline)",
    )
    p.add_argument("--report", default=None, help="optionaler JSON-Zusammenfassungsreport (wird nicht ueberschrieben)")
    p.set_defaults(func=cmd_validate_all)

    p = sub.add_parser("compare", help="Endpose einer Geste vs. andere Geste ODER Live-Snapshot")
    p.add_argument("name")
    p.add_argument("other", nargs="?", default=None)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("live-test", help="beaufsichtigter Live-Test (Checkliste, siehe Doku)")
    p.add_argument("name")
    p.add_argument("--full-speed", action="store_true", help="zweiter Durchgang nach dem 0.4-Test")
    p.add_argument("--speed-scale", type=float, default=None)
    p.add_argument(
        "--bridge-namespace", default="pepper_bridge",
        help="Namespace der laufenden Bridge (Entwicklungsauftrag 04-B, AP8-R2, "
        "Abschnitt 3.11 -- live-test spricht die echte PlayGesture-Action an, "
        "leer lassen fuer eine Bridge ohne Namespace)",
    )
    p.set_defaults(func=cmd_live_test)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except GestureValidationError as e:
        print(f"Validierungsfehler: {e}", file=sys.stderr)
        return 1
    except KinematicCompileError as e:
        print(f"Kinematik-Compiler-Fehler: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
