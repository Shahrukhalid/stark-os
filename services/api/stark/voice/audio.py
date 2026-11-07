"""Microphone and speakers for the desktop app (PortAudio through sounddevice, bundled with the installers).

Only used when the engine runs on the user's own computer (the desktop app). Nothing is recorded unless the
user holds the talk button; recording stops by itself after MAX_SECONDS.
"""

from __future__ import annotations

import threading
from typing import Any

from .gemini import wav_bytes

RATE = 16000
MAX_SECONDS = 60


class AudioUnavailable(RuntimeError):
    pass


class Audio:
    def __init__(self, sd: Any = None):
        self._sd = sd
        self._lock = threading.Lock()
        self._stream: Any = None
        self._buf = bytearray()
        self._out: Any = None
        self._stop_play = threading.Event()

    def _module(self):
        if self._sd is None:
            try:
                import sounddevice  # noqa: PLC0415 - optional, desktop only
            except (ImportError, OSError) as exc:  # no PortAudio on this machine
                raise AudioUnavailable("No audio support on this computer.") from exc
            self._sd = sounddevice
        return self._sd

    def available(self) -> tuple[bool, str]:
        try:
            sd = self._module()
            sd.query_devices(kind="input")
            sd.query_devices(kind="output")
        except AudioUnavailable as exc:
            return False, str(exc)
        except Exception:  # noqa: BLE001 - PortAudio raises its own error types
            return False, "No microphone or speaker found."
        return True, ""

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        sd = self._module()
        with self._lock:
            self._close_input()
            self._buf = bytearray()
            limit = RATE * 2 * MAX_SECONDS

            def take(indata, frames, time_info, status):  # noqa: ARG001 - PortAudio callback signature
                if len(self._buf) < limit:
                    self._buf.extend(bytes(indata))

            try:
                self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", callback=take)
                self._stream.start()
            except Exception as exc:  # noqa: BLE001
                self._stream = None
                raise AudioUnavailable("The microphone could not be opened. Allow microphone access for "
                                       "STARK AI in your system settings.") from exc

    def stop(self) -> bytes:
        """Stop recording; return a WAV file (empty bytes when nothing was recorded)."""
        with self._lock:
            self._close_input()
            pcm, self._buf = bytes(self._buf), bytearray()
        return wav_bytes(pcm, RATE) if len(pcm) > RATE * 2 // 4 else b""  # under 0.25 s: nothing said

    def cancel(self) -> None:
        with self._lock:
            self._close_input()
            self._buf = bytearray()

    def _close_input(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    def play(self, pcm: bytes, rate: int) -> None:
        """Play in the background; a new reply or stop_playing() cuts the current one off."""
        sd = self._module()
        self.stop_playing()
        self._stop_play = stop = threading.Event()

        def run() -> None:
            try:
                with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16") as out:
                    step = rate // 10 * 2  # 100 ms
                    for i in range(0, len(pcm), step):
                        if stop.is_set():
                            break
                        out.write(pcm[i:i + step])
            except Exception:  # noqa: BLE001 - a missing speaker must not crash the engine
                pass

        threading.Thread(target=run, name="stark-voice-play", daemon=True).start()

    def stop_playing(self) -> None:
        self._stop_play.set()
