"""STARK voice: Gemini speech-to-text and voices, desktop microphone, and the endpoints."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from stark.core.addressing import parse_address
from stark.voice import GeminiVoice, VoiceError, spoken
from stark.voice.audio import Audio
from stark.voice.gemini import pick_models

MODELS = {"models": [
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.1-flash-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-pro-preview-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
]}
PCM = b"\x01\x00" * 2400


def _gemini(seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["x-goog-api-key"] == "gem-key" and "key=" not in str(req.url)
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        body = json.loads(req.content)
        if "tts" in req.url.path:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(PCM).decode()}}]}}]})
        assert body["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "audio/wav"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "وژن، آج کی پوسٹس دکھاؤ"}]}}]})
    return httpx.MockTransport(handler)


def test_models_are_picked_from_what_the_key_can_use():
    assert pick_models(MODELS["models"]) == ("gemini-2.5-flash", "gemini-2.5-flash-preview-tts")
    assert pick_models([]) == ("", "")


async def test_transcribe_and_speak_in_urdu():
    seen: list = []
    v = GeminiVoice("gem-key", transport=_gemini(seen))
    text = await v.transcribe(b"RIFF....", "audio/wav", language="auto")
    assert text == "وژن، آج کی پوسٹس دکھاؤ"
    assert parse_address(text) == ("vision", "آج کی پوسٹس دکھاؤ")
    prompt = json.loads(seen[1].content)["contents"][0]["parts"][0]["text"]
    assert "Urdu script" in prompt
    pcm, rate = await v.speak("Hello", "Sulafat", "Say warmly")
    assert (pcm, rate) == (PCM, 24000)
    tts = json.loads(seen[-1].content)
    assert tts["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Sulafat"
    assert tts["contents"][0]["parts"][0]["text"] == "Say warmly: Hello"
    assert sum(1 for r in seen if r.url.path.endswith("/models")) == 1  # model list is cached


async def test_errors_are_short_and_never_include_the_key():
    v = GeminiVoice("gem-key", stt_model="m", tts_model="t",
                    transport=httpx.MockTransport(lambda r: httpx.Response(429, text="quota gem-key")))
    with pytest.raises(VoiceError, match="free limit") as exc:
        await v.speak("hi", "Charon")
    assert "gem-key" not in str(exc.value)
    with pytest.raises(VoiceError, match="Gemini API key"):
        await GeminiVoice("").transcribe(b"x")


def test_spoken_text_is_short_and_plain():
    assert spoken("**Done.** See [the post](https://x.test/1) and `code`.") == "Done. See the post and code."
    long = "Sentence one is here. " * 60
    out = spoken(long)
    assert len(out) < 650 and out.endswith("The rest is on screen.")
    assert spoken("یہ پہلا جملہ ہے۔ " * 80).endswith("باقی جواب اسکرین پر ہے۔")


def test_urdu_and_roman_names_address_the_assistants():
    assert parse_address("ارے وانڈا، تین پوسٹس لکھو") == ("wanda", "تین پوسٹس لکھو")
    assert parse_address("Wanda, teen posts likho") == ("wanda", "teen posts likho")


class FakeStream:
    def __init__(self, callback=None, **kw):
        self.callback, self.kw = callback, kw
        self.written = bytearray()

    def start(self):
        self.callback(b"\x02\x00" * 16000, 16000, None, None)  # one second of sound

    def stop(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def write(self, data):
        FakeSD.played.extend(data)


class FakeSD:
    played = bytearray()

    @staticmethod
    def query_devices(kind=None):
        return {"name": kind}

    RawInputStream = FakeStream
    RawOutputStream = FakeStream


def test_desktop_microphone_records_a_wav():
    audio = Audio(FakeSD)
    assert audio.available() == (True, "")
    audio.start()
    wav = audio.stop()
    assert wav[:4] == b"RIFF" and len(wav) > 32000
    assert not audio.recording and audio.stop() == b""


@pytest.fixture
def voice_client(settings, monkeypatch):
    from stark.main import create_app
    from stark.voice import routes

    seen: list = []
    real = routes.GeminiVoice

    def with_mock(*a, **k):
        return real(*a, **k, transport=_gemini(seen))

    monkeypatch.setattr(routes, "GeminiVoice", with_mock)
    settings.gemini_api_key, settings.desktop = "gem-key", True
    import stark.voice.audio as audio_mod
    monkeypatch.setattr(audio_mod.Audio, "_module", lambda self: FakeSD)
    with TestClient(create_app(settings, {})) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c, seen


def test_voice_endpoints(voice_client, settings):
    c, seen = voice_client
    st = c.get("/api/voice/status").json()
    assert st["engine"] == "gemini" and st["local_audio"] and st["configured"]
    assert c.post("/api/voice/listen/start").json() == {"listening": True}
    assert c.post("/api/voice/listen/stop").json() == {"text": "وژن، آج کی پوسٹس دکھاؤ"}
    r = c.post("/api/voice/speak", json={"agent_id": "wanda", "text": "Here are **three** drafts."}).json()
    assert r == {"played": True, "text": "Here are three drafts."}
    voice = json.loads(seen[-1].content)["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
    assert voice["voiceName"] == "Sulafat"
    r = c.post("/api/voice/speak", json={"agent_id": "vision", "text": "Hi", "play": False}).json()
    assert r["audio"] and base64.b64decode(r["audio"])[:4] == b"RIFF"
    assert c.post("/api/voice/speak", json={"agent_id": "nobody", "text": "x"}).status_code == 404
    assert c.post("/api/voice/transcribe", json={"audio": "!!", "mime": "audio/webm"}).status_code == 400
    assert c.post("/api/voice/transcribe", json={"audio": "AAAA", "mime": "text/html"}).status_code == 422
    assert c.post("/api/voice/stop").json() == {"stopped": True}
    assert TestClient(c.app).get("/api/voice/status").status_code == 401  # needs the API token


def test_without_a_key_the_browser_speech_is_used(settings):
    from stark.main import create_app

    with TestClient(create_app(settings, {})) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        st = c.get("/api/voice/status").json()
        assert st["engine"] == "browser" and not st["local_audio"]
        assert c.post("/api/voice/listen/start").status_code == 409
