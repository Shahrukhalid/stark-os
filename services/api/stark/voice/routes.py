"""HTTP endpoints for STARK voice. Everything said goes to the assistants through the normal chat endpoint."""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .audio import Audio, AudioUnavailable
from .gemini import MESSAGES, STYLES, VOICES, GeminiVoice, VoiceError, spoken, wav_bytes

MAX_UPLOAD = 10 * 1024 * 1024
MIC_HELP = "The microphone could not be opened. Allow microphone access for STARK AI in your system settings."
PREFS = "voice_prefs"


class TranscribeIn(BaseModel):
    audio: str = Field(max_length=MAX_UPLOAD * 4 // 3 + 16)
    mime: str = Field("audio/webm", max_length=60, pattern=r"^audio/[a-z0-9.+-]+(;.*)?$")


class SpeakIn(BaseModel):
    agent_id: str = Field(max_length=40)
    text: str = Field(max_length=20000)
    play: bool = True
    voice: str = Field("", max_length=40)  # preview another voice without saving it
    style: str = Field("", max_length=40)


class PrefIn(BaseModel):
    agent_id: str = Field(max_length=40)
    voice: str = Field("", max_length=40)  # empty: back to the assistant's default
    style: str = Field("", max_length=40)


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
        """Only fixed texts are shown; details stay in the engine."""
        if isinstance(exc, VoiceError):
            return HTTPException(502, MESSAGES[exc.kind])
        return HTTPException(409, MIC_HELP)

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

    def chosen(k: Any, agent_id: str) -> tuple[str, str]:
        """(voice, style text) for an assistant: the user's choice, else agent.toml, else a default."""
        profile = k.registry.get(agent_id).voice
        pref = (k.db.get_setting(PREFS) or {}).get(agent_id) or {}
        name = pref.get("voice") or profile.voice or "Charon"
        style = STYLES.get(pref.get("style", ""), None)
        return name, profile.style if style is None else style

    @app.get("/api/voice/voices", dependencies=[api])
    def voices(k: Any = Depends(kernel)) -> dict[str, Any]:
        agents = {a.id: {"voice": chosen(k, a.id)[0], "style": ((k.db.get_setting(PREFS) or {}).get(a.id) or {})
                         .get("style", ""), "default": a.voice.voice or "Charon"}
                  for a in k.registry.all() if not a.voice.muted}
        return {"voices": [{"name": n, "character": c} for n, c in VOICES.items()],
                "styles": list(STYLES), "agents": agents}

    @app.put("/api/voice/prefs", dependencies=[api])
    def save_pref(body: PrefIn, k: Any = Depends(kernel)) -> dict[str, Any]:
        if body.agent_id not in k.registry:
            raise HTTPException(404, "unknown agent")
        if (body.voice and body.voice not in VOICES) or (body.style and body.style not in STYLES):
            raise HTTPException(400, "unknown voice or style")
        prefs = dict(k.db.get_setting(PREFS) or {})
        if body.voice or body.style:
            prefs[body.agent_id] = {"voice": body.voice, "style": body.style}
        else:
            prefs.pop(body.agent_id, None)
        k.db.set_setting(PREFS, prefs)
        return {"agent_id": body.agent_id, "voice": chosen(k, body.agent_id)[0]}

    @app.post("/api/voice/speak", dependencies=[api])
    async def speak(body: SpeakIn, k: Any = Depends(kernel)) -> dict[str, Any]:
        if body.agent_id not in k.registry:
            raise HTTPException(404, "unknown agent")
        if k.registry.get(body.agent_id).voice.muted:
            return {"played": False, "muted": True}
        name, style = chosen(k, body.agent_id)
        if body.voice in VOICES:
            name = body.voice
        if body.style in STYLES:
            style = STYLES[body.style]
        text = spoken(body.text)
        if not text:
            return {"played": False}
        player = None
        pcm, rate = bytearray(), 24000
        try:
            async for chunk, rate in voice.speak_stream(text, name, style):
                if body.play and player is None and local_audio()[0]:
                    try:
                        player = audio.player(rate)  # starts with the first piece of audio
                    except AudioUnavailable:
                        body.play = False
                if player is not None:
                    player.feed(chunk)
                else:
                    pcm.extend(chunk)
        except VoiceError as exc:
            if player is not None:
                player.close()
            raise fail(exc) from None
        if player is not None:
            player.close()
            return {"played": True, "text": text}
        return {"played": False, "text": text, "mime": "audio/wav",
                "audio": base64.b64encode(wav_bytes(bytes(pcm), rate)).decode()}

    @app.post("/api/voice/stop", dependencies=[api])
    def stop() -> dict[str, Any]:
        audio.stop_playing()
        return {"stopped": True}
