"""1.8: video → Shorts content packages, animated captions, more transitions, cancellable transcription."""
from __future__ import annotations

import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from stark import brands, shorts, video
from stark.core import db as dbm
from stark.core.db import ContentItem
from stark.main import create_app

from .conftest import make_kernel, text

EXE = video.ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(not EXE, reason="ffmpeg not installed")
CANDS = [{"start": 0, "end": 20, "text": "So today I want to talk about our new coffee."},
         {"start": 20, "end": 40, "text": "Did you know 3 out of 4 people brew it too hot? Here is how you fix it!"},
         {"start": 40, "end": 60, "text": "Anyway that was it, thanks for watching."}]


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


def test_rule_pick_clean_pick_and_post_text():
    picks = shorts.rule_pick(CANDS, 1)
    assert picks[0]["index"] == 1 and picks[0]["hashtags"]  # the question with a number and "you" wins
    raw = [{"index": 7, "title": "x"}, {"index": 0, "title": "A" * 200, "hashtags": ["coffee", "#bad tag", "#ok_2"]},
           {"index": 0, "title": "dup"}, {"index": "2", "hook": "Bye"}]
    clean = shorts.clean_pick(raw, CANDS, 5)
    assert [c["index"] for c in clean] == [0, 2] and len(clean[0]["title"]) == 70
    assert clean[0]["hashtags"] == ["#coffee", "#ok_2"]
    long = {"hook": "Hook", "description": "word " * 200, "hashtags": ["#a", "#b", "#c", "#d", "#e", "#f"]}
    out = shorts.post_text("x", long)
    assert len(out) <= 280 and out.endswith("#a #b")  # X: 280 characters, 2 hashtags


def test_ass_animations_and_transitions(tmp_path):
    segs = [{"start": 0.2, "end": 1.4, "text": "Hello brave {new} world"}]
    k = video.ass_from_segments(segs, {"size": 14}, "karaoke", (1080, 1920))
    assert "{\\k" in k and "{new}" not in k and "PlayResY: 1920" in k
    assert "\\fad(150,100)" in video.ass_from_segments(segs, None, "fade", (1080, 1920))
    assert video.parse_srt(video.captions_from_script("One two three. Four five six!", 4))[0]["start"] == 0
    infos = [{"duration": 5.0, "width": 640, "height": 360, "audio": False}] * 2
    cmd, _ = video.build_merge_command("ffmpeg", [tmp_path / "a.mp4", tmp_path / "b.mp4"], infos, tmp_path / "o.mp4",
                                       {"preset": "square", "format": "mp4", "transition": 1,
                                        "transition_type": "wipeleft"})
    assert "xfade=transition=wipeleft" in cmd[cmd.index("-filter_complex") + 1]


def test_transcription_can_be_stopped(monkeypatch):
    import types

    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, samples, new_segment_callback=None, abort_callback=None):
            assert abort_callback is not None and abort_callback()
            return []
    monkeypatch.setitem(__import__("sys").modules, "pywhispercpp.model", types.SimpleNamespace(Model=FakeModel))
    with pytest.raises(video.VideoError, match="cancelled"):
        video.transcribe_audio("m.bin", [], should_stop=lambda: True)


async def test_agent_picks_highlights_and_bad_answers_fall_back(settings):
    answer = json.dumps({"clips": [{"index": 1, "title": "Brew it cooler", "hook": "You brew it too hot.",
                                    "description": "A quick fix.", "hashtags": ["#coffee", "not valid!"]}]})
    k, _ = make_kernel(settings, brain=lambda a, r: [text(answer)])
    picks, how = await shorts._pick(k, CANDS, 1, "talk")
    assert how == "agent" and picks[0]["title"] == "Brew it cooler" and picks[0]["hashtags"] == ["#coffee"]
    k2, _ = make_kernel(settings, brain=lambda a, r: [text("no json here")])
    picks, how = await shorts._pick(k2, CANDS, 1, "talk")
    assert how == "rules" and picks[0]["index"] == 1


def wait(client, jid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in client.get("/api/video").json()["jobs"] if x["id"] == jid)
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.3)
    raise AssertionError("job did not finish")


@needs_ffmpeg
def test_video_to_shorts_package(client, settings, tmp_path):
    clip = tmp_path / "talk.mp4"
    subprocess.run([EXE, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=15",
                    "-f", "lavfi", "-i", "sine", "-t", "60", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", "-shortest", str(clip)], check=True, timeout=120)
    name = client.post("/api/video/upload?name=talk.mp4", content=clip.read_bytes()).json()["name"]
    b = client.post("/api/brands", json={"name": "Acme"}).json()
    client.post("/api/brands/active", json={"id": b["id"]})
    r = client.post("/api/video/package", json={"file": name, "count": 2})
    assert r.status_code == 400 and "Transcribe" in r.text
    st = video.Studio(settings)
    st.path(name).with_name(name + ".transcript.json").write_text(json.dumps({"segments": CANDS}))
    job = client.post("/api/video/package", json={"file": name, "count": 2, "platforms": ["tiktok", "x"],
                                                  "animation": "karaoke"}).json()
    client.post("/api/brands/active", json={"id": None})  # switching brands mid-run must not move the drafts
    j = wait(client, job["id"])
    assert j["status"] == "done" and j["picked_by"] == "rules" and len(j["clips"]) == 2, j
    first = j["clips"][0]
    info = video.probe(EXE, st.path(first["video"]))
    assert (info["width"], info["height"]) == (1080, 1920) and 18 <= info["duration"] <= 21
    assert first["thumbnail"].startswith("media/generated/") and {d["platform"] for d in first["drafts"]} == {"tiktok", "x"}
    k = client.app.state.kernel
    with k.db.session() as s:
        items = s.scalars(select(ContentItem).where(ContentItem.created_by == "video-autopilot")).all()
        assert len(items) == 4 and {i.brand for i in items} == {"Acme"} and {i.status for i in items} == {"draft"}
        assert all(i.kind == "video" for i in items)
    assert client.get(f"/api/video/packages?name={name}").json()["packages"][0]["brand"] == "Acme"
    assert brands.active(k) is None


@needs_ffmpeg
def test_transcribe_endpoint_answers_json(client, settings, tmp_path, monkeypatch):
    """1.8.0 regression: the job's internal stop signal must never reach the JSON answer."""
    clip = tmp_path / "s.mp4"
    subprocess.run([EXE, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
                    "-f", "lavfi", "-i", "sine", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(clip)], check=True, timeout=60)
    name = client.post("/api/video/upload?name=s.mp4", content=clip.read_bytes()).json()["name"]
    monkeypatch.setattr(video, "whisper_available", lambda: True)
    monkeypatch.setattr(video, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 1.0, "text": "Hi"}])
    video.model_file(settings, "tiny").write_bytes(b"lmgg")
    r = client.post("/api/video/transcribe", json={"file": name, "model": "tiny"})
    assert r.status_code == 200 and "abort" not in r.json(), r.text
    assert wait(client, r.json()["id"])["status"] == "done"
    assert client.get("/api/video").status_code == 200
