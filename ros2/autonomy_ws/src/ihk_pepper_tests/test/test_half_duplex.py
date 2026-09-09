"""
Tests fuer half_duplex.py (bisher UNGETESTET -- gefunden waehrend
Entwicklungsauftrag 04-B, AP6.1, Abschnitt 16: "TTS darf niemals selbst
ein Wakeword ausloesen" verlangt explizite Testabdeckung genau dieses
Mechanismus). HalfDuplexController ist die strukturelle Sicherung dafuer
-- audio_node.py::_process_loop() verwirft jeden Audio-Chunk, solange
should_listen() False liefert, BEVOR er ueberhaupt beim VAD-Segmentierer/
Wakeword-Detektor ankommt (siehe audio_node.py: "if not
self.half_duplex.should_listen(): continue").

Keine now_fn-Injektion in half_duplex.py (nutzt time.time() direkt) --
die Zeitschwellen-Tests verwenden deshalb kurze echte time.sleep()-
Aufrufe, gleiches etablierte Muster wie
test_bridge_node_set_head_pose.py::test_cancel_calls_interrupt_channel_and_cancels_goal.
"""
import time

from ihk_pepper_audio.half_duplex import HalfDuplexController


def test_should_listen_true_by_default():
    hd = HalfDuplexController(resume_delay_s=0.5)
    assert hd.should_listen() is True


def test_should_listen_false_while_pepper_is_speaking():
    hd = HalfDuplexController(resume_delay_s=0.5)
    hd.on_speaking_changed(True)
    assert hd.should_listen() is False


def test_should_listen_false_during_resume_delay_after_speaking_ends():
    hd = HalfDuplexController(resume_delay_s=1.0)
    hd.on_speaking_changed(True)
    hd.on_speaking_changed(False)
    # Sprechen ist gerade erst beendet -- Nachlaufzeit noch nicht abgelaufen.
    assert hd.should_listen() is False


def test_should_listen_true_after_resume_delay_elapses():
    hd = HalfDuplexController(resume_delay_s=0.05)
    hd.on_speaking_changed(True)
    hd.on_speaking_changed(False)
    time.sleep(0.08)
    assert hd.should_listen() is True


def test_speaking_again_before_resume_delay_elapsed_resets_the_wait():
    # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 16: Pepper faengt an,
    # WIEDER zu sprechen, noch waehrend die Nachlaufzeit vom vorigen
    # Satz laeuft -- should_listen() muss sofort wieder False werden UND
    # NACH diesem zweiten Sprechende erneut die VOLLE Nachlaufzeit
    # abwarten (kein verkuerztes/verfruehtes Wiederzuhoeren).
    hd = HalfDuplexController(resume_delay_s=0.1)
    hd.on_speaking_changed(True)
    hd.on_speaking_changed(False)
    hd.on_speaking_changed(True)  # wieder an, noch innerhalb der Nachlaufzeit
    assert hd.should_listen() is False
    hd.on_speaking_changed(False)
    assert hd.should_listen() is False  # frische Nachlaufzeit hat gerade erst begonnen
    time.sleep(0.15)
    assert hd.should_listen() is True


def test_zero_resume_delay_listens_immediately_after_speaking_ends():
    hd = HalfDuplexController(resume_delay_s=0.0)
    hd.on_speaking_changed(True)
    hd.on_speaking_changed(False)
    assert hd.should_listen() is True


def test_never_listens_between_speaking_start_and_speaking_end_even_across_many_toggles():
    hd = HalfDuplexController(resume_delay_s=0.05)
    for _ in range(5):
        hd.on_speaking_changed(True)
        assert hd.should_listen() is False
        hd.on_speaking_changed(False)
        # Direkt nach dem Umschalten -- Nachlaufzeit laeuft noch.
        assert hd.should_listen() is False
