"""
Rein lesende Gelenkzustands-Abstraktion (Entwicklungsauftrag 04-B,
AP8.7, Commit 12/14). Die Capture-Kernlogik (gesture_capture.py) erhaelt
AUSSCHLIESSLICH dieses read()-Interface -- niemals Zugriff auf
set_angle/play_trajectory/restore_joints/set_breathing/set_stiffness/
stop_motion oder eine sonstige Bewegungsmethode des zugrunde liegenden
Pepper-Clients. PepperJointStateSource haelt selbst KEINE Referenz auf
irgendetwas anderes als get_angle() -- ein Aufrufer kann also nicht
versehentlich (oder testbar beweisbar: nicht einmal absichtlich ueber
dieses Objekt) eine Bewegung ausloesen.

Zwei Implementierungen: PepperJointStateSource (echt, ruft
ThreadSafePepperClient.get_angle() auf) und ein Test-Double
(_MockJointStateSource in den Tests) fuer die automatischen Tests --
capture-sequence wird in diesem Auftrag AUSSCHLIESSLICH gegen
Test-Doubles geprueft (Abschnitt 1: 'ausschliesslich mit Test-Doubles
geprueft'), der echte Pepper-Lesepfad selbst bleibt
hwverificationrequired.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class JointStateReading:
    """Ein einzelnes (moeglicherweise mehrgelenkiges) Sample. Zeiten sind
    IMMER monotone Zeitstempel (time.monotonic()-kompatibel), nie eine
    Wanduhrzeit -- die Zeitachse einer erfassten Sequenz baut
    ausschliesslich auf diesen Werten auf (gesture_capture.py)."""

    values: dict
    acquisition_started_monotonic_s: float
    acquisition_finished_monotonic_s: float
    source_backend: str
    # "sequential_per_joint" | "batch" -- eine echte Batchmessung darf
    # erst nach technischer Implementierung UND Hardwareverifikation als
    # solche bezeichnet werden (Abschnitt 6), bis dahin ehrlich
    # 'sequential_per_joint', wo das zutrifft.
    acquisition_mode: str

    @property
    def acquisition_span_s(self) -> float:
        """Zeitspanne INNERHALB dieses einen (Mehrgelenk-)Samples --
        bei acquisition_mode='sequential_per_joint' der Zeitversatz
        zwischen dem ersten und dem letzten gelesenen Gelenk. Muss
        sichtbar bleiben, damit eine sequenzielle Messung nie
        faelschlich als zeitgleich dargestellt wird."""
        return self.acquisition_finished_monotonic_s - self.acquisition_started_monotonic_s


class JointStateSource:
    """Vertrag: read() liefert IMMER ein JointStateReading. Ein
    einzelnes fehlendes/ungueltiges Gelenk wird als None/nicht-endlicher
    Wert im values-dict abgebildet (nicht als Exception) -- die
    fail-closed-Entscheidung trifft die Capture-Kernlogik
    (gesture_capture.py), nicht diese Abstraktion selbst. Eine
    tatsaechliche Verbindungsstoerung darf weiterhin propagieren."""

    def read(self, joints: list) -> JointStateReading:
        raise NotImplementedError


class PepperJointStateSource(JointStateSource):
    """Liest AUSSCHLIESSLICH ueber get_angle() des uebergebenen
    Pepper-Clients. Haelt keine weitere Referenz/kein weiteres Attribut
    -- ein Aufrufer, der nur dieses Objekt haelt, hat strukturell keinen
    Weg zu set_angle/play_trajectory/restore_joints/set_breathing/
    set_stiffness/stop_motion (die Methoden sind auf DIESEM Objekt gar
    nicht vorhanden).

    apps/web/pepper/qicli.py::get_angles() liest aktuell nacheinander
    EIN get_angle()-SSH-Kommando je Gelenk (kein Batch-ALMemory-Aufruf)
    -- acquisition_mode dokumentiert das ehrlich als
    'sequential_per_joint', keine Batchmessung wird vorgetaeuscht,
    solange sie nicht technisch implementiert UND hardwareverifiziert
    ist (Abschnitt 6)."""

    def __init__(self, get_angle_fn):
        """get_angle_fn: Callable[[str], float|None] -- bewusst NUR diese
        eine Funktion (nicht der volle Pepper-Client) wird gehalten, um
        strukturell auszuschliessen, dass diese Klasse jemals eine
        andere Methode des Clients aufrufen kann."""
        self._get_angle_fn = get_angle_fn

    def read(self, joints: list) -> JointStateReading:
        started = time.monotonic()
        values = {}
        for joint in joints:
            values[joint] = self._get_angle_fn(joint)
        finished = time.monotonic()
        return JointStateReading(
            values=values,
            acquisition_started_monotonic_s=started,
            acquisition_finished_monotonic_s=finished,
            source_backend="qicli_ssh",
            acquisition_mode="sequential_per_joint",
        )
