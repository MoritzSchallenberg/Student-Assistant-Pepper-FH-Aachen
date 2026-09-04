"""
Deterministischer TTS-/Gesten-Executor (Entwicklungsauftrag 3, AP10).

Rein spielt die Reihenfolge/den Zustandsautomaten je Segment durch --
KEINE eigenen ROS2-Action-Aufrufe hier. say_fn/gesture_fn werden
injiziert (gleiches "Logik von ROS trennen"-Muster wie ueberall in
diesem Projekt, z.B. ihk_pepper_navigation/approach_pose.py). Der reale
ROS-Wrapper (run_dialogue_action_server.py, AP11) implementiert
say_fn/gesture_fn ueber das bestehende blockierende
threading.Event-Actionwarte-Muster aus
ihk_pepper_presentation/presentation_manager_node.py::_say_and_wait()
(braucht MultiThreadedExecutor + ReentrantCallbackGroup) und wendet dort
zusaetzlich tts_sanitizer.py::prepare_for_speech() auf den Text an,
unmittelbar vor dem echten Say-Aufruf.

Synchronisiert NUR an Segmentgrenzen -- die aktuelle TTS-Schnittstelle
bietet KEINE garantierte Wort-fuer-Wort-Synchronisation (Auftrag-Vorgabe,
hier bewusst NICHT behauptet). "with_segment_start" startet Geste und
Sprache in getrennten Threads kurz hintereinander und wartet auf BEIDE
Ergebnisse, bevor das naechste Segment beginnt.

Behebt den in dialog_manager_node.py gefundenen Bug strukturell: der
Aufrufer wechselt den Dialogzustand ERST NACH execute()s Rueckkehr, nie
vorher -- execute() kehrt erst zurueck, wenn Sprache UND Geste jedes
Segments tatsaechlich fertig sind (nicht nur gestartet).
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class SegmentExecutionResult:
    segment_id: str
    say_success: bool = True
    gesture_attempted: bool = False
    gesture_success: bool = True


@dataclass
class ExecutionResult:
    success: bool
    segment_results: list = field(default_factory=list)
    cancelled: bool = False
    rejected_reason: str = ""


class ResponsePlanExecutor:
    def __init__(
        self,
        say_fn: Callable[[str], bool],
        gesture_fn: Callable[[str, float], bool],
        set_speaking_fn: Optional[Callable[[bool], None]] = None,
        segment_status_cb: Optional[Callable[[str, str], None]] = None,
        post_speech_pause_s: float = 0.3,
    ):
        """say_fn(text) -> bool, gesture_fn(name, speed_scale) -> bool --
        BEIDE blockierend, kehren erst zurueck, wenn die jeweilige Action
        WIRKLICH fertig ist (Erfolg oder Fehlschlag), nie nur "gestartet"."""
        self._say_fn = say_fn
        self._gesture_fn = gesture_fn
        self._set_speaking_fn = set_speaking_fn or (lambda _flag: None)
        self._segment_status_cb = segment_status_cb or (lambda *_a: None)
        self.post_speech_pause_s = post_speech_pause_s
        self._cancel_requested = threading.Event()
        self._busy = False

    def cancel(self) -> None:
        self._cancel_requested.set()

    def is_busy(self) -> bool:
        return self._busy

    def execute(self, plan) -> ExecutionResult:
        """Blockiert bis der komplette Plan (oder ein Abbruch) fertig
        ist. Verhindert Doppelstarts -- ein zweiter execute()-Aufruf
        waehrend ein erster noch laeuft wird sofort mit
        rejected_reason abgelehnt, startet NICHTS."""
        if self._busy:
            return ExecutionResult(success=False, rejected_reason="bereits_eine_ausfuehrung_aktiv")

        self._busy = True
        self._cancel_requested.clear()
        results = []
        try:
            self._set_speaking_fn(True)
            for segment in plan.segments:
                if self._cancel_requested.is_set():
                    return ExecutionResult(success=False, segment_results=results, cancelled=True)

                result = self._execute_segment(segment)
                results.append(result)
                status = "done" if (result.say_success and result.gesture_success) else "failed"
                self._segment_status_cb(segment.segment_id, status)

                if self._cancel_requested.is_set():
                    return ExecutionResult(success=False, segment_results=results, cancelled=True)
                if not result.say_success:
                    # Sicherheitsfehler-Prinzip (Auftrag AP9): ein
                    # fehlgeschlagenes Segment bricht den GESAMTEN Plan ab,
                    # kein "einfach weitermachen mit dem naechsten Segment".
                    return ExecutionResult(success=False, segment_results=results)

            time.sleep(self.post_speech_pause_s)  # konfigurierbare Nachlaufzeit
            return ExecutionResult(success=True, segment_results=results)
        finally:
            # Halbduplex-Sperre bleibt bis zum TATSAECHLICHEN Ende aktiv
            # (dieser finally-Block, nicht irgendein frueherer Punkt) --
            # inkl. der Nachlaufzeit oben, die schon innerhalb des try-Blocks
            # lief, bevor hier freigegeben wird.
            self._set_speaking_fn(False)
            self._busy = False

    def _execute_segment(self, segment) -> SegmentExecutionResult:
        result = SegmentExecutionResult(segment_id=segment.segment_id)

        if segment.gesture_name is None:
            result.say_success = self._say_fn(segment.text)
            return result

        result.gesture_attempted = True
        relation = segment.gesture_relation

        if relation == "before_segment":
            result.gesture_success = self._gesture_fn(segment.gesture_name, 1.0)
            result.say_success = self._say_fn(segment.text)
        elif relation == "after_segment":
            result.say_success = self._say_fn(segment.text)
            result.gesture_success = self._gesture_fn(segment.gesture_name, 1.0)
        else:
            # "with_segment_start" (Default-Verhalten fuer alles andere --
            # ResponsePlanValidator hat gesture_relation bereits geprueft,
            # hier kommt nur noch ein gueltiger Wert an).
            gesture_outcome = {}

            def _run_gesture():
                gesture_outcome["success"] = self._gesture_fn(segment.gesture_name, 1.0)

            gesture_thread = threading.Thread(target=_run_gesture, daemon=True)
            gesture_thread.start()
            result.say_success = self._say_fn(segment.text)
            gesture_thread.join()
            result.gesture_success = gesture_outcome.get("success", False)

        return result
