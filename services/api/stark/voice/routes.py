"""HTTP endpoints for STARK voice. Everything said goes to the assistants through the normal chat endpoint."""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .audio import Audio, AudioUnavailable
from .gemini import GeminiVoice, VoiceError, spoken, wav_bytes

MAX_UPLOAD = 10 * 1024 * 1024
DEFAULT_VOICES = {"vision": ("Charon", "Say in a calm, clear and precise voice"),
                  "wanda": ("Sulafat", "Say in a warm, lively and friendly voice")}


class TranscribeIn(BaseModel):
    audio: str = Field(max_length=MAX_UPLOAD * 4 // 3 + 16)
    mime: str = Field("audio/webm", max_length=60, pattern=r"^audio/[a-z0-9.+-]+(;.*)?$")


class SpeakIn(BaseModel):
    agent_id: str = Field(max_length=40)
    text: str = Field(max_length=20000)
    play: bool = True


def register(app: FastAPI, api: Any, kernel: Callable[[], Any], settings: Any, audio: Audio | None = None) -> None:
    voice = GeminiVoice(settings.gemini_api_key, stt_model=settings.voice_stt_model,
                        tts_model=settings.voice_tts_model)
    audio = audio or Audio()

    def engine() -> Literal["gemini", "browser"]:
        return "gemini" if settings.voice_engine == "gemini" and voice.configured() else "browser"

    def local_audio() -> tuple[bool, str]:
        if not settings.desktop:
            return False, "The engine is not on this computer; the page records instead."
        return audio.available()

    def fail(exc: Exception) -> HTTPException:
        return HTTPException(502 if isinstance(exc, VoiceError) else 409, str(exc))

    @app.get("/api/voice/status", dependencies=[api])
    def status() -> dict[str, Any]:
        ok, why = local_audio()
        return {"engine": engine(), "configured": voice.configured(), "local_audio": ok, "local_reason": why,
                "language": settings.voice_language, "urdu_script": settings.voice_urdu_script}

    async def _text(wav: bytes, mime: str) -> dict[str, Any]:
        try:
            text = await voice.transcribe(wav, mime, settings.voice_language, settings.voice_urdu_script)
        except VoiceError as exc:
            raise fail(exc) from None
        return {"text": text}

    @app.post("/api/voice/listen/start", dependencies=[api])
    async def listen_start() -> dict[str, Any]:
        ok, why = local_audio()
        if not ok:
            raise HTTPException(409, why)
        audio.stop_playing()
        try:
            await asyncio.to_thread(audio.start)
        except AudioUnavailable as exc:
            raise fail(exc) from None
        return {"listening": True}

    @app.post("/api/voice/listen/stop", dependencies=[api])
    async def listen_stop() -> dict[str, Any]:
        wav = await asyncio.to_thread(audio.stop)
        return await _text(wav, "audio/wav") if wav else {"text": ""}

    @app.post("/api/voice/listen/cancel", dependencies=[api])
    def listen_cancel() -> dict[str, Any]:
        audio.cancel()
        return {"listening": False}

    @app.post("/api/voice/transcribe", dependencies=[api])
    async def transcribe(body: TranscribeIn) -> dict[str, Any]:
        try:
            data = base64.b64decode(body.audio, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "audio must be base64") from None
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "recording too long")
        return await _text(data, body.mime.split(";")[0])

    @app.post("/api/voice/speak", dependencies=[api])
    async def speak(body: SpeakIn, k: Any = Depends(kernel)) -> dict[str, Any]:
        if body.agent_id not in k.registry:
            raise HTTPException(404, "unknown agent")
        profile = k.registry.get(body.agent_id).voice
        if profile.muted:
            return {"played": False, "muted": True}
        name, style = DEFAULT_VOICES.get(body.agent_id, ("Charon", ""))
        text = spoken(body.text)
        if not text:
            return {"played": False}
        try:
            pcm, rate = await voice.speak(text, profile.voice or name, profile.style or style)
        except VoiceError as exc:
            raise fail(exc) from None
        if body.play and local_audio()[0]:
            try:
                audio.play(pcm, rate)
                return {"played": True, "text": text}
            except AudioUnavailable:
                pass
        return {"played": False, "text": text, "mime": "audio/wav",
                "audio": base64.b64encode(wav_bytes(pcm, rate)).decode()}

    @app.post("/api/voice/stop", dependencies=[api])
    def stop() -> dict[str, Any]:
        audio.stop_playing()
        return {"stopped": True}
