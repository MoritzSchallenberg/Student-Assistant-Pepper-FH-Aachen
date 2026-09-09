"""
Transport-Abstraktion fuer kompilierte Gesten-Trajektorien
(Entwicklungsauftrag 3, AP12: "Validator -> Kinematischer Compiler ->
Trajectory Plan -> Motion Transport -> Pepper oder Mock").

Trennt bewusst "was soll passieren" (TrajectoryPlan, von
kinematic_compiler.py erzeugt) von "wie wird es tatsaechlich gesendet"
(MotionTransport-Implementierungen hier). Kein Transport importiert
rclpy oder publiziert irgendein ROS2-Topic -- insbesondere niemals
/cmd_vel (dieses Modul bewegt ausschliesslich Arm-/Kopf-/Huefte-Gelenke
ueber ALMotion, nie die Basis).
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Entwicklungsauftrag 04-B, AP5B, Abschnitt 10: Standard-Obergrenze fuer
# cancel()s begrenzte Wartezeit auf eine Bestaetigung -- kein
# unbegrenztes _done_event.wait() mehr (das war der bestaetigte Fund
# 2.2: cancel() wartete bei einer laufenden synchronen Trajektorie
# zunaechst UNBEGRENZT).
DEFAULT_CANCEL_TIMEOUT_S = 2.0

# Zeitdauer (s) fuer den einen synchronen Wiederherstellungsaufruf am
# Ende einer Geste. Bewusst kurz, aber > 0 (ALMotion.angleInterpolation
# mit Dauer 0 ist nicht garantiert definiert).
RESTORE_DURATION_S = 1.5


class TransportStatus:
    """Kein echtes Enum (einfache String-Konstanten reichen, leichter
    ueber ROS2-Feedback-Felder/Logs zu transportieren als spaeter)."""

    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CancelResult:
    """Strukturiertes Ergebnis von MotionTransport.cancel()
    (Entwicklungsauftrag 04-B, AP5B, Abschnitt 10) -- ersetzt das
    bisherige unbegrenzte cancel() -> None. cancel_confirmed=True
    bedeutet NUR, dass der Transport-Zustand als beendet beobachtet
    wurde (poll() == CANCELLED/DONE/FAILED) -- KEINE Aussage darueber,
    ob Pepper sich tatsaechlich bewegt hat oder verstummt ist (siehe
    docs/ACTION_CANCELLATION.md: "Unterschied zwischen ROS-Cancel und
    bestaetigtem Hardware-Stopp")."""

    cancel_requested: bool
    cancel_confirmed: bool
    final_transport_state: str
    elapsed_s: float
    error_message: str = ""


@dataclass
class TrajectoryPlan:
    """Ergebnis von KinematicCompiler.compile() -- vollstaendig aufgeloest:
    JEDES Gelenk in joint_names hat in angle_lists/time_lists dieselbe
    Anzahl Punkte auf DERSELBEN Zeitachse (siehe kinematic_compiler.py::
    fill_missing_joint_holds -- behebt die zuvor moegliche
    Gelenk-zu-Gelenk-Zeitachsen-Inkonsistenz)."""

    joint_names: list
    angle_lists: list  # list[list[float]], gleiche Laenge je Gelenk
    time_lists: list  # list[list[float]], IDENTISCH fuer jedes Gelenk
    source_gesture_name: str
    max_duration_s: float
    disable_breathing_parts: list = field(default_factory=list)


class MotionTransport(ABC):
    """prepare() -> start() -> (poll() bis fertig) -> restore().
    cancel() kann jederzeit dazwischen aufgerufen werden."""

    @abstractmethod
    def prepare(self, plan: TrajectoryPlan, restore_snapshot: dict | None = None) -> None:
        """Nimmt den Plan entgegen. restore_snapshot (falls gegeben):
        Gelenk->Winkel-Zuordnung, auf die restore() spaeter zurueckfaehrt
        (typischerweise ein pepper_client.snapshot_joints()-Ergebnis, VOR
        jeder Bewegung aufgenommen -- siehe gesture_catalog.py)."""

    @abstractmethod
    def start(self) -> None:
        """Startet die Trajektorie. Darf nicht blockieren, bis die
        Bewegung fertig ist (siehe poll()/wait())."""

    @abstractmethod
    def poll(self) -> str:
        """Aktueller TransportStatus, ohne zu blockieren."""

    @abstractmethod
    def cancel(self, timeout_s: float = DEFAULT_CANCEL_TIMEOUT_S) -> CancelResult:
        """Bricht so gut wie moeglich ab und liefert ein STRUKTURIERTES
        Ergebnis (nie nur True/False) -- siehe QicliTrajectoryTransport
        fuer die dokumentierten Grenzen einer echten Mid-Flight-
        Unterbrechung bei einer synchronen qicli-SSH-Anfrage. Wartet
        HOECHSTENS timeout_s auf eine Bestaetigung -- kein unbegrenztes
        Blockieren (Entwicklungsauftrag 04-B, AP5B, Abschnitt 10)."""

    @abstractmethod
    def restore(self) -> None:
        """Faehrt (falls ein restore_snapshot uebergeben wurde) alle
        betroffenen Gelenke in EINEM synchronen Aufruf auf die
        Schnappschuss-Winkel zurueck -- NIE Gelenk fuer Gelenk in einer
        Schleife (das war der urspruengliche Fehler in
        qicli.py::restore_joments(), siehe AP12-Bericht)."""


class MockMotionTransport(MotionTransport):
    """Reine Buchfuehrung fuer Tests -- ruft nie irgendeine Hardware/SSH-
    Verbindung auf. `.calls` protokolliert jede Methode in Aufrufreihenfolge."""

    def __init__(self, fail_on_start: bool = False):
        self.calls = []
        self._fail_on_start = fail_on_start
        self._status = TransportStatus.IDLE
        self._plan = None
        self._restore_snapshot = None
        self.last_error = None

    def prepare(self, plan, restore_snapshot=None):
        self._plan = plan
        self._restore_snapshot = restore_snapshot
        self._status = TransportStatus.IDLE
        self.calls.append(("prepare", plan, restore_snapshot))

    def start(self):
        self.calls.append(("start",))
        if self._fail_on_start:
            self.last_error = RuntimeError("simulierter Fehlschlag (MockMotionTransport)")
            self._status = TransportStatus.FAILED
            return
        self._status = TransportStatus.DONE

    def poll(self):
        return self._status

    def wait(self, timeout_s=None):
        return self._status

    def cancel(self, timeout_s: float = DEFAULT_CANCEL_TIMEOUT_S) -> CancelResult:
        self.calls.append(("cancel",))
        if self._status == TransportStatus.RUNNING or self._status == TransportStatus.IDLE:
            self._status = TransportStatus.CANCELLED
        return CancelResult(True, True, self._status, 0.0)

    def restore(self):
        self.calls.append(("restore", self._restore_snapshot))


class DryRunMotionTransport(MotionTransport):
    """Loggt den vollstaendigen Plan, ruft NIEMALS eine Hardware-Methode
    auf -- auch restore()/cancel() bleiben reine Protokollausgaben. Fuer
    gesturectl dry-run (AP14) und GestureCatalog.play(dry_run=True)."""

    def __init__(self, log: logging.Logger | None = None):
        self._log = log or logger
        self._plan = None
        self._status = TransportStatus.IDLE

    def prepare(self, plan, restore_snapshot=None):
        self._plan = plan
        self._log.info(
            "[dry-run] Geste '%s': %d Gelenke, Endzeit %.2fs -- %s",
            plan.source_gesture_name, len(plan.joint_names), plan.max_duration_s,
            dict(zip(plan.joint_names, plan.angle_lists)),
        )

    def start(self):
        self._status = TransportStatus.DONE
        self._log.info("[dry-run] '%s' waere jetzt gesendet worden (keine Hardwareaktion).",
                        self._plan.source_gesture_name if self._plan else "?")

    def poll(self):
        return self._status

    def wait(self, timeout_s=None):
        return self._status

    def cancel(self, timeout_s: float = DEFAULT_CANCEL_TIMEOUT_S) -> CancelResult:
        self._log.info("[dry-run] Abbruch angefordert (keine Hardwareaktion noetig).")
        if self._status != TransportStatus.DONE:
            self._status = TransportStatus.CANCELLED
        return CancelResult(True, True, self._status, 0.0)

    def restore(self):
        self._log.info("[dry-run] Wiederherstellung waere jetzt gesendet worden (keine Hardwareaktion).")


class QicliTrajectoryTransport(MotionTransport):
    """Echter Transport ueber ThreadSafePepperClient/qicli. dry_run_validated,
    NICHT live_validated (kein Pepper in dieser Session erreichbar -- siehe
    docs/GESTURE_TRANSPORT.md).

    start() sendet die Trajektorie in einem Hintergrund-Thread (der
    zugrundeliegende qicli-Aufruf blockiert selbst per SSH bis NAOqi
    fertig ist) -- poll()/wait() lesen den Fortschritt, ohne den Aufrufer
    selbst zu blockieren.

    cancel() hat KEIN natives Abbruch-Primitiv fuer eine bereits an NAOqi
    gesendete synchrone Anfrage (Entwicklungsauftrag 04-B, AP5B,
    Abschnitt 10 -- dokumentierter Capability-Test: qicli exponiert nur
    synchrone "qicli call"-SSH-Aufrufe, kein ALMotion.post.*-Task-ID-
    Mechanismus wird von diesem Werkzeug genutzt/ist ohne Hardwarezugriff
    verifizierbar). cancel() wartet deshalb NICHT mehr unbegrenzt: es
    sendet SOFORT einen Best-Effort-Interrupt ueber einen unabhaengigen
    Kanal (interrupt_channel, siehe pepper_client.py::
    PepperInterruptChannel -- eigene SSH-Verbindung, eigener Lock, blockiert
    NIE hinter dem Lock des Hauptkanals) und wartet danach HOECHSTENS
    timeout_s auf eine Bestaetigung, dass die urspruengliche Anfrage
    tatsaechlich zurueckgekehrt ist. Liefert IMMER ein strukturiertes
    CancelResult -- kein einfaches True/False, das ein echtes Mid-Flight-
    Abbrechen vortaeuschen wuerde. Ohne interrupt_channel (aeltere
    Aufrufer/Tests) faellt cancel() auf das alte Verhalten zurueck
    (warten bis timeout_s, dann Halteposition ueber denselben Kanal --
    NICHT mehr unbegrenzt, aber weiterhin ohne echte Nebenlaeufigkeit
    zum Hauptkanal)."""

    CANCEL_HOLD_DURATION_S = 0.05

    def __init__(self, pepper_client, interrupt_channel=None):
        self._client = pepper_client
        self._interrupt_channel = interrupt_channel
        self._plan = None
        self._restore_snapshot = None
        self._status = TransportStatus.IDLE
        self.last_error = None
        self._thread = None
        self._cancel_requested = threading.Event()
        self._done_event = threading.Event()

    def prepare(self, plan, restore_snapshot=None):
        self._plan = plan
        self._restore_snapshot = restore_snapshot
        self._status = TransportStatus.IDLE
        self.last_error = None
        self._cancel_requested.clear()
        self._done_event.clear()

    def start(self):
        if self._plan is None:
            raise RuntimeError("prepare() muss vor start() aufgerufen werden")
        if self._cancel_requested.is_set():
            self._status = TransportStatus.CANCELLED
            self._done_event.set()
            return
        self._status = TransportStatus.RUNNING
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._client.play_trajectory(self._plan.joint_names, self._plan.angle_lists, self._plan.time_lists)
            self._status = TransportStatus.CANCELLED if self._cancel_requested.is_set() else TransportStatus.DONE
        except Exception as e:  # noqa: BLE001 -- muss jeden Transportfehler auffangen, nie crashen
            self.last_error = e
            self._status = TransportStatus.FAILED
        finally:
            self._done_event.set()

    def poll(self):
        return self._status

    def wait(self, timeout_s: float | None = None):
        """Nicht Teil der abstrakten Schnittstelle -- reine Bequemlichkeit
        fuer Aufrufer, die synchron auf das Ergebnis warten wollen (z.B.
        gesture_catalog.py::_play_v2, das die alte blockierende Semantik
        beibehaelt)."""
        self._done_event.wait(timeout_s)
        return self._status

    def cancel(self, timeout_s: float = DEFAULT_CANCEL_TIMEOUT_S) -> CancelResult:
        start = time.monotonic()
        self._cancel_requested.set()

        if self._status == TransportStatus.IDLE:
            self._status = TransportStatus.CANCELLED
            self._done_event.set()
            return CancelResult(True, True, TransportStatus.CANCELLED, time.monotonic() - start)

        if self._done_event.is_set():
            # Bereits natuerlich fertig (DONE/FAILED/CANCELLED) -- cancel()
            # kommt zu spaet, um noch etwas zu bewirken.
            return CancelResult(True, True, self._status, time.monotonic() - start)

        # RUNNING: SOFORT einen Best-Effort-Interrupt ueber den
        # unabhaengigen Kanal senden -- blockiert NICHT hinter dem Lock
        # des Hauptkanals (siehe Klassendoku, Auftrag Abschnitt 2.3).
        interrupt_sent = False
        interrupt_error = ""
        if self._interrupt_channel is not None:
            try:
                self._interrupt_channel.stop_motion()
                interrupt_sent = True
            except Exception as e:  # noqa: BLE001 -- Abbruch darf selbst nicht crashen
                interrupt_error = str(e)
                logger.warning("Interrupt-Kanal stop_motion() fehlgeschlagen.", exc_info=True)

        # HOECHSTENS timeout_s auf eine Bestaetigung warten -- kein
        # unbegrenztes Blockieren mehr (der urspruengliche Fund 2.2).
        finished = self._done_event.wait(timeout_s)
        elapsed = time.monotonic() - start

        if not finished:
            return CancelResult(
                cancel_requested=True, cancel_confirmed=False,
                final_transport_state=TransportStatus.RUNNING, elapsed_s=elapsed,
                error_message=(
                    "urspruengliche synchrone Anfrage lief nach Ablauf des Timeouts noch -- "
                    + ("Interrupt-Befehl gesendet" if interrupt_sent
                       else f"Interrupt-Befehl NICHT gesendet: {interrupt_error or 'kein interrupt_channel konfiguriert'}")
                ),
            )

        if self._status == TransportStatus.FAILED:
            # War die Anfrage selbst schon gescheitert (z.B. Verbindungs-
            # abbruch), zaehlt das Cancel dennoch als "bestaetigt beendet".
            self._status = TransportStatus.CANCELLED
            return CancelResult(True, True, TransportStatus.CANCELLED, elapsed,
                                 error_message=str(self.last_error) if self.last_error else "")

        # Ohne interrupt_channel (aeltere Aufrufer/Tests): Best-Effort-
        # Halteposition weiterhin ueber denselben Kanal, aber ERST NACHDEM
        # die urspruengliche Anfrage bestaetigt zurueckgekehrt ist (kein
        # unbegrenztes Warten mehr davor).
        if self._interrupt_channel is None:
            try:
                joints = list(self._plan.joint_names)
                current = {j: self._client.get_angle(j) for j in joints}
                names = [j for j in joints if current.get(j) is not None]
                if names:
                    self._client.play_trajectory(
                        names,
                        [[current[j]] for j in names],
                        [[self.CANCEL_HOLD_DURATION_S] for _ in names],
                    )
            except Exception:  # noqa: BLE001 -- Abbruch darf selbst nicht crashen
                logger.warning("Halteposition nach cancel() konnte nicht gesendet werden.", exc_info=True)

        self._status = TransportStatus.CANCELLED
        return CancelResult(True, True, TransportStatus.CANCELLED, elapsed, error_message=interrupt_error)

    def restore(self):
        if not self._restore_snapshot:
            return
        joint_names = [j for j, angle in self._restore_snapshot.items() if angle is not None]
        if not joint_names:
            return
        angle_lists = [[self._restore_snapshot[j]] for j in joint_names]
        time_lists = [[RESTORE_DURATION_S] for _ in joint_names]
        # EIN synchroner play_trajectory()-Aufruf fuer ALLE Gelenke -- behebt
        # den urspruenglichen Fehler (qicli.py::restore_joints() faehrt
        # Gelenk fuer Gelenk in einer Schleife, siehe AP12-Bericht).
        self._client.play_trajectory(joint_names, angle_lists, time_lists)


class LocalPepperQiHelperTransport(MotionTransport):
    """Platzhalter fuer einen kuenftigen Transport ueber eine direkte
    NAOqi-SDK-Verbindung (statt SSH+qicli-CLI) -- NICHT implementiert,
    NICHT live validiert, in dieser Session ohne verfuegbare NAOqi-Python-
    Bibliothek nicht umsetzbar. Existiert nur als dokumentierter
    Erweiterungspunkt (siehe docs/GESTURE_TRANSPORT.md): wuerde
    ausschliesslich bereits validierte TrajectoryPlan-Objekte entgegennehmen
    und NUR fest definierte ALMotion-Methoden aufrufen -- keine freie
    Shell-/qicli-Ausfuehrung. Jede Methode wirft bewusst NotImplementedError,
    damit sie nie versehentlich als funktionsfaehig missverstanden wird."""

    def prepare(self, plan, restore_snapshot=None):
        raise NotImplementedError("LocalPepperQiHelperTransport ist ein Platzhalter, siehe Klassendoku")

    def start(self):
        raise NotImplementedError("LocalPepperQiHelperTransport ist ein Platzhalter, siehe Klassendoku")

    def poll(self):
        raise NotImplementedError("LocalPepperQiHelperTransport ist ein Platzhalter, siehe Klassendoku")

    def cancel(self, timeout_s: float = DEFAULT_CANCEL_TIMEOUT_S) -> CancelResult:
        raise NotImplementedError("LocalPepperQiHelperTransport ist ein Platzhalter, siehe Klassendoku")

    def restore(self):
        raise NotImplementedError("LocalPepperQiHelperTransport ist ein Platzhalter, siehe Klassendoku")
