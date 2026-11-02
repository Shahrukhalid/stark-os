"""1.6: brand context per task, smarter memory recall, video studio."""
from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from stark import automations as au
from stark import brands, video
from stark.core import db as dbm
from stark.core.memory import _tokens
from stark.main import create_app
from stark.tools.social import Social, check_post

from .conftest import make_kernel, text

HAS_FFMPEG = bool(video.ffmpeg_path())


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


async def test_task_keeps_its_brand_when_the_dashboard_switches(settings):
    seen: list[str] = []
    k, _ = make_kernel(settings, brain=lambda a, r: [text("ok")])
    brands.save(k, {"name": "Acme", "voice": "Acme voice", "blocked_terms": ["cheap"]})
    b = brands.save(k, {"name": "Beta", "voice": "Beta voice"})
    k.router.providers["openrouter"].brain = lambda a, r: (seen.append(r.system), [text("done")])[1]
    t = k.submit_chat("edith", "write a post", brand="Acme")
    brands.activate(k, b["id"])  # dashboard now on Beta
    await k.wait(t["id"], 5)
    assert k.get_task(t["id"])["brand"] == "Acme"
    assert "Acme voice" in seen[-1] and "Beta voice" not in seen[-1]
    # outside any task the dashboard brand applies; inside a task context its own brand's words are blocked
    assert dbm.current_brand()["name"] == "Beta"
    token = dbm.TASK_BRAND.set(brands.task_context(k, "Acme"))
    try:
        assert any(i["code"] == "blocked_term" for i in check_post("bluesky", "So cheap")["issues"])
    finally:
        dbm.TASK_BRAND.reset(token)
    assert not any(i["code"] == "blocked_term" for i in check_post("bluesky", "So cheap")["issues"])
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


async def test_automation_drafts_and_agent_tasks_use_the_automation_brand(settings):
    k, _ = make_kernel(settings, brain=lambda a, r: [text("ok")])
    brands.save(k, {"name": "Acme"})
    dbm.ACTIVE_BRAND.update({"name": "Acme"})
    eng = au.Engine(k, Social(settings), settings)
    a = eng.save({"name": "a", "trigger": {"type": "event", "event": "mention.found"},
                  "actions": [{"type": "create_draft", "platform": "bluesky", "text": "Thanks {{data.author}}"},
                              {"type": "ask_agent", "agent": "friday", "message": "reply to {{data.text}}"}]})
    dbm.ACTIVE_BRAND.update({"name": "Other"})  # the owner switched brands after creating it
    r = await eng.run(eng.get(a["id"]), {"event": "mention.found", "data": {"author": "@x", "text": "hi"}})
    assert r["ok"]
    from sqlalchemy import select

    from stark.core.db import ContentItem, Task
    with k.db.session() as s:
        assert [c.brand for c in s.scalars(select(ContentItem)).all()] == ["Acme"]
        assert [t.brand for t in s.scalars(select(Task)).all()] == ["Acme"]
    assert dbm.current_brand()["name"] == "Other"  # the automation's brand never leaks out of its run
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


def test_memory_tokens_are_stemmed():
    assert _tokens("Posting posts posted") == ["post", "post", "post"]
    assert _tokens("stories") == ["story"]


def test_captions_and_command_building(tmp_path):
    srt = video.captions_from_script("Hello there. This is our new launch video, and it is short!", 6.0)
    assert srt.startswith("1\n00:00:00,000 --> ") and "launch" in srt
    assert video.check_srt(srt)
    with pytest.raises(video.VideoError):
        video.check_srt("not captions")
    info = {"duration": 200.0, "width": 1920, "height": 1080, "audio": True}
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    cmd = video.build_command("ffmpeg", src, out, info, {"preset": "vertical", "format": "mp4", "fit": "crop",
                                                         "start": 10, "captions": "burn"}, "c.srt")
    vf = cmd[cmd.index("-vf") + 1]
    assert "crop=1080:1920" in vf and "subtitles=c.srt" in vf
    assert cmd[cmd.index("-to") + 1] == "100.000"  # vertical clips are capped at 90 s
    soft = video.build_command("ffmpeg", src, out, info, {"preset": "original", "format": "mp4",
                                                          "captions": "track"}, "c.srt")
    assert "mov_text" in soft and "-vf" not in soft
    with pytest.raises(video.VideoError):
        video.build_command("ffmpeg", src, out, info, {"preset": "square", "format": "mp4", "start": 199.9}, None)


def test_upload_rejects_non_video(client):
    r = client.post("/api/video/upload?name=x.mp4", content=b"not a video at all")
    assert r.status_code == 400
    assert client.post("/api/video/upload?name=x.exe", content=b"\x00\x00\x00\x18ftypmp42").status_code == 400
    assert client.get("/api/video/file?name=../../etc/passwd").status_code == 404


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_real_export_thumbnail_and_captions(client, settings):
    exe = video.ffmpeg_path()
    sample = settings.workspace_roots[0] / "sample.mp4"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(sample)], check=True, timeout=60)
    up = client.post("/api/video/upload?name=clip.mp4", content=sample.read_bytes()).json()
    home = client.get("/api/video").json()
    assert home["ffmpeg"]["available"] and up["name"] in [f["name"] for f in home["files"]]
    job = client.post("/api/video/export", json={"file": up["name"], "preset": "square", "format": "mp4",
                                                 "start": 0.5, "end": 2.5, "captions": "track",
                                                 "script": "Hello world from the studio"}).json()
    for _ in range(100):
        j = next(x for x in client.get("/api/video").json()["jobs"] if x["id"] == job["id"])
        if j["status"] in ("done", "failed"):
            break
        import time
        time.sleep(0.2)
    assert j["status"] == "done", j
    info = video.probe(exe, video.Studio(settings).path(j["output"]))
    assert (info["width"], info["height"]) == (1080, 1080) and 1.5 <= info["duration"] <= 2.6
    assert client.get(f"/api/video/file?name={j['captions']}").text.startswith("1\n")
    thumb = client.post("/api/video/thumbnail", json={"file": up["name"], "at": 1}).json()
    assert thumb["file"].startswith("media/generated/") and thumb["file"].endswith(".jpg")
    assert any(i["name"] == thumb["name"] for i in client.get("/api/media").json()["images"])
    assert shutil.which(exe) or exe
