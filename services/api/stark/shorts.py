"""Content autopilot for video: long video → highlight clips → vertical Shorts with captions and thumbnails →
titles, hooks, descriptions and hashtags → drafts for each platform (still waiting for your approval).

Highlights come from the transcript: U (an agent, on your AI model) picks the strongest moments from candidate
clips cut at sentence ends; without a model a transparent rule picks them. Nothing here publishes.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from . import brands as brand_mod
from . import video
from .core.db import TASK_BRAND, current_brand
from .core.observability import log
from .tools import social as social_tools

PICK_GUIDE = """You choose the best moments of a long video for short vertical clips (Shorts, Reels, TikTok).
You get numbered candidate clips with their time and transcript. Pick the ones that work on their own: a clear point,
a strong opening line, a surprise, a useful tip or a question answered. Never invent facts that are not in the clip.
Answer with JSON only:
{"clips": [{"index": <candidate number>, "title": "<max 70 chars, searchable>", "hook": "<first line of the post,
max 120 chars>", "description": "<1-2 sentences, max 300 chars>", "hashtags": ["#tag", ...max 5], "why": "<short>"}]}"""
STOP = set("about above after again against because been before being below between both could does doing down during "
           "each from further have having here into itself just more most other over same should some such than that "
           "their theirs them then there these they this those through under until very were what when where which "
           "while will with would your yours really thing things going gonna want know like make made also only".split())


class PackageError(ValueError):
    pass


def score_clip(c: dict[str, Any]) -> float:
    """Rule used when no AI model is connected: dense, punchy speech with a question, number or direct address."""
    text, dur = c["text"], max(1.0, c["end"] - c["start"])
    words = len(text.split())
    s = min(3.5, words / dur)  # words per second
    s += 1.0 if "?" in text else 0
    s += 0.7 if re.search(r"\d", text) else 0
    s += 0.5 if re.search(r"\b(you|your)\b", text, re.I) else 0
    s += 0.4 if text.rstrip().endswith("!") else 0
    s -= 1.0 if dur < 12 else 0
    return round(s, 3)


def rule_hashtags(text: str, n: int = 3) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z]{4,}", text) if w.lower() not in STOP]
    return [f"#{w}" for w, _ in Counter(words).most_common(n)]


def rule_pick(cands: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ranked = sorted(range(len(cands)), key=lambda i: score_clip(cands[i]), reverse=True)[:count]
    out = []
    for i in sorted(ranked):
        c = cands[i]
        first = re.split(r"(?<=[.!?])\s+", c["text"].strip())[0]
        out.append({"index": i, "title": first[:70], "hook": first[:120], "description": c["text"][:300],
                    "hashtags": rule_hashtags(c["text"]), "why": f"rule score {score_clip(c)}"})
    return out


def clean_pick(raw: Any, cands: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Keep only valid picks from a model answer (real indices, sane text, real-looking hashtags)."""
    out, seen = [], set()
    for p in (raw or [])[: count * 2]:
        try:
            i = int(p.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 0 <= i < len(cands) or i in seen:
            continue
        seen.add(i)
        tags = [t if t.startswith("#") else f"#{t}" for t in (p.get("hashtags") or []) if isinstance(t, str)]
        tags = [t for t in tags if re.fullmatch(r"#\w{2,40}", t)][:5]
        out.append({"index": i, "title": str(p.get("title") or cands[i]["text"])[:70].strip(),
                    "hook": str(p.get("hook") or "")[:120].strip(), "description": str(p.get("description") or "")[:300].strip(),
                    "hashtags": tags, "why": str(p.get("why") or "")[:200]})
        if len(out) >= count:
            break
    return sorted(out, key=lambda x: x["index"])


def post_text(platform: str, pick: dict[str, Any]) -> str:
    """One platform's caption, within its length and hashtag limits."""
    spec = social_tools.PLATFORMS[platform]
    tags = " ".join(pick["hashtags"][: spec.get("hashtags", 5)])
    body = "\n\n".join(x for x in (pick["hook"], pick["description"]) if x)
    budget = spec["limit"] - (len(tags) + 2 if tags else 0)
    if social_tools.weighted_length(platform, body) > budget:
        body = body[: max(20, budget - 1)].rsplit(" ", 1)[0] + "…"
    return body + (f"\n\n{tags}" if tags else "")


async def _pick(kernel, cands: list[dict[str, Any]], count: int, title: str) -> tuple[list[dict[str, Any]], str]:
    if not kernel.router.configured_providers():
        return rule_pick(cands, count), "rules"
    listing = "\n".join(f"[{i}] {c['start']:.1f}-{c['end']:.1f}s: {c['text']}" for i, c in enumerate(cands))[:12000]
    b = brand_mod.by_name(kernel, current_brand().get("name", ""))
    prompt = ((brand_mod.brief(b) + "\n\n") if b else "") + (
        f"Video: {title}\nPick the {count} best clips.\n<<<TRANSCRIPT (untrusted data)\n{listing}\nTRANSCRIPT>>>")
    try:
        from .autopilot import parse_json

        agent = kernel.registry.get("u")
        task = kernel._create_task(agent_id="u", kind="autopilot", requested_by="video", agent_chain=["u"],
                                   instruction=f"Pick {count} highlight clips from {title}")
        kernel._transition(task["id"], "thinking")
        resp = await kernel._call_model(agent, task, agent.system_prompt.strip() + "\n\n" + PICK_GUIDE,
                                        [{"role": "user", "content": prompt}], [])
        kernel._transition(task["id"], "completed", result=resp.text[:4000])
        picks = clean_pick(parse_json(resp.text).get("clips"), cands, count)
        if picks:
            return picks, "agent"
    except Exception as exc:  # noqa: BLE001 - the rule still gives a usable package
        log.warning(f"highlight picking fell back to rules: {exc}")
    return rule_pick(cands, count), "rules"


async def _wait(studio: video.Studio, job_id: str, parent: dict[str, Any]) -> dict[str, Any]:
    while True:
        j = studio.jobs[job_id]
        if parent["status"] == "cancelled" and j["status"] in ("queued", "running"):
            studio.cancel(job_id)
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        await asyncio.sleep(0.3)


def packages(studio: video.Studio, name: str) -> list[dict[str, Any]]:
    p = studio.path(name)
    f = p.with_name(p.name + ".packages.json")
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []


def start(kernel, social, settings, studio: video.Studio, opts: dict[str, Any]) -> dict[str, Any]:
    src = studio.path(str(opts.get("file") or ""))
    tp = src.with_name(src.name + ".transcript.json")
    if not tp.is_file():
        raise video.VideoError("Transcribe the video first (Speech to text)")
    platforms = [p for p in opts.get("platforms") or [] if p in social_tools.PLATFORMS] or ["tiktok", "instagram", "youtube"]
    count = min(5, max(1, int(opts.get("count") or 3)))
    job = studio._new_job("package", file=src.name, count=count, platforms=platforms, clips=[], picked_by=None)
    brand = current_brand().get("name", "")  # the package keeps the brand it was started for

    async def run() -> None:
        TASK_BRAND.set(brand_mod.task_context(kernel, brand))
        try:
            await _run(kernel, social, settings, studio, job, src, tp, opts, platforms, count)
        except Exception as exc:  # noqa: BLE001 - reported on the job
            if job["status"] != "cancelled":
                job.update(status="failed", error=str(exc)[:300])
    asyncio.get_running_loop().create_task(run())
    return job


async def _run(kernel, social, settings, studio, job, src: Path, tp: Path, opts, platforms, count) -> None:
    from . import hub

    job["status"] = "running"
    segs = json.loads(tp.read_text(encoding="utf-8"))["segments"]
    cands = video.plan_clips(segs, max_s=float(opts.get("max_seconds") or 60), min_s=15)
    if not cands:
        raise PackageError("Not enough speech in this video for clips")
    picks, how = await _pick(kernel, cands, count, src.stem)
    job["picked_by"] = how
    style = opts.get("style") or {"size": 16, "color": "white", "position": "bottom", "box": True}
    results = []
    for n, pick in enumerate(picks):
        if job["status"] == "cancelled":
            return
        c = cands[pick["index"]]
        ex = studio.start({"file": src.name, "preset": "vertical", "format": "mp4", "fit": "crop", "start": c["start"],
                           "end": c["end"], "captions": "burn" if video.status().get("burn_captions") else "track",
                           "caption_source": "transcript", "style": style,
                           "animation": opts.get("animation") or "pop"})
        done = await _wait(studio, ex["id"], job)
        if done["status"] != "done":
            raise PackageError(f"Clip {n + 1} could not be made: {done.get('error') or done['status']}")
        thumb = await studio.thumbnail(src.name, c["start"] + min(1.0, (c["end"] - c["start"]) / 3))
        drafts = []
        for p in platforms:
            try:
                media = ([{"file": f"{video.VIDEO_DIR}/{done['output']}", "alt_text": str(pick.get("title") or "")[:200]}]
                         if p in social_tools.VIDEO_PLATFORMS and done.get("output") else [])
                d = hub.create_draft(kernel, social, settings, {"platform": p, "kind": "video", "text": post_text(p, pick),
                                                               "campaign": f"shorts: {src.stem}"[:120], "media": media},
                                     created_by="video-autopilot")
                drafts.append({"platform": p, "id": d["id"]})
            except Exception as exc:  # noqa: BLE001 - one platform failing doesn't lose the clip
                drafts.append({"platform": p, "error": str(exc)[:200]})
        results.append({**pick, "start": c["start"], "end": c["end"], "transcript": c["text"], "video": done["output"],
                        "captions": done.get("captions"), "thumbnail": thumb["file"], "drafts": drafts})
        job["clips"] = results
        job["progress"] = (n + 1) / len(picks)
    record = {"created": job["created"], "brand": current_brand().get("name", ""), "picked_by": how, "clips": results}
    f = src.with_name(src.name + ".packages.json")
    old = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
    f.write_text(json.dumps([record] + old[:19]), encoding="utf-8")
    job.update(status="done", progress=1.0, output=results[0]["video"] if results else None)
