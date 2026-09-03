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
from std_msgs.msg import String, Bool, Float32

from .audio_source import create_source, AudioSourceError, CHUNK_MS
from .ring_buffer import RingBuffer
from .vad_segmenter import UtteranceSegmenter, create_vad_backend
from .half_duplex import HalfDuplexController
from .cancel_words import detect_command, is_hard_stop
from .wakeword import WakewordDetector

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

        self.transcript_pub = self.create_publisher(String, "transcript", 10)
        self.command_pub = self.create_publisher(String, "voice_command", 10)
        self.source_ok_pub = self.create_publisher(Bool, "source_ok", 10)
        self.segment_duration_pub = self.create_publisher(Float32, "last_segment_duration", 10)

        self.create_subscription(Bool, "/pepper_bridge/speaking", self._on_speaking, 10)
        self.half_duplex = HalfDuplexController(resume_delay_s=0.5)

        self.wakeword = WakewordDetector(
            model_path=self.get_parameter("wakeword_model_path").value
        )
        self._session_active = not self.wakeword.enabled  # ohne Modell: immer "wach"

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

    def _build_source(self):
        kind = self.get_parameter("source_kind").value
        if kind == "file":
            return create_source("file", path=self.get_parameter("source_file_path").value, loop=True)
        if kind == "microphone":
            dev = self.get_parameter("microphone_device").value
            return create_source("microphone", device=None if dev < 0 else dev)
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

        if self.wakeword.enabled and not self._session_active:
            if self.wakeword.detect(utterance_pcm):
                self._session_active = True
                self.get_logger().info("Wakeword erkannt, Sitzung aktiv.")
            return  # ohne erkanntes Wakeword: Aeusserung verwerfen

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
