"""1.7: video studio ultra (speech-to-text, styled captions, join, speed, batch, progress, cancel, streaming)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import video
from stark.core import db as dbm
from stark.main import create_app

EXE = video.ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(not EXE, reason="ffmpeg not installed")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


def make_clip(path, seconds=3, size="640x360", tone=440):
    subprocess.run([EXE, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25",
                    "-f", "lavfi", "-i", f"sine=frequency={tone}", "-t", str(seconds), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True, timeout=60)


def upload(client, path, name="clip.mp4"):
    r = client.post(f"/api/video/upload?name={name}", content=path.read_bytes())
    assert r.status_code == 200, r.text
    return r.json()["name"]


def wait(client, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in client.get("/api/video").json()["jobs"] if x["id"] == jid)
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


SEGS = [{"start": 0.0, "end": 4.0, "text": "Welcome to our shop."},
        {"start": 4.0, "end": 9.5, "text": "Today we roast a new coffee from Ethiopia and it tastes of berries."},
        {"start": 9.5, "end": 12.0, "text": "Come and try it!"},
        {"start": 12.0, "end": 30.0, "text": "We are open every day from eight until six"}]


def test_transcript_helpers():
    lines = video.split_lines(SEGS, max_chars=30)
    assert all(len(x["text"]) <= 30 for x in lines) and lines[0]["start"] == 0
    assert abs(sum(x["end"] - x["start"] for x in lines) - 30) < 0.01
    cut = video.clip_segments(SEGS, 5.0, 11.0)
    assert cut[0]["start"] == 0 and abs(cut[0]["end"] - 4.5) < 1e-6 and cut[-1]["end"] == 6.0
    clips = video.plan_clips(SEGS, max_s=20, min_s=8)
    assert clips[0] == {"start": 0.0, "end": 9.5, "text": SEGS[0]["text"] + " " + SEGS[1]["text"]}
    assert all(c["end"] - c["start"] <= 20 for c in clips[:-1])
    s = video.style_string({"size": 20, "color": "yellow", "position": "top", "box": True})
    assert "FontSize=20" in s and "&H0000FFFF" in s and "Alignment=8" in s and "BorderStyle=3" in s


def test_command_speed_volume_fade_and_merge(tmp_path):
    info = {"duration": 60.0, "width": 1920, "height": 1080, "audio": True}
    cmd = video.build_command("ffmpeg", tmp_path / "a.mp4", tmp_path / "o.mp4", info,
                              {"preset": "vertical", "format": "mp4", "speed": 2, "volume": 0.5, "fade": 0.5,
                               "end": 20, "captions": "burn", "style": {"position": "top"}}, "c.srt")
    vf, af = cmd[cmd.index("-vf") + 1], cmd[cmd.index("-af") + 1]
    assert vf.index("subtitles=") < vf.index("setpts=PTS/2") and "Alignment=8" in vf
    assert "fade=t=out:st=9.50" in vf and "atempo=2" in af and "volume=0.5" in af and "-progress" in cmd
    infos = [{"duration": 5.0, "width": 640, "height": 360, "audio": True}] * 3
    m, total = video.build_merge_command("ffmpeg", [tmp_path / f"{i}.mp4" for i in range(3)], infos,
                                         tmp_path / "j.mp4", {"preset": "square", "format": "mp4", "transition": 1})
    fc = m[m.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=1.00:offset=4.000" in fc and "offset=8.000" in fc and total == 13.0
    assert "acrossfade" in fc
    with pytest.raises(video.VideoError):
        video.build_merge_command("ffmpeg", [tmp_path / "a.mp4"], infos[:1], tmp_path / "j.mp4",
                                  {"preset": "square", "format": "mp4"})


@needs_ffmpeg
def test_join_speed_batch_styled_captions_and_progress(client, settings, tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    make_clip(a, 3)
    make_clip(b, 3, size="320x240", tone=660)
    na, nb = upload(client, a, "a.mp4"), upload(client, b, "b.mp4")
    st = video.Studio(settings)

    j = wait(client, client.post("/api/video/export", json={"files": [na, nb], "preset": "square", "format": "mp4",
                                                             "transition": 0.5}).json()["id"])
    assert j["status"] == "done" and j["progress"] == 1.0, j
    info = video.probe(EXE, st.path(j["output"]))
    assert (info["width"], info["height"]) == (1080, 1080) and 5.0 <= info["duration"] <= 5.8 and info["audio"]

    j = wait(client, client.post("/api/video/export", json={"file": na, "preset": "original", "format": "mp4",
                                                             "speed": 2, "volume": 0.5}).json()["id"])
    assert j["status"] == "done" and 1.3 <= video.probe(EXE, st.path(j["output"]))["duration"] <= 1.7

    batch = client.post("/api/video/export", json={"file": na, "presets": ["vertical", "landscape"],
                                                   "format": "webm", "mute": True}).json()["jobs"]
    sizes = {video.probe(EXE, st.path(wait(client, x["id"])["output"]))["width"] for x in batch}
    assert sizes == {1080, 1920}

    # captions timed from a transcript, burned in with a style (needs libass in this FFmpeg)
    (st.path(na).with_name(na + ".transcript.json")).write_text(json.dumps({"segments": [
        {"start": 0.2, "end": 1.5, "text": "Hello from the studio"}, {"start": 1.5, "end": 2.8, "text": "Second line"}]}))
    assert client.get(f"/api/video/transcript?name={na}").json()["clips"][0]["start"] == 0.2
    if video.status()["burn_captions"]:
        j = wait(client, client.post("/api/video/export", json={
            "file": na, "preset": "vertical", "format": "mp4", "start": 1.0, "captions": "burn",
            "caption_source": "transcript", "style": {"size": 24, "color": "yellow", "box": True}}).json()["id"])
        assert j["status"] == "done", j
        srt = st.path(j["captions"]).read_text()
        assert srt.startswith("1\n00:00:00,000 --> 00:00:00,500\nHello from the studio")  # shifted to the cut
    assert client.get(f"/api/video/preview?name={na}&at=1").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/video/info?name={na}").json()["audio"] is True


@needs_ffmpeg
def test_cancel_and_streamed_upload_checks(client, settings, tmp_path):
    long = tmp_path / "long.mp4"
    make_clip(long, 40, size="1280x720")
    name = upload(client, long, "long.mp4")
    job = client.post("/api/video/export", json={"file": name, "preset": "landscape", "format": "webm"}).json()
    time.sleep(0.5)
    assert client.delete(f"/api/video/jobs/{job['id']}").status_code == 200
    assert wait(client, job["id"])["status"] == "cancelled"
    assert not [p for p in video.folder(settings).iterdir() if ".part" in p.name]
    assert client.delete(f"/api/video/jobs/{job['id']}").status_code == 404
    assert client.post("/api/video/upload?name=x.mp4", content=b"\x00" * 64).status_code == 400
    assert not [p for p in video.folder(settings).iterdir() if p.name.endswith(".part")]


async def test_model_download_is_checked(settings):
    import asyncio

    st = video.Studio(settings)
    good = b"lmgg" + b"\x00" * 11_000_000
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=good if "tiny" in str(req.url) else b"<html>not a model</html>" * 10)
    job = st.download_model("tiny", transport=httpx.MockTransport(handler))
    for _ in range(100):
        if st.jobs[job["id"]]["status"] in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert st.jobs[job["id"]]["status"] == "done" and video.model_file(settings, "tiny").is_file()
    assert calls[0].endswith("ggml-tiny.bin")
    bad = st.download_model("base", transport=httpx.MockTransport(handler))
    for _ in range(100):
        if st.jobs[bad["id"]]["status"] in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert st.jobs[bad["id"]]["status"] == "failed" and not video.model_file(settings, "base").exists()
    assert [m["installed"] for m in video.models_status(settings)] == [True, False, False]


MODEL = os.environ.get("STARK_TEST_WHISPER_MODEL")


@pytest.mark.skipif(not MODEL, reason="set STARK_TEST_WHISPER_MODEL to a ggml model file (CI does)")
def test_real_speech_to_text(client, settings, tmp_path):
    # with a model given (CI) everything else must be there: this test never silently skips in CI
    assert EXE and shutil.which("espeak-ng") and video.whisper_available(), video.WHISPER_ERROR
    wav = tmp_path / "speech.wav"
    subprocess.run(["espeak-ng", "-s", "140", "-w", str(wav), "Hello world. This is a test of the video studio."],
                   check=True, timeout=60)
    clip = tmp_path / "talk.mp4"
    subprocess.run([EXE, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=10",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
                   check=True, timeout=60)
    name = upload(client, clip, "talk.mp4")
    shutil.copy(MODEL, video.model_file(settings, "tiny"))
    j = wait(client, client.post("/api/video/transcribe", json={"file": name, "model": "tiny",
                                                                "language": "en"}).json()["id"], timeout=180)
    assert j["status"] == "done", j
    t = client.get(f"/api/video/transcript?name={name}").json()
    assert "hello" in t["text"].lower() and t["segments"][0]["end"] > t["segments"][0]["start"]
