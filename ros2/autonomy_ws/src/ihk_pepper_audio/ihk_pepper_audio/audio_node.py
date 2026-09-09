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
from builtin_interfaces.msg import Time as TimeMsg
from rclpy.node import Node
from std_msgs.msg import String, Bool, Float32, UInt8

from ihk_pepper_interaction.interaction_state import InteractionState
from ihk_pepper_interfaces.msg import AudioFocusState, SoundDirection, WakewordEvent

from .audio_source import create_source, AudioSourceError, CHUNK_MS
from .direction_sample_buffer import DirectionSampleBuffer, TimedDirectionSample
from .ring_buffer import RingBuffer
from .vad_segmenter import UtteranceSegmenter, create_vad_backend
from .half_duplex import HalfDuplexController
from .cancel_words import detect_command, is_hard_stop
from .wakeword import WakewordDetector
from .wakeword_gate import WakewordGate

# Entwicklungsauftrag 04-B, AP6.1, Abschnitt 13.
ACTIVATION_MODE_WAKEWORD_REQUIRED = "wakeword_required"
ACTIVATION_MODE_PUSH_TO_TALK = "push_to_talk"
ACTIVATION_MODE_CONTINUOUS_DEVELOPMENT = "continuous_development"
VALID_ACTIVATION_MODES = (
    ACTIVATION_MODE_WAKEWORD_REQUIRED, ACTIVATION_MODE_PUSH_TO_TALK,
    ACTIVATION_MODE_CONTINUOUS_DEVELOPMENT,
)


def _ns_to_stamp(ns: int) -> TimeMsg:
    stamp = TimeMsg()
    stamp.sec = int(ns // 1_000_000_000)
    stamp.nanosec = int(ns % 1_000_000_000)
    return stamp

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

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 13: expliziter
        # Aktivierungsmodus ersetzt das bisherige implizite
        # "if not self.wakeword.enabled: return True" -- das war ein
        # bestaetigter Fail-Open-Fund (ein fehlendes Modell fuehrte zu
        # DAUERHAFTER Transkription, nicht zu keiner Sitzung).
        # production_mode (analog zu gesture_memory_node.py) sperrt
        # continuous_development serverseitig, unabhaengig vom Launch.
        self.declare_parameter("activation_mode", ACTIVATION_MODE_WAKEWORD_REQUIRED)
        self.declare_parameter("production_mode", False)

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: begrenzter
        # Zeitpuffer fuer Richtungsproben statt einer einzelnen globalen
        # "letzte Richtung"-Variable.
        self.declare_parameter("direction_buffer_max_duration_s", 3.0)
        self.declare_parameter("direction_window_margin_s", 0.5)
        self.declare_parameter("direction_min_confidence_for_wakeword", 0.0)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.3: der von
        # audio_node.py veroeffentlichte Winkel ist IMMER relativ zum
        # Mikrofonarray selbst -- der Frame-Name macht das explizit
        # (Transformation nach base_link passiert erst im separaten
        # sound_direction_transform_node.py, siehe AP6.1 Commit 3).
        self.declare_parameter("respeaker_frame_id", "respeaker_link")

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
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: echte Kanal-
        # geometrie fuer gezieltes Delay-and-Sum-Steering (statt nur des
        # Referenzpaar-Abstands) -- drei parallele Arrays statt
        # verschachtelter Structs (ROS2-Parameter kennen keine Listen von
        # Objekten). Alle drei leer (Default) = keine Geometrie
        # konfiguriert, Backend faellt fail-closed auf das alte,
        # ungerichtete Delay-and-Sum zurueck (siehe directional_audio.py).
        self.declare_parameter("respeaker_mic_geometry_channels", [])
        self.declare_parameter("respeaker_mic_geometry_x_m", [])
        self.declare_parameter("respeaker_mic_geometry_y_m", [])
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13: siehe
        # DirectionalAudioBackend.provides_unambiguous_direction-Doku --
        # eine Zwei-Mikrofon-GCC-PHAT-Halbebenenschaetzung darf NIE ohne
        # explizite, in production_mode gesperrte Bestaetigung eine
        # Kopfbewegung ausloesen.
        self.declare_parameter("allow_ambiguous_direction_for_head_orientation", False)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: deutlich groesser
        # als audio_focus_node.py's Publikationsintervall (0.2s) -- ein
        # einzelner verpasster Tick darf das Steering nicht sofort
        # abbrechen, ein ausbleibender audio_focus_node (Absturz, Netz)
        # aber sehr wohl.
        self.declare_parameter("focus_target_freshness_margin_s", 1.0)

        activation_mode = self.get_parameter("activation_mode").value
        if activation_mode not in VALID_ACTIVATION_MODES:
            raise RuntimeError(
                f"audio_node: unbekannter activation_mode '{activation_mode}'. "
                f"Erlaubt: {', '.join(VALID_ACTIVATION_MODES)}."
            )
        if (self.get_parameter("production_mode").value
                and activation_mode == ACTIVATION_MODE_CONTINUOUS_DEVELOPMENT):
            raise RuntimeError(
                "audio_node: activation_mode=continuous_development ist mit "
                "production_mode=true gesperrt (Entwicklungsauftrag 04-B, AP6.1, "
                "Abschnitt 13) -- niemals unbeaufsichtigtes Dauerhoeren in Produktion."
            )
        if (self.get_parameter("production_mode").value
                and self.get_parameter("allow_ambiguous_direction_for_head_orientation").value):
            raise RuntimeError(
                "audio_node: allow_ambiguous_direction_for_head_orientation=true ist mit "
                "production_mode=true gesperrt (Entwicklungsauftrag 04-B, AP6.1, "
                "Abschnitt 5/13) -- eine front/back-mehrdeutige Zwei-Mikrofon-Schaetzung "
                "darf in Produktion nie als sichere Grundlage fuer eine Kopfbewegung gelten."
            )

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13: konservativer
        # Default, bis der erste Richtungssample eines Backends mit
        # provides_unambiguous_direction=True eingetroffen ist (siehe
        # _publish_sound_direction_if_available()) -- kein bekannter
        # Backend-Typ bedeutet KEINE sichere 360-Grad-Peilung.
        self._direction_source_unambiguous = False
        self._current_backend = None

        self.transcript_pub = self.create_publisher(String, "transcript", 10)
        self.command_pub = self.create_publisher(String, "voice_command", 10)
        self.source_ok_pub = self.create_publisher(Bool, "source_ok", 10)
        self.segment_duration_pub = self.create_publisher(Float32, "last_segment_duration", 10)
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4/12: strikte Trennung
        # RAW (dieser Node, IMMER frame_id=respeaker_frame_id, roh relativ
        # zum Mikrofonarray) vs. KANONISCH (nur sound_direction_transform_node.py
        # publiziert das, IMMER frame_id=base_frame, siehe dort) -- kein
        # anderer Node darf je auf die kanonischen Topics publizieren, und
        # BT/audio_focus_node.py duerfen NUR die kanonischen abonnieren.
        self.sound_direction_pub = self.create_publisher(SoundDirection, "/audio/sound_direction_raw", 10)
        self.wakeword_event_pub = self.create_publisher(WakewordEvent, "/audio/wakeword_event_raw", 10)

        self.create_subscription(Bool, "/pepper_bridge/speaking", self._on_speaking, 10)
        self.half_duplex = HalfDuplexController(resume_delay_s=0.5)

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 13: expliziter
        # Befehl fuer activation_mode=push_to_talk -- ein Tablet-/ROS2-
        # Aufruf setzt dieses Topic, sonst bleibt die Sitzung inaktiv.
        self._push_to_talk_active = False
        self.create_subscription(
            Bool, "/audio/push_to_talk_active", self._on_push_to_talk, 10)

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

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: bestaetigter Fund
        # -- bislang gab es KEINEN Weg, das reale, bestaetigte Fokus-Ziel
        # (audio_focus_node.py, AudioFocusStateMachine) an das aktive
        # Backend weiterzugeben; jeder Beamforming-Pfad verarbeitete
        # strukturell nur den lautesten/gemessenen Sprecher. Steuert das
        # Backend NUR waehrend eines bestaetigten Gespraechsfokus an --
        # ein lauterer/anderer Sprecher kann NIE selbst zum neuen Ziel
        # werden (das entscheidet ausschliesslich audio_focus.py/
        # audiovisual_association.py, nicht dieser Node).
        self.create_subscription(AudioFocusState, "/audio/focus_state", self._on_focus_state, 10)

        self.wakeword = WakewordDetector(
            model_path=self.get_parameter("wakeword_model_path").value
        )
        self.wakeword_gate = WakewordGate(
            cooldown_s=self.get_parameter("wakeword_cooldown_s").value)
        self._session_active_until = None  # None = keine aktive Sitzung
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: ersetzt die
        # vorherige einzelne "letzte Richtung"-Variable durch einen
        # zeitindizierten Puffer -- siehe direction_sample_buffer.py.
        # _direction_lock schuetzt ihn: push() laeuft im Capture-Thread,
        # select_for_window() im ROS-Executor-Thread (Timer-Callback).
        self._direction_lock = threading.Lock()
        self._direction_buffer = DirectionSampleBuffer(
            max_duration_s=self.get_parameter("direction_buffer_max_duration_s").value)

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
            f"activation_mode={activation_mode}, "
            f"Wakeword={'aktiv' if self.wakeword.enabled else 'deaktiviert (kein Modell)'}"
        )
        if activation_mode == ACTIVATION_MODE_WAKEWORD_REQUIRED and not self.wakeword.enabled:
            self.get_logger().warn(
                "activation_mode=wakeword_required, aber KEIN Wakeword-Modell geladen -- "
                "es wird NIEMALS eine Sitzung aktiv (fail-closed, kein Transkript im "
                "Idle-Modus). Siehe wakeword_model_path."
            )

    def _on_speaking(self, msg: Bool):
        self.half_duplex.on_speaking_changed(msg.data)

    def _on_push_to_talk(self, msg: Bool):
        self._push_to_talk_active = msg.data

    def _on_focus_state(self, msg: AudioFocusState):
        """Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: steuert das
        aktive Backend auf das von audio_focus_node.py bestaetigte
        Fokus-Ziel -- NUR waehrend CONVERSATION_FOCUS/PEPPER_SPEAKING
        UND msg.valid. Jeder andere Zustand (IDLE_WIDE, AUDIO_DEGRADED,
        RETURNING_TO_IDLE, ...) loescht ein evtl. gesetztes Ziel sofort
        (kein stilles Weitersteuern auf eine verlorene Person).

        valid_until wird bewusst HIER (mit der eigenen monotone Uhr
        dieses Prozesses) berechnet, nicht aus dem Nachrichteninhalt
        uebernommen -- verlaesst sich nicht auf eine geteilte
        Uhren-Epoche zwischen getrennten ROS-Prozessen. Bleibt das
        naechste Update laenger als die Marge aus, faellt das Backend
        von selbst auf ungerichtetes Verhalten zurueck (siehe
        directional_audio.py::_active_focus_azimuth)."""
        backend = self._current_backend
        if backend is None or not hasattr(backend, "set_focus_target"):
            return
        if msg.valid and msg.mode in ("CONVERSATION_FOCUS", "PEPPER_SPEAKING"):
            margin_s = self.get_parameter("focus_target_freshness_margin_s").value
            backend.set_focus_target(msg.target_azimuth_rad, time.monotonic() + margin_s)
        else:
            backend.clear_focus_target()

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
        """Reiner Timeout-Check -- NUR im activation_mode=wakeword_required
        aussagekraeftig (siehe _should_process_utterance()). Bewusst KEIN
        "ohne Modell -> immer wach" mehr -- das war der bestaetigte
        Fail-Open-Fund aus Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.4."""
        if self._session_active_until is None:
            return False
        return time.monotonic() < self._session_active_until

    def _should_process_utterance(self) -> bool:
        """Ersetzt die bisherige, direkt an self.wakeword.enabled gekoppelte
        Kurzschluss-Logik (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.4/13):
        vorher fuehrte ein fehlendes Wakeword-Modell dazu, dass JEDE
        Aeusserung transkribiert wurde (fail-open). Jetzt entscheidet
        ausschliesslich der explizite activation_mode -- niemals ein
        impliziter Fallback."""
        mode = self.get_parameter("activation_mode").value
        if mode == ACTIVATION_MODE_CONTINUOUS_DEVELOPMENT:
            return True
        if mode == ACTIVATION_MODE_PUSH_TO_TALK:
            return self._push_to_talk_active
        # wakeword_required (sicherer Standard): OHNE geladenes Modell
        # NIE eine Sitzung -- kein Erkennungsversuch kann je gelingen,
        # also darf auch nie transkribiert werden.
        if not self.wakeword.enabled:
            return False
        return self._session_active()

    def _build_microphone_geometry(self):
        """None, wenn die drei parallelen Arrays nicht UEBEREINSTIMMEND
        (gleiche Laenge, nicht leer) konfiguriert sind -- fail-closed auf
        "keine Geometrie" statt eine Teilkonfiguration zu erraten
        (Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5)."""
        from .directional_audio import MicrophoneGeometry

        channels = list(self.get_parameter("respeaker_mic_geometry_channels").value)
        xs = list(self.get_parameter("respeaker_mic_geometry_x_m").value)
        ys = list(self.get_parameter("respeaker_mic_geometry_y_m").value)
        if not channels or not (len(channels) == len(xs) == len(ys)):
            if channels or xs or ys:
                self.get_logger().warn(
                    "respeaker_mic_geometry_*-Parameter unvollstaendig/inkonsistent "
                    f"(channels={len(channels)}, x={len(xs)}, y={len(ys)}) -- "
                    "Geometrie-Steering bleibt deaktiviert."
                )
            return None
        return [MicrophoneGeometry(channel=int(c), x_m=float(x), y_m=float(y))
                for c, x, y in zip(channels, xs, ys)]

    def _build_directional_backend(self):
        from .directional_audio import GccPhatDelayAndSumBackend, PassthroughTestBackend

        kind = self.get_parameter("respeaker_backend_kind").value
        if kind == "gcc_phat":
            return GccPhatDelayAndSumBackend(
                microphone_channels=list(self.get_parameter("respeaker_microphone_channels").value),
                mic_spacing_m=self.get_parameter("respeaker_mic_spacing_m").value,
                sample_rate_hz=self.get_parameter("respeaker_sample_rate_hz").value,
                microphone_geometry=self._build_microphone_geometry(),
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
        Zyklus-Import mit audio_source.py einzugehen.

        Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.3/5: jede Probe
        bekommt ihren EIGENEN Zeitstempel (ROS- und monotone Uhr) und
        einen expliziten frame_id -- landet zusaetzlich zum Topic im
        DirectionSampleBuffer, damit ein spaeteres Wakeword-Ereignis
        gezielt aus seinem eigenen Aeusserungsfenster waehlen kann,
        statt blind die "letzte" Richtung zu uebernehmen."""
        if not hasattr(source, "last_azimuth_rad"):
            return
        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13: einfache
        # Bool-Zuweisung, kein Lock noetig (gleiches, bereits etabliertes
        # Muster wie self._push_to_talk_active -- eine einzelne
        # Attributzuweisung ist unter der GIL atomar genug fuer dieses
        # nicht-kritische Cross-Thread-Flag).
        self._direction_source_unambiguous = bool(
            getattr(getattr(source, "_backend", None), "provides_unambiguous_direction", False))
        now_ns = self.get_clock().now().nanoseconds
        frame_id = self.get_parameter("respeaker_frame_id").value
        sample = TimedDirectionSample(
            ros_stamp_ns=now_ns,
            monotonic_stamp_s=time.monotonic(),
            frame_id=frame_id,
            azimuth_rad=float(source.last_azimuth_rad),
            confidence=float(source.last_doa_confidence),
            valid=bool(source.last_direction_valid),
        )
        with self._direction_lock:
            self._direction_buffer.push(sample)
        msg = SoundDirection()
        msg.header.stamp = _ns_to_stamp(now_ns)
        msg.header.frame_id = frame_id
        msg.azimuth_rad = sample.azimuth_rad
        msg.confidence = sample.confidence
        msg.vad_active = bool(source.last_vad_active)
        msg.valid = sample.valid
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
                # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5: Referenz
                # auf das aktuell aktive Backend fuer den ROS-Callback-
                # Thread (_on_focus_state()) -- derselbe Bool-Zuweisungs-
                # Grund wie bei _direction_source_unambiguous oben.
                self._current_backend = getattr(source, "_backend", None)
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

    def _try_wakeword_activation(self, utterance_pcm: bytes, utterance_end_monotonic_s: float,
                                  duration_s: float):
        """Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/8: waehlt die
        Richtungsprobe(n) aus GENAU dem Zeitfenster dieser Aeusserung
        (nicht die zufaellig "letzte" Probe) und traegt den ECHTEN
        Messzeitpunkt in WakewordEvent.header.stamp ein -- nicht den
        spaeteren ROS-Empfangszeitpunkt dieses Callbacks."""
        detected = self.wakeword.detect(utterance_pcm)

        margin_s = self.get_parameter("direction_window_margin_s").value
        utterance_start_monotonic_s = utterance_end_monotonic_s - duration_s
        with self._direction_lock:
            direction_sample = self._direction_buffer.select_for_window(
                utterance_start_monotonic_s - margin_s, utterance_end_monotonic_s + margin_s,
                min_confidence=self.get_parameter("direction_min_confidence_for_wakeword").value,
            )

        if direction_sample is not None:
            azimuth_rad = direction_sample.azimuth_rad
            direction_confidence = direction_sample.confidence
            direction_valid = True
            event_stamp_ns = direction_sample.ros_stamp_ns
        else:
            # Keine passende Probe im Aeusserungsfenster -- ehrlich als
            # ungueltig melden, NIE eine Richtung erfinden. Der
            # Zeitstempel selbst ist hier irrelevant (direction_valid
            # bleibt False, WaitForFreshWakeword im Behavior Tree
            # verlangt explizit direction_valid==true).
            azimuth_rad = 0.0
            direction_confidence = 0.0
            direction_valid = False
            event_stamp_ns = self.get_clock().now().nanoseconds

        # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 5/13: eine
        # front/back-mehrdeutige Zwei-Mikrofon-Schaetzung (z.B. GCC-PHAT)
        # darf NIE ohne explizite, in production_mode gesperrte
        # Bestaetigung eine Kopfbewegung ausloesen -- direction_valid
        # wird hier ehrlich zurueckgesetzt, NICHT die Richtung selbst
        # veraendert (WaitForFreshWakeword/OrientHeadToSound verlangen
        # direction_valid==true, siehe Behavior Tree).
        if direction_valid and not self._direction_source_unambiguous:
            if not self.get_parameter("allow_ambiguous_direction_for_head_orientation").value:
                direction_valid = False

        event = self.wakeword_gate.evaluate(
            keyword_detected=detected,
            keyword_confidence=1.0 if detected else 0.0,  # WakewordDetector liefert aktuell nur bool
            conversation_active=self._conversation_active_for_gate(),
            azimuth_rad=azimuth_rad,
            direction_confidence=direction_confidence,
            direction_valid=direction_valid,
            min_keyword_confidence=self.get_parameter("wakeword_min_confidence").value,
        )
        if event is None:
            return
        timeout_s = self.get_parameter("session_active_timeout_s").value
        self._session_active_until = time.monotonic() + timeout_s
        self.get_logger().info(
            f"Wakeword erkannt (event_id={event.event_id}), Sitzung fuer "
            f"{timeout_s:.0f}s aktiv."
        )
        msg = WakewordEvent()
        msg.header.stamp = _ns_to_stamp(event_stamp_ns)
        msg.header.frame_id = self.get_parameter("respeaker_frame_id").value
        msg.event_id = event.event_id
        msg.keyword = event.keyword
        msg.keyword_confidence = event.keyword_confidence
        msg.azimuth_rad = event.azimuth_rad
        msg.direction_confidence = event.direction_confidence
        msg.direction_valid = event.direction_valid
        self.wakeword_event_pub.publish(msg)

    def _handle_utterance(self, utterance_pcm: bytes):
        import numpy as np
        now_s = time.monotonic()
        duration_s = len(utterance_pcm) / 2 / 16000
        self.segment_duration_pub.publish(Float32(data=duration_s))

        if not self._should_process_utterance():
            # Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.4/13: nur im
            # wakeword_required-Modus MIT geladenem Modell lohnt ein
            # Erkennungsversuch ueberhaupt -- in jedem anderen "nicht
            # aktiv"-Fall (push_to_talk ohne Freigabe, wakeword_required
            # ohne Modell) wird die Aeusserung OHNE Erkennungsversuch
            # verworfen, nie stillschweigend transkribiert.
            if (self.get_parameter("activation_mode").value == ACTIVATION_MODE_WAKEWORD_REQUIRED
                    and self.wakeword.enabled):
                self._try_wakeword_activation(utterance_pcm, now_s, duration_s)
            return

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
