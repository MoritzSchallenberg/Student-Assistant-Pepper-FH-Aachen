#!/usr/bin/env python3
"""
ihk_pepper_audio: Ringpuffer + VAD + Halbduplex + Whisper-Transkription.

Ersetzt NICHT apps/web/stt/listen_loop.py -- das bleibt als
eigenstaendiger, bewiesen funktionierender Fallback erhalten (Auftrag
Abschnitt 3.1/7). Dieser Node ist der neue, kontinuierliche Hauptweg.

Getestet (2026-08-19): Segmentierungs-/VAD-/Halbduplex-Logik per Unit-
Tests mit synthetischen/aufgezeichneten Audiodaten (siehe
ihk_pepper_tests). NICHT live gegen ein echtes Mikrofon oder den echten
Pepper-PulseAudio-Stream getestet -- Pepper war in dieser Session nicht
durchgehend erreichbar, und kein USB-Mikrofon war angeschlossen. Siehe
docs/IMPLEMENTATION_REPORT.md.
"""
import queue
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool, Float32, UInt8

from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import SoundDirection, WakewordEvent

from .audio_source import create_source, AudioSourceError, CHUNK_MS
from .ring_buffer import RingBuffer
from .vad_segmenter import UtteranceSegmenter, create_vad_backend
from .half_duplex import HalfDuplexController
from .cancel_words import detect_command, is_hard_stop
from .wakeword import WakewordDetector
from .wakeword_gate import WakewordGate

try:
    from ihk_pepper_interfaces.srv import CancelInteraction
    HAVE_CANCEL_SRV = True
except ImportError:
    HAVE_CANCEL_SRV = False


class AudioNode(Node):
    def __init__(self):
        super().__init__("audio_node")

        self.declare_parameter("source_kind", "pepper_pulseaudio")
        self.declare_parameter("source_file_path", "")
        self.declare_parameter("microphone_device", -1)
        self.declare_parameter("pepper_host", "")
        self.declare_parameter("pepper_user", "nao")
        self.declare_parameter("pepper_password", "")
        self.declare_parameter("vad_threshold", 0.5)
        self.declare_parameter("preroll_s", 0.3)
        self.declare_parameter("min_speech_s", 0.3)
        self.declare_parameter("silence_end_s", 0.7)
        self.declare_parameter("max_utterance_s", 15.0)
        self.declare_parameter("whisper_model", "small")
        self.declare_parameter("whisper_language", "de")
        self.declare_parameter("wakeword_model_path", "")
        self.declare_parameter("reconnect_delay_s", 3.0)
        # Entwicklungsauftrag 04-B, AP6, Abschnitt 8: Cooldown/Entprellung
        # zwischen zwei Wakeword-Ereignissen, und eine BEGRENZTE (nicht
        # ewige) Sitzungsdauer nach einem erkannten Wakeword -- behebt
        # den bestaetigten Fund, dass das bisherige _session_active einmal
        # gesetzt NIE wieder zurueckgesetzt wurde (jede Aeusserung fuer
        # den Rest des Prozesslaufs transkribiert haette).
        self.declare_parameter("wakeword_cooldown_s", 3.0)
        self.declare_parameter("wakeword_min_confidence", 0.5)
        self.declare_parameter("session_active_timeout_s", 20.0)
        self.declare_parameter("interaction_state_max_age_s", 3.0)

        # Entwicklungsauftrag 04-B, AP6, Abschnitt 5: ReSpeaker-Core-v2.0-
        # Konfiguration, nur relevant wenn source_kind=respeaker_core_v2.
        self.declare_parameter("respeaker_transport_kind", "mock")
        self.declare_parameter("respeaker_input_channels", 8)
        self.declare_parameter("respeaker_sample_rate_hz", 16000)
        self.declare_parameter("respeaker_device_name", "seeed-8mic-voicecard")
        self.declare_parameter("respeaker_host", "")
        self.declare_parameter("respeaker_user", "")
        self.declare_parameter("respeaker_password", "")
        self.declare_parameter("respeaker_block_duration_ms", 20)
        self.declare_parameter("respeaker_maximum_buffer_ms", 500.0)
        self.declare_parameter("respeaker_maximum_frame_age_ms", 200.0)
        self.declare_parameter("respeaker_backend_kind", "passthrough")
        self.declare_parameter("respeaker_microphone_channels", [0, 1, 2, 3, 4, 5])
        self.declare_parameter("respeaker_mic_spacing_m", 0.035)

        self.transcript_pub = self.create_publisher(String, "transcript", 10)
        self.command_pub = self.create_publisher(String, "voice_command", 10)
        self.source_ok_pub = self.create_publisher(Bool, "source_ok", 10)
        self.segment_duration_pub = self.create_publisher(Float32, "last_segment_duration", 10)
        self.sound_direction_pub = self.create_publisher(SoundDirection, "/audio/sound_direction", 10)
        self.wakeword_event_pub = self.create_publisher(WakewordEvent, "/audio/wakeword_event", 10)

        self.create_subscription(Bool, "/pepper_bridge/speaking", self._on_speaking, 10)
        self.half_duplex = HalfDuplexController(resume_delay_s=0.5)

        # Entwicklungsauftrag 04-B, AP6, Abschnitt 8: der tatsaechliche
        # Gespraechszustand kommt aus dem zentralen Supervisor
        # (/interaction_state), NICHT allein aus einem lokalen Flag --
        # fail-closed: solange nie/nicht mehr aktuell empfangen, wird
        # "Gespraech koennte aktiv sein" angenommen (blockiert ein neues
        # Wakeword-Ereignis eher, statt eines faelschlich waehrend einer
        # laufenden Interaktion auszuloesen).
        self._interaction_state_value = InteractionState.IDLE
        self._interaction_state_received_at = None
        self.create_subscription(UInt8, "/interaction_state", self._on_interaction_state, 10)

        self.wakeword = WakewordDetector(
            model_path=self.get_parameter("wakeword_model_path").value
        )
        self.wakeword_gate = WakewordGate(
            cooldown_s=self.get_parameter("wakeword_cooldown_s").value)
        self._session_active_until = None  # None = keine aktive Sitzung
        self._direction_lock = threading.Lock()
        self._latest_direction = (0.0, 0.0, False)  # (azimuth_rad, confidence, valid)

        if HAVE_CANCEL_SRV:
            self.cancel_client = self.create_client(CancelInteraction, "cancel_interaction")
        else:
            self.cancel_client = None

        self._whisper_model = None  # lazy geladen, damit Node schnell startet
        self._chunk_queue = queue.Queue(maxsize=200)
        self._stop_event = threading.Event()
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        self.create_timer(0.05, self._process_loop)

        self.get_logger().info(
            f"audio_node gestartet, Quelle={self.get_parameter('source_kind').value}, "
            f"Wakeword={'aktiv' if self.wakeword.enabled else 'deaktiviert (kein Modell)'}"
        )

    def _on_speaking(self, msg: Bool):
        self.half_duplex.on_speaking_changed(msg.data)

    def _on_interaction_state(self, msg: UInt8):
        self._interaction_state_value = msg.data
        self._interaction_state_received_at = time.monotonic()
        # Abschnitt 8: der zentrale Zustand ist massgeblich -- sobald der
        # Supervisor wieder IDLE meldet, ist eine vorher lokal gemerkte
        # Sitzung DEFINITIV vorbei, unabhaengig vom eigenen Timeout.
        if msg.data == InteractionState.IDLE:
            self._session_active_until = None

    def _conversation_active_for_gate(self) -> bool:
        """Fail-closed: unbekannt/veraltet -> "koennte aktiv sein"
        annehmen (blockiert ein neues Wakeword-Ereignis eher, statt
        eines faelschlich waehrend einer laufenden Interaktion
        auszuloesen)."""
        max_age = self.get_parameter("interaction_state_max_age_s").value
        if self._interaction_state_received_at is None:
            return True
        if (time.monotonic() - self._interaction_state_received_at) > max_age:
            return True
        return self._interaction_state_value != InteractionState.IDLE

    def _session_active(self) -> bool:
        if not self.wakeword.enabled:
            return True  # ohne Modell: immer "wach" (unveraendertes Verhalten)
        if self._session_active_until is None:
            return False
        return time.monotonic() < self._session_active_until

    def _build_directional_backend(self):
        from .directional_audio import GccPhatDelayAndSumBackend, PassthroughTestBackend

        kind = self.get_parameter("respeaker_backend_kind").value
        if kind == "gcc_phat":
            return GccPhatDelayAndSumBackend(
                microphone_channels=list(self.get_parameter("respeaker_microphone_channels").value),
                mic_spacing_m=self.get_parameter("respeaker_mic_spacing_m").value,
                sample_rate_hz=self.get_parameter("respeaker_sample_rate_hz").value,
            )
        return PassthroughTestBackend()

    def _build_source(self):
        kind = self.get_parameter("source_kind").value
        if kind == "file":
            return create_source("file", path=self.get_parameter("source_file_path").value, loop=True)
        if kind == "microphone":
            dev = self.get_parameter("microphone_device").value
            return create_source("microphone", device=None if dev < 0 else dev)
        if kind == "respeaker_core_v2":
            from .audio_source import build_respeaker_transport_from_config
            from .directional_audio import PassthroughTestBackend
            cfg = {
                "transport": self.get_parameter("respeaker_transport_kind").value,
                "input_channels": self.get_parameter("respeaker_input_channels").value,
                "device_name": self.get_parameter("respeaker_device_name").value,
                "respeaker_host": self.get_parameter("respeaker_host").value,
                "respeaker_user": self.get_parameter("respeaker_user").value,
                "respeaker_password": self.get_parameter("respeaker_password").value,
                "block_duration_ms": self.get_parameter("respeaker_block_duration_ms").value,
            }
            transport = build_respeaker_transport_from_config(cfg)
            return create_source(
                "respeaker_core_v2", transport=transport,
                directional_backend=self._build_directional_backend(),
                maximum_buffer_ms=self.get_parameter("respeaker_maximum_buffer_ms").value,
                maximum_frame_age_ms=self.get_parameter("respeaker_maximum_frame_age_ms").value,
                expected_channel_count=self.get_parameter("respeaker_input_channels").value,
            )
        if kind == "pepper_pulseaudio":
            host = self.get_parameter("pepper_host").value
            user = self.get_parameter("pepper_user").value
            password = self.get_parameter("pepper_password").value
            if not host or not password:
                # Fallback NUR wenn die Launch-Parameter fehlen (z.B. bei
                # direktem "ros2 run" ohne Launch-Datei/systemd-Umgebung) --
                # braucht apps/web im Python-Pfad (PEPPER_FLASK_WRAPPER_PATH),
                # was beim regulaeren systemd-Start NICHT der Fall ist. Vorher
                # lief dieser Import unbedingt und liess den Node bei jedem
                # regulaeren Start mit "No module named 'config'" abstuerzen,
                # obwohl Host/Passwort schon per Launch-Parameter da waren --
                # per Live-Test auf dem echten NUC gefunden.
                import config.config as _cfg
                host = host or _cfg.QI_HOST
                user = user or _cfg.QI_USER
                password = password or _cfg.QI_PW
            return create_source("pepper_pulseaudio", host=host, user=user, password=password)
        raise ValueError(f"Unbekannte source_kind: {kind}")

    def _publish_sound_direction_if_available(self, source):
        """Nur ReSpeakerCoreV2Source fuehrt Diagnose-Attribute
        (last_azimuth_rad/last_doa_confidence/last_direction_valid) --
        andere Quellen (file/microphone/pepper_pulseaudio) haben keine
        Richtungsschaetzung, hasattr() statt isinstance() um keinen
        Zyklus-Import mit audio_source.py einzugehen."""
        if not hasattr(source, "last_azimuth_rad"):
            return
        with self._direction_lock:
            self._latest_direction = (
                source.last_azimuth_rad, source.last_doa_confidence, source.last_direction_valid,
            )
        msg = SoundDirection()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.azimuth_rad = float(source.last_azimuth_rad)
        msg.confidence = float(source.last_doa_confidence)
        msg.vad_active = bool(source.last_vad_active)
        msg.valid = bool(source.last_direction_valid)
        msg.backend = type(getattr(source, "_backend", None)).__name__
        msg.reason = source.last_backend_reason
        self.sound_direction_pub.publish(msg)

    def _capture_loop(self):
        """Laeuft in eigenem Thread (blockierende Reads). Automatische
        Wiederverbindung bei Ausfall der Quelle."""
        reconnect_delay = self.get_parameter("reconnect_delay_s").value
        while not self._stop_event.is_set():
            try:
                source = self._build_source()
                source.connect()
                self.source_ok_pub.publish(Bool(data=True))
                self.get_logger().info(f"Audioquelle '{source.name}' verbunden.")
                while not self._stop_event.is_set():
                    chunk = source.read_chunk()
                    self._publish_sound_direction_if_available(source)
                    try:
                        self._chunk_queue.put(chunk, timeout=1.0)
                    except queue.Full:
                        pass  # Verarbeitung haengt hinterher -- Chunk verwerfen statt blockieren
            except AudioSourceError as e:
                self.get_logger().warn(f"Audioquelle ausgefallen: {e} -- reconnect in {reconnect_delay}s")
                self.source_ok_pub.publish(Bool(data=False))
                try:
                    self._chunk_queue.put(None, timeout=1.0)  # Sentinel: Segmenter soll flushen
                except queue.Full:
                    pass
                time.sleep(reconnect_delay)
            except Exception as e:
                self.get_logger().error(f"Unerwarteter Fehler in Audio-Capture: {e}")
                self.source_ok_pub.publish(Bool(data=False))
                time.sleep(reconnect_delay)

    def _get_whisper(self):
        if self._whisper_model is None:
            from faster_whisper import WhisperModel
            model_size = self.get_parameter("whisper_model").value
            self.get_logger().info(f"Lade Whisper-Modell '{model_size}' ...")
            self._whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        return self._whisper_model

    def _process_loop(self):
        if not hasattr(self, "_segmenter"):
            backend = create_vad_backend(prefer_silero=True)
            self.get_logger().info(f"VAD-Backend: {backend.name}")
            self._segmenter = UtteranceSegmenter(
                backend=backend,
                ring_buffer=RingBuffer(max_duration_s=30.0),
                threshold=self.get_parameter("vad_threshold").value,
                preroll_s=self.get_parameter("preroll_s").value,
                min_speech_s=self.get_parameter("min_speech_s").value,
                silence_end_s=self.get_parameter("silence_end_s").value,
                max_utterance_s=self.get_parameter("max_utterance_s").value,
                chunk_ms=CHUNK_MS,
            )

        # Alle wartenden Chunks in diesem Tick abarbeiten
        while True:
            try:
                chunk = self._chunk_queue.get_nowait()
            except queue.Empty:
                break

            if chunk is None:
                # Sentinel von _capture_loop: Quelle abgebrochen/beendet.
                # Laufende Aeusserung nicht verlieren, sondern abschliessen.
                utterance = self._segmenter.flush()
                if utterance is not None:
                    self._handle_utterance(utterance)
                continue

            if not self.half_duplex.should_listen():
                continue  # Pepper spricht gerade -- nicht selbst transkribieren

            utterance = self._segmenter.process_chunk(chunk)
            if utterance is not None:
                self._handle_utterance(utterance)

    def _handle_utterance(self, utterance_pcm: bytes):
        import numpy as np
        duration_s = len(utterance_pcm) / 2 / 16000
        self.segment_duration_pub.publish(Float32(data=duration_s))

        if self.wakeword.enabled and not self._session_active():
            detected = self.wakeword.detect(utterance_pcm)
            with self._direction_lock:
                azimuth_rad, direction_confidence, direction_valid = self._latest_direction
            event = self.wakeword_gate.evaluate(
                keyword_detected=detected,
                keyword_confidence=1.0 if detected else 0.0,  # WakewordDetector liefert aktuell nur bool
                conversation_active=self._conversation_active_for_gate(),
                azimuth_rad=azimuth_rad,
                direction_confidence=direction_confidence,
                direction_valid=direction_valid,
                min_keyword_confidence=self.get_parameter("wakeword_min_confidence").value,
            )
            if event is not None:
                timeout_s = self.get_parameter("session_active_timeout_s").value
                self._session_active_until = time.monotonic() + timeout_s
                self.get_logger().info(
                    f"Wakeword erkannt (event_id={event.event_id}), Sitzung fuer "
                    f"{timeout_s:.0f}s aktiv."
                )
                msg = WakewordEvent()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.event_id = event.event_id
                msg.keyword = event.keyword
                msg.keyword_confidence = event.keyword_confidence
                msg.azimuth_rad = event.azimuth_rad
                msg.direction_confidence = event.direction_confidence
                msg.direction_valid = event.direction_valid
                self.wakeword_event_pub.publish(msg)
            return  # ohne erzeugtes Ereignis: Aeusserung verwerfen (kein Transkript im Idle-Modus)

        audio = np.frombuffer(utterance_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            model = self._get_whisper()
            segments, info = model.transcribe(
                audio, language=self.get_parameter("whisper_language").value,
                beam_size=1, vad_filter=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            self.get_logger().error(f"Whisper-Transkription fehlgeschlagen: {e}")
            return

        if not text:
            return

        self.get_logger().info(f"Transkript: {text}")

        command = detect_command(text)
        if command:
            self.command_pub.publish(String(data=command))
            if is_hard_stop(command) and self.cancel_client is not None:
                if self.cancel_client.service_is_ready():
                    req = CancelInteraction.Request()
                    req.reason = f"voice_command:{command}"
                    self.cancel_client.call_async(req)
                else:
                    self.get_logger().warn(
                        "cancel_interaction-Service nicht verfuegbar "
                        "(ihk_pepper_interaction laeuft noch nicht?)"
                    )

        self.transcript_pub.publish(String(data=text))

    def destroy_node(self):
        self._stop_event.set()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AudioNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
