"""
Halbduplex-Steuerung: waehrend Pepper spricht (Bool-Topic /pepper_bridge/
speaking bzw. hier als "speaking"-Topic vom Bridge-Node abonniert), wird
das Verwerten neuer Aeusserungen pausiert, damit Pepper sich nicht selbst
transkribiert. Nach einer konfigurierbaren Nachlaufzeit nach Sprechende
wird wieder zugehoert.

Eine vollstaendige akustische Echo-Kompensation (AEC) ist NICHT
implementiert -- nur diese einfachere, aber robuste Zeitsteuerung. Siehe
docs/IMPLEMENTATION_REPORT.md, Abschnitt "vorbereitet, nicht vollstaendig".
"""
import time


class HalfDuplexController:
    def __init__(self, resume_delay_s: float = 0.5):
        self.resume_delay_s = resume_delay_s
        self._pepper_speaking = False
        self._resume_at = None

    def on_speaking_changed(self, speaking: bool):
        self._pepper_speaking = speaking
        if not speaking:
            self._resume_at = time.time() + self.resume_delay_s
        else:
            self._resume_at = None

    def should_listen(self) -> bool:
        if self._pepper_speaking:
            return False
        if self._resume_at is not None and time.time() < self._resume_at:
            return False
        return True
