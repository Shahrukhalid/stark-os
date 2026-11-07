"""Check STARK voice on this computer: microphone, Urdu/English speech-to-text, and the voice choices.

    python scripts/voice-check.py            (asks for your Gemini key; it is not saved)

Needs: pip install httpx sounddevice numpy
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402

from stark.voice.gemini import GeminiVoice, VoiceError, wav_bytes  # noqa: E402

CHOICES = {"Vision": ["Charon", "Iapetus", "Orus", "Algenib"], "Wanda": ["Sulafat", "Aoede", "Kore", "Despina"]}
LINE = "Hello, I'm {name}. السلام علیکم، میں {urdu} ہوں۔ آپ کی آج کی پوسٹس تیار ہیں۔"
URDU = {"Vision": "وژن", "Wanda": "وانڈا"}


async def main() -> None:
    key = os.environ.get("GEMINI_API_KEY") or getpass.getpass("Gemini API key (hidden, not saved): ")
    v = GeminiVoice(key, stt_model=os.environ.get("STARK_VOICE_STT_MODEL", ""),
                    tts_model=os.environ.get("STARK_VOICE_TTS_MODEL", ""))
    try:
        stt, tts = await v.models()
    except VoiceError as exc:
        sys.exit(f"Gemini: {exc}")
    print(f"Models: speech-to-text {stt}, voice {tts}\n")
    for lang in ("Urdu", "English"):
        input(f"Press Enter, then speak in {lang} for 5 seconds…")
        pcm = sd.rec(16000 * 5, samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        level = int(np.abs(pcm).max())
        if level < 300:
            print("  The microphone recorded silence. Allow microphone access for Terminal in System Settings → "
                  "Privacy & Security → Microphone, then run this again.\n")
            continue
        t = time.time()
        try:
            text = await v.transcribe(wav_bytes(pcm.tobytes(), 16000), "audio/wav")
        except VoiceError as exc:
            print(f"  {exc}\n")
            continue
        print(f"  heard ({time.time() - t:.1f} s): {text or '(nothing)'}\n")
    for who, voices in CHOICES.items():
        for name in voices:
            input(f"Press Enter to hear {who} as {name}…")
            t = time.time()
            try:
                audio, rate = await v.speak(LINE.format(name=who, urdu=URDU[who]), name)
            except VoiceError as exc:
                print(f"  {exc}")
                continue
            print(f"  ready in {time.time() - t:.1f} s")
            sd.play(np.frombuffer(audio, dtype=np.int16), rate)
            sd.wait()
    print("\nDone. Tell me which voice you liked for Vision and for Wanda.")


if __name__ == "__main__":
    asyncio.run(main())
