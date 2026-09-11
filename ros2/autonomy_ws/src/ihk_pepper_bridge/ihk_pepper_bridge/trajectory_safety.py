"""
trajectory_safety.py -- austauschbare, offline-testbare Sicherheitspruefung
fuer eine Geste (Entwicklungsauftrag 04-B, AP8.5).

Hintergrund (bestaetigte Ausgangsluecke, siehe
docs/DEVELOPMENT_ORDER_04_B_REPORT.md AP8 Commit 1/11, Abschnitt 3.4/3.6
und AP8.5 im Originalauftrag): KinematicCompiler.compile() (siehe
kinematic_compiler.py) prueft bereits harte Gelenk-/Timing-Grenzen
(Winkel, Geschwindigkeit/Beschleunigung nach Skalierung, Start-Uebergang,
NaN/inf, max_duration_s) und liefert bei Erfolg einen TrajectoryPlan.
Dieses Modul baut EINE Ebene darueber: eine austauschbare
TrajectorySafetyValidator/-Backend-Schnittstelle, die (a) das bereits
vorhandene Compiler-Ergebnis in einen einheitlichen, auch fuer
Offline-Evidence-Reports (gesturectl verify-offline, AP8.7/Commit 9)
wiederverwendbaren TrajectorySafetyReport uebersetzt, und (b) fuer die im
Auftrag genannten besonders sorgfaeltig zu behandelnden Bewegungs-
kategorien (Haende nahe Kopf/Gesicht, Huefte/Knie, gleichzeitige
Torso+Arm-Bewegung, grosse bilaterale Armbewegungen) auf manuelle,
beaufsichtigte Pruefung HINWEIST.

Ehrliche Grenze (bewusst NICHT ueberspielt): in dieser Session ist KEINE
echte Vorwaertskinematik-/Kollisionsbibliothek verfuegbar (kein
trimesh/fcl/pinocchio installiert, siehe
docs/DEVELOPMENT_ORDER_04_B_REPORT.md) -- obwohl unter
ros2/robot_model/src/pepper_description/urdf/pepper.urdf ein echtes URDF
existiert, kann daraus in dieser Umgebung KEIN reproduzierbarer
Kollisions-/Abstandsbeweis erzeugt werden. DisabledCollisionBackend macht
deshalb AUSDRUECKLICH KEINE Kollisionsaussage (verdict="inconclusive") --
ein "inconclusive" darf laut Auftrag NIE automatisch zu
dry_run_validated/live_validated hochgestuft werden. JointAndTimingValidator
ist das PFLICHT-Backend; ein optionales echtes URDF-/Kollisions-Backend
kann spaeter ergaenzt werden, sobald es "echt, reproduzierbar" laeuft
(Auftragsvorgabe) -- nicht vorher.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .kinematic_compiler import COMPILER_VERSION, KinematicCompileError, KinematicCompiler

VALID_VERDICTS = ("pass", "fail", "inconclusive")

# Entwicklungsauftrag 04-B, AP8.5: Gelenkgruppen fuer die konservativen
# Hinweisflaggen -- reine Namensmengen, KEINE geometrische Berechnung
# (keine echte Vorwaertskinematik verfuegbar, siehe Moduldoku oben).
HIP_KNEE_JOINTS = frozenset({"HipRoll", "HipPitch", "KneePitch"})
LEFT_ARM_JOINTS = frozenset(
    {"LShoulderPitch", "LShoulderRoll", "LElbowYaw", "LElbowRoll", "LWristYaw", "LHand"})
RIGHT_ARM_JOINTS = frozenset(
    {"RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw", "RHand"})
HEAD_JOINTS = frozenset({"HeadYaw", "HeadPitch"})
ARM_JOINTS = LEFT_ARM_JOINTS | RIGHT_ARM_JOINTS


@dataclass
class TrajectorySafetyReport:
    """Vereinheitlichtes Ergebnis eines oder mehrerer
    TrajectorySafetyBackend-Laeufe. 'inconclusive' ist ein EIGENER,
    dritter Zustand -- niemals gleichbedeutend mit 'pass' (Auftrag AP8.7:
    'inconclusive darf nie automatisch zu dry_run_validated/
    live_validated hochgestuft werden')."""

    gesture_name: str
    verdict: str  # "pass" | "fail" | "inconclusive"
    compiler_version: str = COMPILER_VERSION
    backend_names: list = field(default_factory=list)
    collision_checked: bool = False
    collision_backend_note: str = ""
    joint_timing_errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    requires_manual_review: list = field(default_factory=list)
    affected_joints: list = field(default_factory=list)
    effective_speed_scale: Optional[float] = None
    effective_duration_s: Optional[float] = None

    def __post_init__(self):
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(f"Ungueltiger verdict {self.verdict!r}, erlaubt: {VALID_VERDICTS}")


class TrajectorySafetyBackend:
    """Basisschnittstelle fuer ein austauschbares Sicherheits-Backend.
    check() bekommt IMMER dieselbe (gesture, plan, start_pose,
    compile_error)-Eingabe -- plan ist None UND compile_error gesetzt,
    wenn KinematicCompiler.compile() bereits gescheitert ist (siehe
    TrajectorySafetyValidator.validate())."""

    name = "unnamed_backend"

    def check(self, gesture, plan, start_pose, compile_error):
        raise NotImplementedError


class JointAndTimingValidator(TrajectorySafetyBackend):
    """Pflicht-Backend (AP8.5): der eigentliche Sicherheitsnachweis kommt
    bereits aus KinematicCompiler.compile() (Gelenkgrenzen, Geschwindigkeit/
    Beschleunigung NACH Skalierung, Start-zu-erstem-Keyframe-Uebergang,
    NaN/inf, max_duration_s -- siehe kinematic_compiler.py). Dieses Backend
    uebersetzt dessen Ergebnis in einen TrajectorySafetyReport und ergaenzt
    NUR dokumentierende, NICHT geometrisch berechnete Hinweisflaggen fuer
    die im Auftrag genannten besonders sorgfaeltig zu behandelnden
    Bewegungskategorien. Diese Flaggen sind KEIN Kollisionsbeweis -- sie
    lenken die Aufmerksamkeit der PFLICHTIGEN beaufsichtigten Live-Pruefung
    (docs/GESTURE_HARDWARE_ACCEPTANCE.md), ersetzen sie aber nicht."""

    name = "joint_and_timing"

    def check(self, gesture, plan, start_pose, compile_error):
        errors = [compile_error] if compile_error else []

        affected_joints = list(plan.joint_names) if plan is not None else []
        effective_duration_s = plan.max_duration_s if plan is not None else None
        effective_speed_scale = None
        if plan is not None and gesture.schema_version == 2 and gesture.keyframes:
            raw_last_t = gesture.keyframes[-1]["time_from_start_s"]
            if effective_duration_s and effective_duration_s > 0:
                effective_speed_scale = raw_last_t / effective_duration_s

        used_joints = set(gesture.affected_joints()) if gesture.schema_version == 2 else set()
        manual_review = []

        if used_joints & HIP_KNEE_JOINTS:
            manual_review.append(
                "Huefte/Knie-Bewegung (HipRoll/HipPitch/KneePitch) -- Standfestigkeit "
                "erfordert besonders sorgfaeltige, beaufsichtigte Pruefung (Auftrag AP8.5)."
            )
        if (used_joints & HIP_KNEE_JOINTS) and (used_joints & ARM_JOINTS):
            manual_review.append(
                "Gleichzeitige Torso- UND Armbewegung -- besonders sorgfaeltig auf "
                "Gleichgewicht/freien Bewegungsraum pruefen (Auftrag AP8.5)."
            )
        if (used_joints & LEFT_ARM_JOINTS) and (used_joints & RIGHT_ARM_JOINTS):
            manual_review.append(
                "Bilaterale Armbewegung (beide Arme betroffen) -- freien Armraum um "
                "Pepper vor jeder Live-Nutzung pruefen (Auftrag AP8.5)."
            )
        if (used_joints & HEAD_JOINTS) and (used_joints & ARM_JOINTS):
            manual_review.append(
                "Kopf- und Armbewegung kombiniert -- 'keine Haende im Gesichtsbereich' "
                "MANUELL bestaetigen (keine echte Vorwaertskinematik in dieser Session "
                "verfuegbar, siehe docs/CAPABILITIES.md) (Auftrag AP8.5)."
            )
        if gesture.name == "self_hug_symbolic":
            manual_review.append(
                "self_hug_symbolic MUSS kontaktlos bleiben -- Pepper darf keine Person "
                "beruehren/keine echte Umarmung ausfuehren (Entwicklungsauftrag 1, "
                "Abschnitt 7, weiterhin bindend)."
            )

        verdict = "fail" if errors else "pass"
        return TrajectorySafetyReport(
            gesture_name=gesture.name,
            verdict=verdict,
            backend_names=[self.name],
            collision_checked=False,
            collision_backend_note=(
                "JointAndTimingValidator prueft KEINE Kollisionen/Koerperabstaende -- "
                "nur Gelenkgrenzen, Geschwindigkeit/Beschleunigung nach Skalierung, "
                "Start-Uebergang und max_duration_s."
            ),
            joint_timing_errors=errors,
            requires_manual_review=manual_review,
            affected_joints=affected_joints,
            effective_speed_scale=effective_speed_scale,
            effective_duration_s=effective_duration_s,
        )


class DisabledCollisionBackend(TrajectorySafetyBackend):
    """NUR fuer Offline-Entwicklung: macht AUSDRUECKLICH KEINE
    Kollisionsaussage. In dieser Session ist kein Kollisions-/URDF-Backend
    reproduzierbar lauffaehig (keine trimesh/fcl/pinocchio-Installation --
    siehe Moduldoku), OBWOHL ein echtes URDF existiert
    (ros2/robot_model/src/pepper_description/urdf/pepper.urdf). Ein
    zukuenftiges echtes Backend darf diese Klasse ersetzen, sobald es
    tatsaechlich, reproduzierbar Kollisionsfreiheit nachweisen kann --
    NICHT vorher, und niemals durch stilles Umbenennen des Verdicts."""

    name = "disabled_collision"

    def check(self, gesture, plan, start_pose, compile_error):
        return TrajectorySafetyReport(
            gesture_name=gesture.name,
            verdict="inconclusive",
            backend_names=[self.name],
            collision_checked=False,
            collision_backend_note=(
                "Kollisionspruefung DEAKTIVIERT/nicht verfuegbar -- dieses Backend "
                "trifft KEINE Aussage ueber Koerperabstaende/Selbstkollision. Ein "
                "'inconclusive'-Gesamtverdict darf NIE automatisch zu "
                "dry_run_validated/live_validated hochgestuft werden."
            ),
            requires_manual_review=[
                "Kollisionsfreiheit wurde NICHT geprueft -- vor jeder Live-Nutzung "
                "beaufsichtigt visuell/physisch bestaetigen."
            ],
            affected_joints=list(plan.joint_names) if plan is not None else [],
        )


def _is_finite(value) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _plan_structurally_intact(plan) -> Optional[str]:
    """Entwicklungsauftrag 04-B, AP8-R2, Abschnitt 3.4 (bestaetigter Fund
    2.4): reine Struktur-/Endlichkeitspruefung des Plans SELBST, UNABHAENGIG
    von der Geste -- Listenlaengen, identische Zeitachse je Gelenk,
    NaN/inf in jedem Winkel/jeder Zeit, endliche max_duration_s. Deckt
    'manipulierte Zeitachse, Listenlaenge, NaN/inf oder Gelenkreihenfolge'
    (Auftrag, Testliste #9) unabhaengig vom Fingerprint-Vergleich ab."""
    if len(plan.angle_lists) != len(plan.joint_names) or len(plan.time_lists) != len(plan.joint_names):
        return (
            f"Listenlaengen stimmen nicht ueberein: {len(plan.joint_names)} Gelenke, "
            f"{len(plan.angle_lists)} Winkellisten, {len(plan.time_lists)} Zeitlisten."
        )
    if not plan.time_lists or not plan.time_lists[0]:
        return "time_lists ist leer."
    reference_times = plan.time_lists[0]
    for i, joint in enumerate(plan.joint_names):
        angles, times = plan.angle_lists[i], plan.time_lists[i]
        if len(angles) != len(times):
            return f"Gelenk '{joint}': angle_lists/time_lists-Laenge stimmt nicht ueberein."
        if times != reference_times:
            return f"Gelenk '{joint}': Zeitachse weicht von Gelenk '{plan.joint_names[0]}' ab (nicht identisch)."
        for a in angles:
            if not _is_finite(a):
                return f"Gelenk '{joint}': nicht-endlicher Winkel {a!r}."
        for t in times:
            if not _is_finite(t):
                return f"Gelenk '{joint}': nicht-endliche Zeit {t!r}."
    if not _is_finite(plan.max_duration_s):
        return f"max_duration_s ist nicht endlich: {plan.max_duration_s!r}."
    return None


def _plan_matches_gesture(gesture, plan, speed_scale: Optional[float],
                          start_pose: Optional[dict] = None) -> Optional[str]:
    """Entwicklungsauftrag 04-B, AP8-R1.8/AP8-R2.4 ('Vertrauensgrenze bei
    vorkompilierten Plaenen'): TrajectorySafetyValidator.validate(...,
    plan=plan) darf einen von AUSSEN uebergebenen, bereits kompilierten
    TrajectoryPlan NICHT blind als gueltig fuer DIESE Geste behandeln --
    sonst koennte ein fremder/veraenderter Plan die Pflichtpruefung
    umgehen.

    Zwei unabhaengige Ebenen:
    1. _plan_structurally_intact(): Dimensionen/NaN-inf/identische
       Zeitachse -- unabhaengig von der Geste.
    2. Fingerprint-Selbstkonsistenz (compute_plan_fingerprint()):
       KinematicCompiler.compile() speichert EINMAL einen Hash ueber die
       tatsaechlich ausfuehrbaren Felder (Gelenkreihenfolge, Winkel,
       Zeiten, Enddauer, Breathing-Metadaten). Diese Funktion rechnet den
       Hash aus den AKTUELLEN Feldwerten NEU und vergleicht ihn mit dem
       gespeicherten -- eine Aenderung AUCH NUR EINES Winkels/Zeitpunkts
       NACH der Kompilierung aendert den neu berechneten Hash und wird
       dadurch zuverlaessig erkannt (Auftrag, Testliste #8/#10). Ein Plan
       ohne (leeren) Fingerprint gilt als NICHT ueber
       KinematicCompiler.compile() erzeugt und wird ebenfalls abgelehnt.
    Zusaetzlich: Gestenname, Gelenkmenge, Breathing-Metadaten, Speed-Scale
    und Startpose-Fingerprint muessen zur Geste/den uebergebenen Aufrufparametern
    passen. Gibt bei einer Abweichung eine Fehlermeldung zurueck (sonst None)."""
    structural_error = _plan_structurally_intact(plan)
    if structural_error is not None:
        return structural_error

    if not getattr(plan, "fingerprint", ""):
        return (
            "Plan besitzt keinen Fingerprint -- nicht ueber KinematicCompiler.compile() "
            "erzeugt (oder das fingerprint-Feld wurde entfernt/geloescht)."
        )
    from .motion_transport import compute_plan_fingerprint  # lokal, siehe kinematic_compiler.py-Vorbild
    if compute_plan_fingerprint(plan) != plan.fingerprint:
        return (
            "Plan-Fingerprint stimmt nicht mit dem tatsaechlichen Plan-Inhalt ueberein -- "
            "der Plan wurde nach der Kompilierung veraendert."
        )

    if plan.source_gesture_name != gesture.name:
        return (
            f"Plan.source_gesture_name={plan.source_gesture_name!r} passt nicht zur "
            f"erwarteten Geste {gesture.name!r}."
        )
    if gesture.schema_version == 2:
        expected_joints = set(gesture.affected_joints())
        if set(plan.joint_names) != expected_joints:
            return (
                f"Plan-Gelenkmenge {sorted(plan.joint_names)} weicht von der Geste "
                f"{gesture.name!r} ({sorted(expected_joints)}) ab."
            )
        if set(plan.disable_breathing_parts) != set(gesture.disable_breathing):
            return (
                f"Plan.disable_breathing_parts={sorted(plan.disable_breathing_parts)} weicht von "
                f"der Geste ({sorted(gesture.disable_breathing)}) ab."
            )
        if gesture.keyframes and speed_scale:
            raw_last_t = gesture.keyframes[-1]["time_from_start_s"]
            expected_duration = raw_last_t / speed_scale
            if abs(plan.max_duration_s - expected_duration) > 1e-6:
                return (
                    f"Plan.max_duration_s={plan.max_duration_s:.6f}s passt nicht zur aus "
                    f"Geste+speed_scale={speed_scale} erwarteten Dauer {expected_duration:.6f}s."
                )
            if plan.speed_scale and abs(plan.speed_scale - speed_scale) > 1e-9:
                return (
                    f"Plan.speed_scale={plan.speed_scale!r} passt nicht zum angeforderten "
                    f"speed_scale={speed_scale!r}."
                )
    from .motion_transport import _fingerprint_start_pose  # lokal, siehe oben
    if getattr(plan, "start_pose_fingerprint", "") and plan.start_pose_fingerprint != _fingerprint_start_pose(start_pose):
        return "Plan-Startpose-Fingerprint passt nicht zur uebergebenen Startpose (start_pose)."
    return None


def _merge_reports(gesture_name: str, reports: list) -> TrajectorySafetyReport:
    """Kombiniert mehrere Backend-Reports zu EINEM Gesamtreport. Ein
    einzelnes 'fail' macht das Gesamtergebnis IMMER 'fail'; sonst macht ein
    einzelnes 'inconclusive' (z.B. DisabledCollisionBackend) das
    Gesamtergebnis 'inconclusive' -- niemals automatisch 'pass', wenn
    irgendein Backend keine Aussage treffen konnte."""
    if any(r.verdict == "fail" for r in reports):
        overall = "fail"
    elif any(r.verdict == "inconclusive" for r in reports):
        overall = "inconclusive"
    else:
        overall = "pass"

    return TrajectorySafetyReport(
        gesture_name=gesture_name,
        verdict=overall,
        backend_names=[n for r in reports for n in r.backend_names],
        collision_checked=any(r.collision_checked for r in reports),
        collision_backend_note=" / ".join(r.collision_backend_note for r in reports if r.collision_backend_note),
        joint_timing_errors=[e for r in reports for e in r.joint_timing_errors],
        warnings=[w for r in reports for w in r.warnings],
        requires_manual_review=[m for r in reports for m in r.requires_manual_review],
        affected_joints=sorted({j for r in reports for j in r.affected_joints}),
        effective_speed_scale=next(
            (r.effective_speed_scale for r in reports if r.effective_speed_scale is not None), None),
        effective_duration_s=next(
            (r.effective_duration_s for r in reports if r.effective_duration_s is not None), None),
    )


def _default_backends() -> list:
    """Entwicklungsauftrag 04-B, AP8-R1.8 (bestaetigter Fund 3.7): der
    STANDARDPFAD nutzte bisher NUR JointAndTimingValidator -- dadurch
    konnte ein Standardreport gleichzeitig verdict='pass' UND
    collision_checked=false melden, was wie ein (nicht vorhandener)
    Kollisionsnachweis wirkt. JointAndTimingValidator + DisabledCollision-
    Backend ist jetzt der Standard -- ein Report ohne echtes Kollisions-
    Backend ist ab sofort STRUKTURELL 'inconclusive', niemals 'pass'."""
    return [JointAndTimingValidator(), DisabledCollisionBackend()]


class TrajectorySafetyValidator:
    """Faehrt eine oder mehrere TrajectorySafetyBackend-Instanzen ueber
    dieselbe Geste und fasst das Ergebnis in EINEM TrajectorySafetyReport
    zusammen. JointAndTimingValidator ist IMMER Pflicht (AP8.5) -- ohne
    mindestens dieses Backend gibt es KEINEN Sicherheitsnachweis, und der
    Konstruktor verweigert die Erzeugung fail-closed."""

    def __init__(self, backends: Optional[list] = None, compiler: Optional[KinematicCompiler] = None):
        self.backends = list(backends) if backends is not None else _default_backends()
        if not any(isinstance(b, JointAndTimingValidator) for b in self.backends):
            raise ValueError(
                "TrajectorySafetyValidator benoetigt mindestens JointAndTimingValidator "
                "als Pflicht-Backend (Auftrag AP8.5) -- kein Sicherheitsnachweis ohne "
                "diese Pruefung."
            )
        self._compiler = compiler or KinematicCompiler()

    def validate(self, gesture, start_pose: Optional[dict] = None,
                 speed_scale: Optional[float] = None, plan=None) -> TrajectorySafetyReport:
        """plan kann bereits vorkompiliert uebergeben werden (z.B. aus
        gesture_catalog.py::_play_v2 -- derselbe Plan, der auch an den
        Transport geht, KEIN zweites Kompilieren) -- sonst kompiliert
        validate() selbst GENAU EINMAL, damit alle Backends dasselbe
        Ergebnis sehen.

        Ein uebergebener plan wird IMMER gegen _plan_matches_gesture()
        geprueft (Entwicklungsauftrag 04-B, AP8-R1.8, 'Vertrauensgrenze
        bei vorkompilierten Plaenen') -- ein erkennbar fremder/veraenderter
        Plan (falscher Gestenname, falsche Gelenkmenge, unplausible aus
        speed_scale abgeleitete Dauer) wird VERWORFEN und wie ein
        Kompilierfehler behandelt (verdict='fail'), nicht stillschweigend
        durchgereicht."""
        compile_error = None
        if plan is None:
            try:
                plan = self._compiler.compile(gesture, speed_scale=speed_scale, start_pose=start_pose)
            except KinematicCompileError as e:
                compile_error = str(e)
        else:
            mismatch = _plan_matches_gesture(gesture, plan, speed_scale, start_pose)
            if mismatch is not None:
                compile_error = f"Vorkompilierter Plan verworfen (Struktur-/Plausibilitaetspruefung): {mismatch}"
                plan = None

        reports = [backend.check(gesture, plan, start_pose, compile_error) for backend in self.backends]
        return _merge_reports(gesture.name, reports)
