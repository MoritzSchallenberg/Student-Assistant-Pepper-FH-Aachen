#!/usr/bin/env python3
"""
Hoer-Pipeline v1: abonniert Peppers Audio-Topic (/audio,
naoqi_bridge_msgs/AudioBuffer), sammelt ein paar Sekunden PCM-Audio,
schickt den Block durch Whisper (lokal, CPU) und gibt den erkannten
Text auf der Konsole aus.

Naechster Ausbauschritt (noch nicht drin): den erkannten Text an
AnythingLLM schicken (llm/anythingllm.py) und die Antwort per
pepper/qicli.py aussprechen lassen -> damit waere der volle Kreis
"hoeren -> verstehen -> antworten" fertig.

Nutzung:
    source /opt/ros/jazzy/setup.bash
    source venv/bin/activate
    python3 stt/listen.py --window 5 --model small --lang de
"""
import sys
import time
import argparse
import numpy as np

import rclpy
from rclpy.node import Node
from naoqi_bridge_msgs.msg import AudioBuffer

from faster_whisper import WhisperModel


class Listener(Node):
    def __init__(self, window_s: float, model_size: str, language: str):
        super().__init__("pepper_listener")
        self.window_s = window_s
        self.language = language

        self.get_logger().info(f"Lade Whisper-Modell '{model_size}' (CPU, int8) ...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.get_logger().info("Modell geladen.")

        self.buffer = []          # Liste von int16-numpy-Arrays (mono)
        self.buffer_samples = 0
        self.sample_rate = None   # aus der ersten Nachricht uebernommen

        self.sub = self.create_subscription(AudioBuffer, "/audio", self.on_audio, 10)
        self.get_logger().info("Warte auf Audio auf /audio ...")

    def on_audio(self, msg: AudioBuffer):
        if self.sample_rate is None:
            self.sample_rate = msg.frequency
            self.get_logger().info(f"Erste Audio-Nachricht: {msg.frequency} Hz, "
                                    f"{len(msg.channel_map)} Kanal/Kanaele")

        n_channels = max(1, len(msg.channel_map))
        data = np.array(msg.data, dtype=np.int16)
        if n_channels > 1:
            # interlaced -> auf einen Kanal reduzieren (Mittelwert)
            usable_len = (len(data) // n_channels) * n_channels
            data = data[:usable_len].reshape(-1, n_channels).mean(axis=1).astype(np.int16)

        self.buffer.append(data)
        self.buffer_samples += len(data)

        if self.sample_rate and self.buffer_samples >= self.window_s * self.sample_rate:
            self.transcribe_buffer()

    def transcribe_buffer(self):
        audio = np.concatenate(self.buffer)
        self.buffer = []
        self.buffer_samples = 0

        # int16 -> float32 in [-1, 1], wie Whisper es erwartet
        audio_f32 = audio.astype(np.float32) / 32768.0

        t0 = time.time()
        segments, info = self.model.transcribe(
            audio_f32, language=self.language, beam_size=1, vad_filter=True
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        dt = time.time() - t0

        if text:
            print(f"\n>>> GEHOERT: {text}   ({dt:.1f}s Verarbeitung)\n")
        else:
            self.get_logger().info(f"(Stille/kein Text erkannt, {dt:.1f}s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=float, default=5.0, help="Sekunden Audio pro Erkennungs-Block")
    parser.add_argument("--model", default="small", help="Whisper-Modellgroesse: tiny/base/small/medium")
    parser.add_argument("--lang", default="de", help="Sprachcode, z.B. de/en")
    args = parser.parse_args()

    rclpy.init()
    node = Listener(window_s=args.window, model_size=args.model, language=args.lang)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
