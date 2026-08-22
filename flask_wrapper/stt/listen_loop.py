#!/usr/bin/env python3
"""
Hoer-Pipeline v3 (robuste, getestete Variante): nimmt wiederholt kurze
WAV-Dateien per PulseAudio auf Pepper auf (bewiesen funktionierender Weg,
siehe listen_pulse.py-Kommentar/STATUS.md), holt sie per SFTP, transkribiert
per Whisper und gibt den Text aus. Kein echtes VAD/Streaming (das haengt
sich in listen_pulse.py momentan auf -- offener TODO), aber zuverlaessig
und mit kurzer Verzoegerung (Fenstergroesse Sekunden).

Naechster Schritt: den erkannten Text an AnythingLLM schicken und die
Antwort per qicli.say() aussprechen -> voller Kreis.

Nutzung:
    source venv/bin/activate
    python3 stt/listen_loop.py --window 3 --model small --lang de
"""
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pepper.qicli import qicli
from faster_whisper import WhisperModel
import config.config as _cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=float, default=3.0, help="Sekunden pro Aufnahme-Fenster")
    parser.add_argument("--model", default="small")
    parser.add_argument("--lang", default="de")
    parser.add_argument("--host", default=_cfg.QI_HOST)
    parser.add_argument("--user", default=_cfg.QI_USER)
    parser.add_argument("--password", default=_cfg.QI_PW)
    args = parser.parse_args()

    print(f"Lade Whisper-Modell '{args.model}' (CPU, int8) ...")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print("Modell geladen.")

    c = qicli(args.host, args.user, args.password)
    c.connect()
    sftp = c.client.open_sftp()

    remote_path = "/home/nao/loop_rec.wav"
    local_path = "/tmp/loop_rec.wav"

    print(f"Starte Dauerschleife, {args.window:.1f}s-Fenster. Strg+C zum Beenden.\n")
    try:
        while True:
            c.exec_command(
                f"timeout {args.window + 0.5} parecord --device=microphone "
                f"--file-format=wav {remote_path}"
            )
            time.sleep(args.window + 0.6)  # sicherstellen dass die Aufnahme fertig ist

            try:
                sftp.get(remote_path, local_path)
            except IOError:
                continue

            segments, info = model.transcribe(local_path, language=args.lang, beam_size=1, vad_filter=True)
            text = " ".join(s.text.strip() for s in segments).strip()
            if text:
                print(f">>> GEHOERT: {text}")
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        sftp.close()
        c.close()


if __name__ == "__main__":
    main()
