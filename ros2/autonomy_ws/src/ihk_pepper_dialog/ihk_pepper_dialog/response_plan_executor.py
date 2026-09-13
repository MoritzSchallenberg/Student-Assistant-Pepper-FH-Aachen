"""
Deterministischer TTS-/Gesten-Executor (Entwicklungsauftrag 3, AP10;
Cancel-/Race-Haertung Entwicklungsauftrag 04-B, AP8.8, Commit 13/14).

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

Entwicklungsauftrag 04-B, AP8.8 (bestaetigte Funde 3.1): drei reale
Abbruchluecken behoben, alle durch je einen Regressionstest in
test_response_plan_executor.py abgesichert:

1. cancel() VOR execute() wurde durch das anschliessende
   self._cancel_requested.clear() am ANFANG von execute() wirkungslos
   gemacht -- das Zuruecksetzen fuer den NAECHSTEN Durchlauf passiert
   jetzt ausschliesslich im finally-Block AM ENDE von execute(), nie am
   Anfang. Ein Cancel, der vor/waehrend eines Durchlaufs ankommt, bleibt
   bis zu dessen eigenem Ende sichtbar.
2. Ein Cancel waehrend einer 'before_segment'-Geste verhinderte den
   danach gestarteten TTS-Aufruf NICHT -- jetzt wird cancel_requested
   zwischen Geste und TTS erneut geprueft.
3. 'after_segment' startete die Geste auch dann, wenn TTS zuvor
   fehlgeschlagen war -- jetzt nur noch nach erfolgreichem TTS UND ohne
   zwischenzeitliches Cancel.

Zusaetzlich: atomare Doppelstartpruefung (Lock statt zweier getrennter,
nicht-atomarer Anweisungen), Worker-Ausnahmen aus dem
'with_segment_start'-Gestenthread werden abgefangen und als Ergebnis
erfasst (nie stillschweigend verschluckt), und die Nachlaufpause
reagiert jetzt auf ein Cancel (threading.Event.wait() statt time.sleep(),
kehrt sofort zurueck, sobald cancel() waehrend der Pause ankommt).
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
    gesture_error: str = ""


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
        cancel_active_fn: Optional[Callable[[], None]] = None,
    ):
        """say_fn(text) -> bool, gesture_fn(name, speed_scale) -> bool --
        BEIDE blockierend, kehren erst zurueck, wenn die jeweilige Action
        WIRKLICH fertig ist (Erfolg oder Fehlschlag), nie nur "gestartet".

        cancel_active_fn (Entwicklungsauftrag 04-B, AP5B, Abschnitt 13):
        wird von cancel() SOFORT aufgerufen, zusaetzlich zum bisherigen
        Flag (das nur zwischen zwei Segmenten geprueft wird). Der reale
        ROS-Wrapper (run_dialogue_action_server.py) bindet hier einen
        Aufruf, der das GERADE LAUFENDE Say-/PlayGesture-Ziel aktiv per
        cancel_goal_async() abbricht -- vorher wartete cancel() rein
        passiv auf die naechste Segmentgrenze, eine bereits laufende
        Action wurde nie aktiv benachrichtigt."""
        self._say_fn = say_fn
        self._gesture_fn = gesture_fn
        self._set_speaking_fn = set_speaking_fn or (lambda _flag: None)
        self._segment_status_cb = segment_status_cb or (lambda *_a: None)
        self.post_speech_pause_s = post_speech_pause_s
        self._cancel_active_fn = cancel_active_fn or (lambda: None)
        self._cancel_requested = threading.Event()
        self._busy = False
        # Entwicklungsauftrag 04-B, AP8.8: schuetzt die vorher
        # nicht-atomare "if self._busy: ... self._busy = True"-Sequenz --
        # zwei gleichzeitige execute()-Aufrufe auf DERSELBEN Instanz
        # koennten sonst beide die Busy-Pruefung als "frei" lesen, bevor
        # einer von beiden sie auf True setzt.
        self._start_lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel_requested.set()
        self._cancel_active_fn()

    def is_busy(self) -> bool:
        return self._busy

    def execute(self, plan) -> ExecutionResult:
        """Blockiert bis der komplette Plan (oder ein Abbruch) fertig
        ist. Verhindert Doppelstarts -- ein zweiter execute()-Aufruf
        waehrend ein erster noch laeuft wird sofort mit
        rejected_reason abgelehnt, startet NICHTS (atomar per
        _start_lock geprueft/gesetzt).

        Ein VOR diesem Aufruf bereits gesetztes Cancel (z.B. cancel()
        wurde aufgerufen, bevor execute() ueberhaupt startete) wird
        HIER respektiert, nicht stillschweigend geloescht -- das
        Zuruecksetzen fuer den naechsten Durchlauf passiert
        ausschliesslich im finally-Block am ENDE dieses Aufrufs."""
        with self._start_lock:
            if self._busy:
                return ExecutionResult(success=False, rejected_reason="bereits_eine_ausfuehrung_aktiv")
            self._busy = True

        results = []
        try:
            if self._cancel_requested.is_set():
                return ExecutionResult(success=False, cancelled=True)

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

            # Entwicklungsauftrag 04-B, AP8.8 (bestaetigter Fund): die
            # Nachlaufpause reagiert jetzt auf ein Cancel -- .wait()
            # kehrt SOFORT zurueck, sobald cancel() waehrend der Pause
            # aufgerufen wird, statt die volle Dauer stur abzuwarten.
            cancelled_during_pause = self._cancel_requested.wait(timeout=self.post_speech_pause_s)
            if cancelled_during_pause:
                return ExecutionResult(success=False, segment_results=results, cancelled=True)
            return ExecutionResult(success=True, segment_results=results)
        finally:
            # Halbduplex-Sperre bleibt bis zum TATSAECHLICHEN Ende aktiv
            # (dieser finally-Block, nicht irgendein frueherer Punkt) --
            # inkl. der Nachlaufzeit oben, die schon innerhalb des try-Blocks
            # lief, bevor hier freigegeben wird.
            self._set_speaking_fn(False)
            self._busy = False
            # ERST HIER, am Ende, fuer den naechsten Durchlauf
            # zuruecksetzen -- NIEMALS am Anfang von execute() (das wuerde
            # ein vor diesem Aufruf bereits gesetztes Cancel wirkungslos
            # machen, bestaetigter Fund 3.1).
            self._cancel_requested.clear()

    def _execute_segment(self, segment) -> SegmentExecutionResult:
        result = SegmentExecutionResult(segment_id=segment.segment_id)

        if segment.gesture_name is None:
            result.say_success = self._say_fn(segment.text)
            return result

        relation = segment.gesture_relation

        if relation == "before_segment":
            result.gesture_attempted = True
            result.gesture_success = self._run_gesture_safely(result, segment.gesture_name)
            if self._cancel_requested.is_set():
                # Entwicklungsauftrag 04-B, AP8.8 (bestaetigter Fund):
                # kein TTS-Neustart, wenn waehrend der vorangehenden
                # Geste ein Cancel ankam.
                return result
            result.say_success = self._say_fn(segment.text)
        elif relation == "after_segment":
            result.say_success = self._say_fn(segment.text)
            if not result.say_success or self._cancel_requested.is_set():
                # Entwicklungsauftrag 04-B, AP8.8 (bestaetigter Fund):
                # die Geste wird NUR nach erfolgreichem TTS UND ohne
                # zwischenzeitliches Cancel gestartet -- gesture_attempted
                # bleibt bewusst False, sie wurde nie versucht.
                return result
            result.gesture_attempted = True
            result.gesture_success = self._run_gesture_safely(result, segment.gesture_name)
        else:
            # "with_segment_start" (Default-Verhalten fuer alles andere --
            # ResponsePlanValidator hat gesture_relation bereits geprueft,
            # hier kommt nur noch ein gueltiger Wert an).
            result.gesture_attempted = True
            gesture_outcome = {}

            def _run_gesture():
                try:
                    gesture_outcome["success"] = self._gesture_fn(segment.gesture_name, 1.0)
                except Exception as e:
                    # Entwicklungsauftrag 04-B, AP8.8 (bestaetigter Fund):
                    # eine Ausnahme im Gestenthread wurde bisher NICHT
                    # abgefangen -- threading.Thread verschluckt sie
                    # stillschweigend (nur eine Konsolenmeldung), der
                    # Aufrufer sah lediglich gesture_success=False ohne
                    # jeden Hinweis auf die Ursache. Jetzt als Ergebnis
                    # erfasst (result.gesture_error).
                    gesture_outcome["success"] = False
                    gesture_outcome["error"] = str(e)

            gesture_thread = threading.Thread(target=_run_gesture, daemon=True)
            gesture_thread.start()
            result.say_success = self._say_fn(segment.text)
            gesture_thread.join()
            result.gesture_success = gesture_outcome.get("success", False)
            result.gesture_error = gesture_outcome.get("error", "")

        return result

    def _run_gesture_safely(self, result: SegmentExecutionResult, gesture_name: str) -> bool:
        """Faengt eine Ausnahme aus gesture_fn() ab (Entwicklungsauftrag
        04-B, AP8.8) -- ein Worker-Fehler wird als Ergebnis erfasst
        (result.gesture_error), NIE unbehandelt nach aussen durchgereicht
        (das wuerde execute() selbst abstuerzen lassen, OHNE dass
        _busy/die Halbduplex-Sperre je durch den finally-Block korrekt
        freigegeben wuerden -- doch, der finally-Block faengt das
        strukturell ohnehin ab; diese Methode verhindert zusaetzlich,
        dass ein einzelner Gestenfehler den GESAMTEN Ausfuehrungspfad
        mit einer Python-Ausnahme statt einem sauberen False beendet)."""
        try:
            return self._gesture_fn(gesture_name, 1.0)
        except Exception as e:
            result.gesture_error = str(e)
            return False
