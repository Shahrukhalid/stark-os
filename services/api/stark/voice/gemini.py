"""Speech-to-text and text-to-speech with the owner's Google Gemini API key."""

from __future__ import annotations

import base64
import io
import json
import re
import time
import wave
from typing import Any, AsyncIterator

import httpx

API = "https://generativelanguage.googleapis.com/v1beta"
MODELS_TTL_S = 6 * 3600
_URDU = re.compile(r"[؀-ۿ]")
_VERSION = re.compile(r"(\d+(?:\.\d+)?)")

# The prebuilt voices and their character, so users can pick the one they like for each assistant.
VOICES = {
    "Achernar": "soft", "Achird": "friendly", "Algenib": "gravelly", "Algieba": "smooth", "Alnilam": "firm",
    "Aoede": "breezy", "Autonoe": "bright", "Callirrhoe": "easy-going", "Charon": "informative",
    "Despina": "smooth", "Enceladus": "breathy", "Erinome": "clear", "Fenrir": "excitable", "Gacrux": "mature",
    "Iapetus": "clear", "Kore": "firm", "Laomedeia": "upbeat", "Leda": "youthful", "Orus": "firm",
    "Puck": "upbeat", "Pulcherrima": "forward", "Rasalgethi": "informative", "Sadachbia": "lively",
    "Sadaltager": "knowledgeable", "Schedar": "even", "Sulafat": "warm", "Umbriel": "easy-going",
    "Vindemiatrix": "gentle", "Zephyr": "bright", "Zubenelgenubi": "casual",
}
# How a line is said (sent with the text). Free text also works in agent.toml.
STYLES = {
    "calm": "Say in a calm, clear and precise voice",
    "warm": "Say in a warm, lively and friendly voice",
    "energetic": "Say in an energetic, upbeat voice",
    "professional": "Say in a confident, professional voice",
    "gentle": "Say in a soft, gentle voice",
    "natural": "",
}


# Everything a user may see about a voice failure. Endpoints show only these fixed texts.
MESSAGES = {
    "limit": "The Gemini free limit is reached for now. Wait a minute and try again.",
    "key": "Gemini did not accept the API key. Check it in Settings.",
    "no_key": "Add your Gemini API key in Settings to use STARK voice.",
    "timeout": "Gemini took too long to answer. Try again.",
    "network": "Gemini could not be reached. Check your internet connection.",
    "no_model": "This Gemini key has no speech model available.",
    "no_audio": "Gemini returned no audio.",
    "provider": "Gemini could not handle the request right now. Try again.",
}


class VoiceError(RuntimeError):
    """A voice failure; `kind` selects the fixed text that may be shown."""

    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind if kind in MESSAGES else "provider"
        super().__init__(f"{MESSAGES[self.kind]}{f' ({detail})' if detail else ''}")


def is_urdu(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if _URDU.match(c)) / len(letters) > 0.4


def spoken(text: str, limit: int = 400) -> str:
    """What is said aloud: plain sentences, no code or links, at most about `limit` characters."""
    t = re.sub(r"```[\s\S]*?```", " ", text[:20000])
    t = re.sub(r"`([^`\n]{1,500})`", r"\1", t)
    t = re.sub(r"!\[[^\]\n]{0,300}\]\([^()\s]{0,1000}\)", " ", t)
    t = re.sub(r"\[([^\[\]\n]{1,300})\]\([^()\s]{0,1000}\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"[#*_>|~]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(p) for p in (". ", "? ", "! ", "۔ ", "؟ "))
    cut = cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0]
    return cut + (" باقی جواب اسکرین پر ہے۔" if is_urdu(cut) else " The rest is on screen.")


def wav_bytes(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _rate(mime: str) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else 24000


def _version(name: str) -> float:
    m = _VERSION.search(name.split("/")[-1])
    return float(m.group(1)) if m else 0.0


def stt_candidates(models: list[dict[str, Any]]) -> list[str]:
    """Speech-to-text models to try, best first: the newest "flash-lite" (fastest), then the newest "flash"."""
    usable = [m["name"].split("/")[-1] for m in models
              if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    skip = ("tts", "image", "live", "audio", "embed", "thinking", "robotics", "computer", "exp")
    general = [n for n in usable if "flash" in n and not any(s in n for s in skip)]
    stable = [n for n in general if "preview" not in n] or general
    lite = sorted((n for n in stable if "lite" in n), key=_version, reverse=True)
    full = sorted((n for n in stable if "lite" not in n), key=_version, reverse=True)
    return (lite[:1] + full[:1]) or []


def pick_models(models: list[dict[str, Any]]) -> tuple[str, str]:
    """(speech-to-text model, text-to-speech model) from the models this key can use.

    Speech-to-text: the newest "flash-lite" model (fast, understands audio). Voice: the newest "flash" TTS
    model, else any TTS model. Names are read from the API, so new model versions are picked up by themselves.
    """
    usable = [m["name"].split("/")[-1] for m in models
              if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    stt = (stt_candidates(models) or [""])[0]
    tts_all = [n for n in usable if "tts" in n]
    tts = (sorted(tts_all, key=lambda n: ("flash" in n, _version(n)), reverse=True) or [""])[0]
    return stt, tts


class GeminiVoice:
    def __init__(self, api_key: str, *, stt_model: str = "", tts_model: str = "", transport=None,
                 timeout: float = 30):
        self.key = api_key.strip()
        self.stt_model, self.tts_model = stt_model.strip(), tts_model.strip()
        self.transport, self.timeout = transport, timeout
        self._models: tuple[float, list[str], str] | None = None

    def configured(self) -> bool:
        return bool(self.key)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=API, timeout=self.timeout, transport=self.transport,
                                 headers={"x-goog-api-key": self.key})

    @staticmethod
    def _check(r: httpx.Response, what: str) -> dict[str, Any]:
        if r.status_code == 429:
            raise VoiceError("limit")
        if r.status_code in (400, 401, 403) and "key" in r.text.lower():
            raise VoiceError("key")
        if r.status_code != 200:
            raise VoiceError("provider", f"{what}: {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise VoiceError("provider", f"{what}: unexpected answer") from None

    async def _send(self, method: str, path: str, what: str, **kw) -> dict[str, Any]:
        try:
            async with self._client() as c:
                return self._check(await c.request(method, path, **kw), what)
        except httpx.TimeoutException:
            raise VoiceError("timeout", what) from None
        except httpx.HTTPError:
            raise VoiceError("network", what) from None

    async def _candidates(self) -> tuple[list[str], str]:
        if not self._models or time.time() - self._models[0] > MODELS_TTL_S:
            if self.stt_model and self.tts_model:
                self._models = (time.time(), [self.stt_model], self.tts_model)
            else:
                data = await self._send("GET", "/models", "list its models", params={"pageSize": 1000})
                models = data.get("models") or []
                self._models = (time.time(), stt_candidates(models), pick_models(models)[1])
        _, stts, tts = self._models
        stts = [self.stt_model] if self.stt_model else stts
        tts = self.tts_model or tts
        if not stts or not tts:
            raise VoiceError("no_model")
        return stts, tts

    async def models(self) -> tuple[str, str]:
        stts, tts = await self._candidates()
        return stts[0], tts

    async def transcribe(self, audio: bytes, mime: str = "audio/wav", language: str = "auto",
                         urdu_script: str = "urdu") -> str:
        if not self.configured():
            raise VoiceError("no_key")
        if not audio:
            return ""
        stts, _ = await self._candidates()
        lang = {"en": "The speaker uses English.", "ur": "The speaker uses Urdu."}.get(
            language, "The speaker uses English, Urdu or a mix of both.")
        script = ("Write Urdu words in Urdu script." if urdu_script != "roman"
                  else "Write Urdu words in Roman Urdu (Latin letters).")
        prompt = (f"Transcribe this recording exactly as spoken. {lang} {script} Keep names such as Vision and "
                  "Wanda as they are. Return only the words that were said, with no notes. If nothing was said, "
                  "return an empty answer.")
        body = {"contents": [{"role": "user", "parts": [
                    {"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 512}}  # no runaway repetition
        for i, stt in enumerate(stts):  # a slow or busy model falls back to the next one
            try:
                data = await self._send("POST", f"/models/{stt}:generateContent", "understand the recording",
                                        json=body, timeout=15)
                break
            except VoiceError:
                if i == len(stts) - 1:
                    raise
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = " ".join(str(p.get("text", "")) for p in parts).strip()
        return text.strip('"').strip()

    @staticmethod
    def _tts_body(text: str, voice: str, style: str) -> dict[str, Any]:
        said = f"{style.strip()}: {text}" if style.strip() else text
        return {"contents": [{"role": "user", "parts": [{"text": said}]}],
                "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice if voice in VOICES else "Charon"}}}}}

    @staticmethod
    def _audio_parts(data: dict[str, Any]) -> list[tuple[bytes, int]]:
        out = []
        for part in ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                out.append((base64.b64decode(inline["data"]),
                            _rate(inline.get("mimeType") or inline.get("mime_type", ""))))
        return out

    async def speak(self, text: str, voice: str, style: str = "") -> tuple[bytes, int]:
        """Return (16-bit mono PCM, sample rate) for the whole line."""
        pcm, rate = bytearray(), 24000
        async for chunk, rate in self.speak_stream(text, voice, style):  # noqa: B007 - last rate is kept
            pcm.extend(chunk)
        return bytes(pcm), rate

    async def speak_stream(self, text: str, voice: str, style: str = "") -> AsyncIterator[tuple[bytes, int]]:
        """Yield audio as it is made, so playback can start before the whole line is ready (one request)."""
        if not self.configured():
            raise VoiceError("no_key")
        _, tts = await self._candidates()
        body = self._tts_body(text, voice, style)
        got = False
        try:
            async with self._client() as c, c.stream(
                    "POST", f"/models/{tts}:streamGenerateContent", params={"alt": "sse"}, json=body,
                    timeout=max(self.timeout, 60)) as r:
                if r.status_code == 200:
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:])
                        except ValueError:
                            continue
                        for chunk in self._audio_parts(event):
                            got = True
                            yield chunk
                else:
                    await r.aread()
                    if r.status_code in (429, 401, 403) or (r.status_code == 400 and "key" in r.text.lower()):
                        self._check(r, "speak")  # raises the matching message
        except httpx.TimeoutException:
            raise VoiceError("timeout", "speak") from None
        except httpx.HTTPError:
            raise VoiceError("network", "speak") from None
        if got:
            return
        # streaming not offered for this model: one plain request
        data = await self._send("POST", f"/models/{tts}:generateContent", "speak", json=body,
                                timeout=max(self.timeout, 60))
        parts = self._audio_parts(data)
        if not parts:
            raise VoiceError("no_audio")
        for chunk in parts:
            yield chunk
