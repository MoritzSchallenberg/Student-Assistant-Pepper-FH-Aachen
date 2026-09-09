"""
Einheitliches Bewegungs-/Gesten-Katalogformat. Zwei Schema-Versionen,
beide gleichzeitig ladbar:

schema_version 1 (Feld fehlt = 1, Rueckwaertskompatibilitaet) --
sequenzielle Einzelgelenk-Schritte, unveraendert:
    name: <eindeutig, muss Dateiname ohne .yaml entsprechen>
    steps:
      - {joint: RShoulderPitch, angle: -1.0, duration: 1.0}
      - ...

schema_version 2 (Entwicklungsauftrag 1, Abschnitt 7) -- zeitbasierte,
SYNCHRONE Ganzkoerper-Keyframes:
    schema_version: 2
    name: <eindeutig>
    requires_stationary: true
    allowed_interaction_states: [IDLE, ATTRACT, CONVERSATION_READY]
    speed_scale_default: 0.6
    tested_status: dry_run_validated
    keyframes:
      - time_from_start_s: 0.0
        joints: {LShoulderPitch: 1.4, RShoulderPitch: 1.4}
      - time_from_start_s: 1.5
        joints: {LShoulderPitch: 0.3, RShoulderPitch: 0.3}

v1 bleibt bewusst sequenziell (kein automatisches "zwei Steps = ein
Keyframe-Paar"-Mapping) -- das wuerde die bereits live getestete Timing-
Semantik der bestehenden Gesten veraendern, ohne dass hier ein echter
synchroner Gewinn entstuende. v2-Gesten nutzen stattdessen einen echten
synchronen Transport ueber EINEN ALMotion.angleInterpolation-Aufruf mit
mehreren Gelenken, siehe pepper_client.play_trajectory() und
docs/GESTURE_AUTHORING.md.

Bewusst NICHT Teil dieses Auftrags: automatisches Trainieren neuer
Bewegungen. Nur das Format + der Player werden hier bereitgestellt.
"""
import glob
import os
from dataclasses import dataclass, field

import yaml

from .joint_limits import ALLOWED_GESTURE_JOINTS, JointLimitError, validate_angle, validate_angle_with_margin
from .kinematic_compiler import KinematicCompiler
from .motion_transport import QicliTrajectoryTransport, TransportStatus

MIN_SPEED_SCALE_V1 = 0.1
MAX_SPEED_SCALE_V1 = 3.0
# Konservativer als v1 (Auftrag: "kein 3-faches Livetempo mehr").
MIN_SPEED_SCALE_V2 = 0.3
MAX_SPEED_SCALE_V2 = 1.5

# Geschwindigkeitsgrenze zwischen zwei Keyframes desselben Gelenks.
# 3.0 rad/s statt einer runden, aus der Luft gegriffenen Zahl: die
# bereits live getestete wave_*-Oszillation (RElbowYaw 0.6<->1.6 in 0.4s,
# siehe docs/STATUS.md/docs/CAPABILITIES.md) braucht exakt 2.5 rad/s --
# die Grenze liegt knapp darueber, damit dieser bewiesene Fall nicht
# faelschlich abgelehnt wird, aber erkennbar schnellere Bewegungen ohne
# jede Live-Referenz weiterhin blockiert werden. Beschleunigung wird
# NICHT geprueft -- keine gemessene Referenz vorhanden (siehe
# docs/GESTURE_AUTHORING.md).
MAX_JOINT_VELOCITY_RAD_S = 3.0

VALID_TESTED_STATUS = ("draft", "dry_run_validated", "live_validated")
_HEAD_JOINTS = frozenset({"HeadYaw", "HeadPitch"})


class GestureValidationError(ValueError):
    pass


@dataclass
class PlaybackResult:
    """Rueckgabe von GestureCatalog.play() -- bei dry_run=True enthaelt
    plan die vollstaendig aufgeloeste (Speed-skalierte) Trajektorie, OHNE
    dass irgendeine Hardwareaktion stattgefunden hat."""

    dry_run: bool
    schema_version: int
    plan: list = field(default_factory=list)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _trajectory_plan_to_legacy_dicts(plan) -> list:
    """Wandelt einen motion_transport.TrajectoryPlan zurueck in das
    bisherige PlaybackResult.plan-Format (Liste von {time_from_start_s,
    joints}) -- haelt die oeffentliche PlaybackResult-Schnittstelle stabil,
    obwohl _play_v2 seit AP12 intern ueber den KinematicCompiler laeuft."""
    if not plan.time_lists or not plan.time_lists[0]:
        return []
    result = []
    for i, t in enumerate(plan.time_lists[0]):
        result.append({
            "time_from_start_s": t,
            "joints": {joint: plan.angle_lists[j][i] for j, joint in enumerate(plan.joint_names)},
        })
    return result


class Gesture:
    """Repraesentiert genau EINE Gestendatei, v1 (steps) ODER v2 (keyframes)."""

    def __init__(self, data: dict, source_path: str):
        self.name = data["name"]
        self.description = data.get("description", "")
        self.metadata = data.get("metadata", {})
        self.disable_breathing = data.get("disable_breathing", [])
        self.restore_after = data.get("restore_after", True)
        self.source_path = source_path
        self.schema_version = int(data.get("schema_version", 1))

        # Metadaten, die der Auftrag fuer jede Geste verlangt (Abschnitt 7).
        self.allowed_interaction_states = list(data.get("allowed_interaction_states", []))  # leer = ueberall
        self.requires_stationary = bool(data.get("requires_stationary", False))
        self.tested_status = data.get("tested_status", "draft")
        self.tested_date = data.get("tested_date")
        self.test_note = data.get("test_note", "")
        self.max_duration_s = data.get("max_duration_s")
        self.on_cancel = data.get("on_cancel", "hold")  # "hold" | "restore"

        if self.tested_status not in VALID_TESTED_STATUS:
            raise GestureValidationError(
                f"Geste '{self.name}': unbekannter tested_status '{self.tested_status}' "
                f"(erlaubt: {VALID_TESTED_STATUS})"
            )

        if self.schema_version == 1:
            self.steps = data.get("steps", [])
            self.keyframes = None
            self.speed_scale_default = 1.0
            self._validate_v1()
        elif self.schema_version == 2:
            self.steps = None
            self.keyframes = data.get("keyframes", [])
            self.speed_scale_default = float(data.get("speed_scale_default", 1.0))
            self._validate_v2()
        else:
            raise GestureValidationError(
                f"Geste '{self.name}': unbekannte schema_version {self.schema_version} (unterstuetzt: 1, 2)"
            )

    def _validate_v1(self):
        if not self.steps:
            raise GestureValidationError(f"Geste '{self.name}': keine steps definiert")
        for i, step in enumerate(self.steps):
            for key in ("joint", "angle", "duration"):
                if key not in step:
                    raise GestureValidationError(f"Geste '{self.name}', Schritt {i}: Feld '{key}' fehlt")
            if step["duration"] <= 0:
                raise GestureValidationError(f"Geste '{self.name}', Schritt {i}: duration muss > 0 sein")
            try:
                validate_angle(step["joint"], step["angle"], strict=True)
            except JointLimitError as e:
                raise GestureValidationError(f"Geste '{self.name}', Schritt {i}: {e}") from e

    def _validate_v2(self):
        if not self.keyframes:
            raise GestureValidationError(f"Geste '{self.name}': keine keyframes definiert")

        last_t = None
        for i, kf in enumerate(self.keyframes):
            if "time_from_start_s" not in kf or "joints" not in kf:
                raise GestureValidationError(
                    f"Geste '{self.name}', Keyframe {i}: 'time_from_start_s'/'joints' fehlt"
                )
            t = float(kf["time_from_start_s"])
            if t < 0:
                raise GestureValidationError(f"Geste '{self.name}', Keyframe {i}: time_from_start_s < 0")
            if last_t is not None and t <= last_t:
                raise GestureValidationError(
                    f"Geste '{self.name}', Keyframe {i}: time_from_start_s muss streng monoton "
                    f"steigen ({t} <= {last_t})"
                )
            last_t = t

            joints = kf["joints"]
            if not joints:
                raise GestureValidationError(f"Geste '{self.name}', Keyframe {i}: keine joints angegeben")
            for joint, angle in joints.items():
                if joint not in ALLOWED_GESTURE_JOINTS:
                    raise GestureValidationError(
                        f"Geste '{self.name}', Keyframe {i}: Gelenk '{joint}' nicht freigegeben"
                    )
                try:
                    validate_angle_with_margin(joint, float(angle))
                except JointLimitError as e:
                    raise GestureValidationError(f"Geste '{self.name}', Keyframe {i}: {e}") from e

        self._validate_v2_velocity()

    def _validate_v2_velocity(self):
        """Prueft die Geschwindigkeit zwischen aufeinanderfolgenden
        Keyframes pro Gelenk (nur wo das Gelenk in beiden vorkommt)."""
        for i in range(1, len(self.keyframes)):
            prev, curr = self.keyframes[i - 1], self.keyframes[i]
            dt = float(curr["time_from_start_s"]) - float(prev["time_from_start_s"])
            for joint, angle in curr["joints"].items():
                if joint not in prev["joints"]:
                    continue
                d_angle = abs(float(angle) - float(prev["joints"][joint]))
                velocity = d_angle / dt if dt > 0 else float("inf")
                if velocity > MAX_JOINT_VELOCITY_RAD_S:
                    raise GestureValidationError(
                        f"Geste '{self.name}', Keyframe {i}: Gelenk '{joint}' braucht "
                        f"{velocity:.2f} rad/s (> {MAX_JOINT_VELOCITY_RAD_S} rad/s erlaubt)"
                    )

    def affected_joints(self):
        if self.schema_version == 1:
            return sorted({s["joint"] for s in self.steps})
        joints = set()
        for kf in self.keyframes:
            joints.update(kf["joints"].keys())
        return sorted(joints)

    def affects_head(self) -> bool:
        return bool(_HEAD_JOINTS & set(self.affected_joints()))

    def duration_s(self) -> float:
        if self.schema_version == 1:
            return sum(s["duration"] for s in self.steps)
        return float(self.keyframes[-1]["time_from_start_s"])


class GestureCatalog:
    def __init__(self, catalog_dir: str):
        self.catalog_dir = catalog_dir
        self._gestures: dict[str, Gesture] = {}
        self.reload()

    def reload(self):
        """Laedt/validiert alle *.yaml im Katalog-Ordner neu (v1+v2
        gemischt). Fehlerhafte Dateien werden uebersprungen (mit
        Fehlermeldung), nicht das ganze System blockieren."""
        self._gestures = {}
        errors = []
        for path in sorted(glob.glob(os.path.join(self.catalog_dir, "*.yaml"))):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                gesture = Gesture(data, path)
                if gesture.name != os.path.splitext(os.path.basename(path))[0]:
                    errors.append(f"{path}: name '{gesture.name}' passt nicht zum Dateinamen")
                    continue
                self._gestures[gesture.name] = gesture
            except Exception as e:
                errors.append(f"{path}: {e}")
        return errors

    def names(self):
        return sorted(self._gestures.keys())

    def get(self, name: str) -> Gesture:
        if name not in self._gestures:
            raise KeyError(f"Unbekannte Geste: '{name}' (verfuegbar: {self.names()})")
        return self._gestures[name]

    def play(
        self, pepper_client, name: str, speed_scale: float = None, feedback_cb=None,
        dry_run: bool = False, current_interaction_state: str = None,
        nav2_moving: bool = False, mapping_active: bool = False,
        cancel_event=None, interrupt_channel=None,
    ) -> PlaybackResult:
        """Fuehrt eine Geste aus (dry_run=True: loggt/liefert nur die
        aufgeloeste Trajektorie zurueck, OHNE jede Hardwareaktion).

        Sperrt die Ausfuehrung (GestureValidationError), wenn:
        - current_interaction_state gesetzt ist und nicht in
          gesture.allowed_interaction_states steht (leer = ueberall erlaubt)
        - nav2_moving=True und die Geste v2 ist bzw. requires_stationary
          gesetzt hat (Arm-/Kopfgesten waehrend Nav2-Bewegung, Abschnitt 7)
        - mapping_active=True und die Geste Kopfgelenke bewegt (Kopf-
          bewegung waehrend Mapping/Navigation, Abschnitt 3)

        speed_scale=None nutzt gesture.speed_scale_default (v2) bzw. 1.0
        (v1). Live-Wiring von nav2_moving/mapping_active aus echten
        SafetyState-/camera_pose_gate-Topics ist vorbereitet, aber nicht
        Teil dieses Aufrufs -- Aufrufer (z.B. ein spaeterer BT-Knoten)
        muss die aktuellen Werte selbst uebergeben.

        cancel_event (Entwicklungsauftrag 04-B, AP5B, Abschnitt 12):
        optionales threading.Event, das WAEHREND der Ausfuehrung
        (bewusst NICHT nur vor dem Start) beobachtet wird. Fuer v1 wird
        zwischen zwei Einzelschritten geprueft (keine Unterbrechung
        MITTEN in einem set_angle()-Aufruf moeglich). Fuer v2 wird
        zwischen kurzen Poll-Intervallen geprueft und bei Bedarf
        transport.cancel() aufgerufen (siehe motion_transport.py fuer
        die dort dokumentierten Grenzen einer echten Mid-Flight-
        Unterbrechung). interrupt_channel wird unveraendert an
        QicliTrajectoryTransport durchgereicht (unabhaengiger
        Abbruchkanal, siehe pepper_client.py::PepperInterruptChannel).
        Beide Parameter bleiben optional -- ohne sie ist das Verhalten
        unveraendert wie vor diesem Auftrag (blockierender Aufruf bis
        zum natuerlichen Ende)."""
        gesture = self.get(name)

        if gesture.allowed_interaction_states and current_interaction_state is not None:
            if current_interaction_state not in gesture.allowed_interaction_states:
                raise GestureValidationError(
                    f"Geste '{name}' im Zustand '{current_interaction_state}' nicht erlaubt "
                    f"(erlaubt: {gesture.allowed_interaction_states})"
                )
        if nav2_moving and (gesture.requires_stationary or gesture.schema_version == 2):
            raise GestureValidationError(f"Geste '{name}' waehrend Nav2-Bewegung gesperrt")
        if mapping_active and gesture.affects_head():
            raise GestureValidationError(
                f"Geste '{name}' waehrend Mapping/Navigation gesperrt (bewegt Kopfgelenke)"
            )

        if gesture.schema_version == 1:
            scale = _clamp(speed_scale if speed_scale is not None else 1.0, MIN_SPEED_SCALE_V1, MAX_SPEED_SCALE_V1)
            return self._play_v1(pepper_client, gesture, scale, feedback_cb, dry_run, cancel_event)

        scale = _clamp(
            speed_scale if speed_scale is not None else gesture.speed_scale_default,
            MIN_SPEED_SCALE_V2, MAX_SPEED_SCALE_V2,
        )
        return self._play_v2(pepper_client, gesture, scale, feedback_cb, dry_run, cancel_event, interrupt_channel)

    def _play_v1(self, pepper_client, gesture, speed_scale, feedback_cb, dry_run, cancel_event=None):
        planned = [
            {"joint": s["joint"], "angle": s["angle"], "duration": s["duration"] / speed_scale}
            for s in gesture.steps
        ]
        if dry_run:
            return PlaybackResult(dry_run=True, schema_version=1, plan=planned)

        for part in gesture.disable_breathing:
            pepper_client.set_breathing(False, part)
        snapshot = pepper_client.snapshot_joints(gesture.affected_joints()) if gesture.restore_after else None
        try:
            total = len(planned)
            for i, step in enumerate(planned):
                # Zwischen zwei Schritten pruefen (Entwicklungsauftrag
                # 04-B, AP5B) -- KEINE Unterbrechung mitten in einem
                # bereits laufenden set_angle()-Aufruf moeglich.
                if cancel_event is not None and cancel_event.is_set():
                    break
                pepper_client.set_angle(step["joint"], step["angle"], step["duration"])
                if feedback_cb:
                    feedback_cb(f"step_{i}", (i + 1) / total)
        finally:
            if snapshot is not None:
                pepper_client.restore_joints(snapshot)
            for part in gesture.disable_breathing:
                pepper_client.set_breathing(True, part)
        return PlaybackResult(dry_run=False, schema_version=1, plan=planned)

    def _play_v2(self, pepper_client, gesture, speed_scale, feedback_cb, dry_run,
                 cancel_event=None, interrupt_channel=None):
        """Nutzt seit Entwicklungsauftrag 3, AP12 den KinematicCompiler +
        QicliTrajectoryTransport statt Keyframes direkt in
        play_trajectory()-Argumente umzurechnen (siehe kinematic_compiler.py-
        Moduldoku fuer die damit behobenen Schwaechen: fehlende Gelenke pro
        Keyframe, undefinierter Startzustand, inkonsistente Zeitachsen je
        Gelenk, fehlende Beschleunigungspruefung, Gelenk-fuer-Gelenk-
        Wiederherstellung).

        cancel_event/interrupt_channel (Entwicklungsauftrag 04-B, AP5B):
        siehe play()-Docstring. Ohne cancel_event blockiert diese Methode
        weiterhin unveraendert bis zum natuerlichen Ende (transport.wait())."""
        compiler = KinematicCompiler()

        if dry_run:
            plan = compiler.compile(gesture, speed_scale=speed_scale)
            return PlaybackResult(dry_run=True, schema_version=2, plan=_trajectory_plan_to_legacy_dicts(plan))

        for part in gesture.disable_breathing:
            pepper_client.set_breathing(False, part)
        snapshot = pepper_client.snapshot_joints(gesture.affected_joints()) if gesture.restore_after else None
        transport = None
        try:
            plan = compiler.compile(gesture, speed_scale=speed_scale, start_pose=snapshot)
            transport = QicliTrajectoryTransport(pepper_client, interrupt_channel=interrupt_channel)
            transport.prepare(plan, restore_snapshot=snapshot)
            transport.start()
            if cancel_event is None:
                status = transport.wait()
            else:
                status = transport.poll()
                while status == TransportStatus.RUNNING:
                    if cancel_event.is_set():
                        status = transport.cancel().final_transport_state
                        break
                    status = transport.wait(timeout_s=0.1)
            if feedback_cb:
                feedback_cb("trajectory_sent", 1.0)
            if status == TransportStatus.FAILED:
                raise transport.last_error
        finally:
            if snapshot is not None and transport is not None:
                transport.restore()
            for part in gesture.disable_breathing:
                pepper_client.set_breathing(True, part)
        return PlaybackResult(dry_run=False, schema_version=2, plan=_trajectory_plan_to_legacy_dicts(plan))
