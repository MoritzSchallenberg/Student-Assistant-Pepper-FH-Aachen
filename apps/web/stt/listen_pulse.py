#!/usr/bin/env python3
"""
Hoer-Pipeline v2 (funktionierender Weg): streamt rohes PCM-Audio live per
SSH von Peppers PulseAudio-Mikrofonquelle ("microphone"), erkennt per
einfacher Lautstaerke-Schwelle (RMS) automatisch, wann die Person zu reden
aufhoert (Sprechpause), und transkribiert dann sofort per Whisper (lokal,
CPU) -- ohne auf ein festes Zeitfenster zu warten.

Hintergrund: naoqi_driver2 (/audio Topic) und ALAudioDevice.
startMicrophonesRecording liefern auf diesem Pepper KEINE Daten (siehe
docs/STATUS.md). PulseAudio ("microphone"-Source, 4ch/48kHz) funktioniert aber
zuverlaessig -- dieser Weg nutzt das direkt per SSH-Stream.

Naechster Schritt (noch nicht drin): erkannten Text an AnythingLLM schicken
(llm/anythingllm.py) und Antwort per qicli.say() aussprechen lassen.

Nutzung:
    source venv/bin/activate
    python3 stt/listen_pulse.py --model small --lang de
"""
import os
import sys
import time
import argparse
import numpy as np
import paramiko

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from faster_whisper import WhisperModel
import config.config as _cfg

SAMPLE_RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * (CHUNK_MS / 1000.0)) * 2  # int16 mono

SILENCE_RMS_THRESHOLD = 400      # anpassen je nach Mikrofon-Empfindlichkeit/Raum
SILENCE_CHUNKS_TO_END = 7        # ~0.7s Stille = Ende der Aeusserung
MIN_SPEECH_CHUNKS = 4            # ~0.4s Mindestlaenge, um Rauschen zu ignorieren
MAX_UTTERANCE_CHUNKS = 150       # ~15s Sicherheitslimit


def rms(chunk_bytes: bytes) -> float:
    samples = np.frombuffer(chunk_bytes, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small")
    parser.add_argument("--lang", default="de")
    parser.add_argument("--host", default=_cfg.QI_HOST)
    parser.add_argument("--user", default=_cfg.QI_USER)
    parser.add_argument("--password", default=_cfg.QI_PW)
    parser.add_argument("--threshold", type=float, default=SILENCE_RMS_THRESHOLD)
    args = parser.parse_args()

    print(f"Lade Whisper-Modell '{args.model}' (CPU, int8) ...")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print("Modell geladen. Verbinde SSH-Audio-Stream ...")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=args.host, username=args.user, password=args.password, timeout=10)
    except paramiko.ssh_exception.BadAuthenticationType as e:
        if "keyboard-interactive" not in e.allowed_types:
            raise
        transport = client.get_transport()
        transport.auth_interactive(args.user, lambda t, i, p: [args.password for _ in p])

    cmd = (
        f"parecord --device=microphone --raw --format=s16le "
        f"--rate={SAMPLE_RATE} --channels=1 -"
    )
    stdin, stdout, stderr = client.exec_command(cmd)
    print("Stream laeuft. Rede einfach los -- ich erkenne automatisch, wann du fertig bist.\n")

    speech_chunks = []
    silence_run = 0
    in_speech = False

    try:
        while True:
            chunk = stdout.read(CHUNK_BYTES)
            if not chunk:
                print("Stream beendet (Verbindung verloren?)")
                break

            level = rms(chunk)
            is_loud = level > args.threshold
            if int(time.time() * 2) % 2 == 0:
                print(f"\rPegel: {level:7.1f}  (Schwelle: {args.threshold})   ", end="", flush=True)

            if is_loud:
                speech_chunks.append(chunk)
                silence_run = 0
                if not in_speech and len(speech_chunks) >= MIN_SPEECH_CHUNKS:
                    in_speech = True
                    print("... erkenne Sprache ...")
            elif in_speech:
                speech_chunks.append(chunk)  # kurze Pausen mit aufnehmen
                silence_run += 1
                if silence_run >= SILENCE_CHUNKS_TO_END or len(speech_chunks) >= MAX_UTTERANCE_CHUNKS:
                    # Aeusserung fertig -> transkribieren
                    audio_bytes = b"".join(speech_chunks)
                    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                    t0 = time.time()
                    segments, info = model.transcribe(audio, language=args.lang, beam_size=1, vad_filter=False)
                    text = " ".join(s.text.strip() for s in segments).strip()
                    dt = time.time() - t0
                    if text:
                        print(f"\n>>> GEHOERT: {text}   ({dt:.2f}s)\n")
                    else:
                        print(f"(kein Text erkannt, {dt:.2f}s)")
                    speech_chunks = []
                    silence_run = 0
                    in_speech = False
            else:
                speech_chunks = []  # noch keine Sprache erkannt, Puffer klein halten

    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
