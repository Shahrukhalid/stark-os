"""Social media layer: policy checks, queue, approvals, adapters (HTTP shapes), simulation honesty, brains."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from stark.core.db import Approval, ContentItem, to_dict
from stark.core.runtime import ToolContext
from stark.core.workflows import verify_content_claims
from stark.providers.openrouter import OpenRouterProvider
from stark.tools import social
from stark.tools.social import (BlueskyAdapter, MastodonAdapter, Social, SocialAnalytics, SocialInbox,
                                bluesky_facets, check_post, triage)

from .conftest import last_tool_results, make_kernel, n_tool_rounds, text, tool, wait_for


def _ctx(k, agent_id):
    t = k._create_task(agent_id=agent_id, instruction="t")
    return ToolContext(kernel=k, agent=k.registry.get(agent_id), task_id=t["id"], root_id=t["id"], settings=k.settings)


def _pending(k):
    with k.db.session() as s:
        return [to_dict(a) for a in s.scalars(select(Approval).where(Approval.status == "pending")).all()]


async def _draft(k, agent="edith", **kw):
    args = {"platform": "bluesky", "text": "Our new feature ships today. Details: https://example.com/launch #launch"}
    args.update(kw)
    res = await k.tools.get("social.draft").run(k.tools.get("social.draft").Input(**args), _ctx(k, agent))
    assert res.ok, res.summary
    return res.data


# ------------------------------------------------------------------ checks
def test_policy_check_rules():
    ok = check_post("bluesky", "Hello Bluesky! https://example.com #hello")
    assert ok["verdict"] == "pass"
    assert check_post("x", "a" * 281)["verdict"] == "fail"
    # X counts every link as 23 characters
    assert check_post("x", "a" * 250 + " https://example.com/" + "b" * 60)["length"] == 274
    assert any(i["code"] == "secret" for i in check_post("mastodon", "key sk-or-v1-" + "a" * 64)["issues"])
    sponsored = check_post("instagram", "Love this serum", sponsored=True, media=[{"description": "bottle", "alt_text": "a"}])
    assert any(i["code"] == "missing_disclosure" for i in sponsored["issues"])
    assert check_post("instagram", "Love this serum #ad", sponsored=True,
                      media=[{"description": "bottle", "alt_text": "a"}])["verdict"] == "pass"
    assert any(i["code"] == "needs_media" for i in check_post("tiktok", "dance")["issues"])
    assert check_post("linkedin", "Buy followers cheap")["verdict"] == "fail"
    codes = {i["code"] for i in check_post("x", "GIVEAWAY! Like and share to win. bit.ly http://bit.ly/x")["issues"]}
    assert {"engagement_bait", "giveaway_rules", "shortened_link", "insecure_link"} <= codes
    assert any(i["code"] == "blocked_term" for i in check_post("bluesky", "This is lit", blocked_terms=["lit"])["issues"])
    assert any(i["code"] == "personal_data" for i in check_post("bluesky", "Call Sam on 555-123-4567")["issues"])
    assert not any(i["code"] == "personal_data" for i in check_post("bluesky", "Launch on 2026-10-16")["issues"])
    assert any(i["code"] == "alt_text" for i in check_post("bluesky", "pic", media=[{"description": "x"}])["issues"])
    assert check_post("bluesky", "hi", kind="reply")["verdict"] == "fail"  # reply without a target


def test_triage_labels():
    assert triage("Your app leaked my data, I'm calling a lawyer")["category"] == "escalate"
    assert triage("you idiot")["category"] == "abuse"
    assert triage("crypto airdrop, check my profile")["category"] == "spam"
    assert triage("My order never arrived")["category"] == "complaint"
    assert triage("When is the next drop?")["category"] == "question"
    assert triage("Loved it, thanks!")["category"] == "praise"
    assert triage("the latest translation")["category"] == "general"  # no substring false positives


def test_bluesky_facets_use_utf8_byte_offsets():
    t = "Café 🚀 https://example.com #news"
    facets = bluesky_facets(t)
    link = next(f for f in facets if "link" in f["features"][0]["$type"])
    b = t.encode()
    assert b[link["index"]["byteStart"]:link["index"]["byteEnd"]].decode() == "https://example.com"
    tag = next(f for f in facets if "tag" in f["features"][0]["$type"])
    assert tag["features"][0]["tag"] == "news"


# ------------------------------------------------------------------ queue & approvals
async def test_draft_schedule_and_simulated_publish_with_approval(settings):
    def brain(agent, req):
        if agent == "dum_e" and n_tool_rounds(req) == 0:
            item_id = req.messages[-1]["content"].split()[-1]
            return [tool("social.publish", {"item_id": item_id})]
        if agent == "dum_e":
            return [text(f"*whirr* {item_id_box[0]} result: " + last_tool_results(req)[0]["content"][:300])]
        return [text("?")]

    item_id_box: list[str] = []
    k, _ = make_kernel(settings, brain)
    item = await _draft(k)
    item_id_box.append(item["id"])
    assert item["status"] == "draft" and item["check"]["verdict"] == "pass"
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    sch = await k.tools.get("social.schedule").run(k.tools.get("social.schedule").Input(item_id=item["id"], when=when),
                                                  _ctx(k, "dum_e"))
    assert sch.ok and sch.data["status"] == "scheduled"
    task = k.submit_chat("dum_e", f"publish {item['id']}")
    ap = await wait_for(lambda: _pending(k))
    assert ap[0]["tool_id"] == "social.publish"
    assert "SIMULATION ONLY" in ap[0]["expected_effects"] and "Our new feature ships today" in ap[0]["expected_effects"]
    with k.db.session() as s:
        assert s.get(ContentItem, item["id"]).status == "scheduled"  # nothing happens before approval
    k.approvals.decide(ap[0]["id"], "approved")
    done = await k.wait(task["id"], 10)
    assert done["status"] == "completed"
    assert "SIMULATED publish" in done["result"]
    assert "published (SIMULATED)" in done["result"]  # verified status block appended by the platform
    with k.db.session() as s:
        row = s.get(ContentItem, item["id"])
        assert row.status == "published" and row.simulated and row.external_url is None


async def test_rejected_publish_leaves_item_untouched(settings):
    k, _ = make_kernel(settings, lambda a, r: [tool("social.publish", {"item_id": item_id})]
                       if n_tool_rounds(r) == 0 else [text("rejected: " + last_tool_results(r)[0]["content"][:200])])
    item_id = (await _draft(k))["id"]
    task = k.submit_chat("dum_e", "publish it")
    ap = await wait_for(lambda: _pending(k))
    k.approvals.decide(ap[0]["id"], "rejected")
    done = await k.wait(task["id"], 10)
    assert done["status"] == "completed"
    with k.db.session() as s:
        assert s.get(ContentItem, item_id).status == "draft"


async def test_publish_gates(settings):
    k, _ = make_kernel(settings)
    pub = k.tools.get("social.publish")
    bad = await _draft(k, text="secret sk-or-v1-" + "a" * 64)
    assert bad["check"]["verdict"] == "fail"
    res = await pub.run(pub.Input(item_id=bad["id"]), _ctx(k, "dum_e"))
    assert not res.ok and res.error == "check_failed"
    good = await _draft(k)
    rev = k.tools.get("social.review")
    await rev.run(rev.Input(item_id=good["id"], verdict="block", notes="Off-brand claim"), _ctx(k, "jarvis"))
    res = await pub.run(pub.Input(item_id=good["id"]), _ctx(k, "dum_e"))
    assert not res.ok and res.error == "blocked"
    # editing clears the block; pausing the queue stops publishing again
    ed = k.tools.get("social.edit")
    await ed.run(ed.Input(item_id=good["id"], text="Our new feature ships today."), _ctx(k, "edith"))
    social.pause_queue(k, True)
    res = await pub.run(pub.Input(item_id=good["id"]), _ctx(k, "dum_e"))
    assert not res.ok and res.error == "paused"
    social.pause_queue(k, False)
    res = await pub.run(pub.Input(item_id=good["id"]), _ctx(k, "dum_e"))
    assert res.ok and res.simulated
    again = await pub.run(pub.Input(item_id=good["id"]), _ctx(k, "dum_e"))
    assert not again.ok and again.error == "not_publishable"  # never double-post


def test_only_dum_e_publishes_and_only_jarvis_reviews(settings):
    k, _ = make_kernel(settings)
    for agent in ("jarvis", "friday", "edith", "ultron", "jocasta", "u"):
        assert "social.publish" not in k.registry.get(agent).tools
    assert k.tools.get("social.publish").allowed_agents == {"dum_e"}
    assert k.tools.get("social.review").allowed_agents == {"jarvis"}


async def test_resume_after_pause_needs_approval_and_estop_pauses(settings):
    k, _ = make_kernel(settings)
    item = await _draft(k)
    tool_ = k.tools.get("social.pause_queue")
    agent = k.registry.get("dum_e")
    assert k.perms.decide(agent, tool_, tool_.Input(paused=True), _ctx(k, "dum_e")).verdict.value == "allow"
    assert k.perms.decide(agent, tool_, tool_.Input(paused=False), _ctx(k, "dum_e")).verdict.value == "approval"
    k.engage_emergency_stop()
    with k.db.session() as s:
        assert s.get(ContentItem, item["id"]).paused
    k.reset_emergency_stop()
    with k.db.session() as s:
        assert s.get(ContentItem, item["id"]).paused  # stays paused until resumed with approval


def test_content_claim_check():
    items = {"cnt_0123456789abcdef": {"status": "draft", "platform": "x", "check": {"verdict": "pass"}}}
    out, meta = verify_content_claims("Done! cnt_0123456789abcdef has been published.", items.get)
    assert meta["unsupported_publish_claim"] and "claim is not supported" in out
    out, meta = verify_content_claims("Draft cnt_ffffffffffffffff is ready", items.get)
    assert meta["missing_content_ids"] == ["cnt_ffffffffffffffff"] and "NOT FOUND" in out
    out, meta = verify_content_claims("Nothing to report.", items.get)
    assert out == "Nothing to report." and not meta["unsupported_publish_claim"]


# ------------------------------------------------------------------ inbox & analytics
async def test_simulated_inbox_is_labelled(settings):
    k, _ = make_kernel(settings)
    res = await SocialInbox(Social(settings)).run(SocialInbox.Input(), _ctx(k, "friday"))
    assert res.simulated and res.summary.startswith("SIMULATED")
    assert res.data["messages"][0]["triage"]["priority"] == "high"
    assert all(m["author"].endswith(".example") for m in res.data["messages"])
    assert "UNTRUSTED" in res.data["notice"]


async def test_analytics_never_invents_numbers_for_simulated_posts(settings):
    k, _ = make_kernel(settings)
    item = await _draft(k)
    pub = k.tools.get("social.publish")
    await pub.run(pub.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    res = await SocialAnalytics(Social(settings)).run(SocialAnalytics.Input(), _ctx(k, "jocasta"))
    assert res.data["posts"][0]["engagement"] == "no engagement data: simulated publish"
    assert res.data["totals"] is None and "0 with real engagement data" in res.summary


# ------------------------------------------------------------------ real adapters (recorded HTTP shapes)
def _bsky_transport(seen):
    def handler(req: httpx.Request):
        path = req.url.path
        if path.endswith("createSession"):
            body = json.loads(req.content)
            seen["login"] = body
            return httpx.Response(200, json={"accessJwt": "jwt-1", "did": "did:plc:abc", "handle": "brand.bsky.social"})
        assert req.headers["authorization"] == "Bearer jwt-1"
        if path.endswith("getRecord"):
            rkey = req.url.params["rkey"]
            if rkey in seen.get("stored", {}):
                return httpx.Response(200, json=seen["stored"][rkey])
            return httpx.Response(400, json={"error": "RecordNotFound"})
        if path.endswith("createRecord"):
            body = json.loads(req.content)
            seen.setdefault("records", []).append(body["record"])
            seen.setdefault("rkeys", []).append(body["rkey"])
            n = len(seen["records"])
            return httpx.Response(200, json={"uri": f"at://did:plc:abc/app.bsky.feed.post/rk{n}", "cid": f"cid{n}"})
        if path.endswith("listNotifications"):
            return httpx.Response(200, json={"notifications": [
                {"reason": "like", "uri": "at://x/1", "author": {"handle": "a"}, "record": {}},
                {"reason": "mention", "uri": "at://x/2", "author": {"handle": "fan.bsky.social"},
                 "record": {"text": "When is the next drop?"}, "indexedAt": "2026-10-16T10:00:00Z"}]})
        if path.endswith("getPosts"):
            return httpx.Response(200, json={"posts": [{"uri": "at://did:plc:abc/app.bsky.feed.post/rk1", "cid": "cid1",
                                                        "likeCount": 7, "repostCount": 2, "replyCount": 1}]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_bluesky_adapter_publishes_threads_and_reads(settings):
    settings.bluesky_handle, settings.bluesky_app_password = "brand.bsky.social", "app-pass-1234"
    seen: dict = {}
    k, _ = make_kernel(settings)
    sc = Social(settings, _bsky_transport(seen))
    assert sc.adapter("bluesky") is not None and sc.adapter("x") is None
    item = await _draft(k, thread=["Part two #launch"])
    pub = social.SocialPublish(sc)
    res = await pub.run(pub.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    assert res.ok and not res.simulated
    assert res.data["external_url"] == "https://bsky.app/profile/brand.bsky.social/post/rk1"
    assert seen["login"] == {"identifier": "brand.bsky.social", "password": "app-pass-1234"}
    first, second = seen["records"]
    assert "facets" in first and "reply" not in first
    assert len(set(seen["rkeys"])) == 2 and all(len(k) == 13 and k[0] in "234567abcdefghij" for k in seen["rkeys"])
    assert second["reply"]["root"]["uri"].endswith("rk1") and second["reply"]["parent"]["uri"].endswith("rk1")
    inbox = await SocialInbox(sc).run(SocialInbox.Input(), _ctx(k, "friday"))
    assert not inbox.simulated and [m["author"] for m in inbox.data["messages"]] == ["@fan.bsky.social"]
    stats = await SocialAnalytics(sc).run(SocialAnalytics.Input(), _ctx(k, "jocasta"))
    assert stats.data["totals"] == {"likes": 7, "reposts": 2, "replies": 1}


async def test_bluesky_login_failure_marks_item_failed(settings):
    settings.bluesky_handle, settings.bluesky_app_password = "brand.bsky.social", "wrong-pass"
    k, _ = make_kernel(settings)
    sc = Social(settings, httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "AuthenticationRequired"})))
    item = await _draft(k)
    res = await social.SocialPublish(sc).run(social.SocialPublish.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    assert not res.ok and res.error == "platform_error" and "wrong-pass" not in res.summary
    with k.db.session() as s:
        assert s.get(ContentItem, item["id"]).status == "failed"


async def test_mastodon_adapter(settings):
    settings.mastodon_base_url, settings.mastodon_access_token = "https://social.example", "masto-token-123"
    seen: dict = {}

    def handler(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer masto-token-123"
        if req.method == "POST" and req.url.path == "/api/v1/statuses":
            seen.setdefault("posts", []).append((dict(httpx.QueryParams(req.content.decode())),
                                                req.headers.get("idempotency-key")))
            n = len(seen["posts"])
            return httpx.Response(200, json={"id": str(100 + n), "url": f"https://social.example/@brand/{100 + n}"})
        if req.url.path == "/api/v1/notifications":
            return httpx.Response(200, json=[{"type": "mention", "account": {"acct": "fan@other.example"},
                                              "status": {"id": "9", "content": "<p>Love it &amp; thanks!</p>"}}])
        if req.url.path == "/api/v1/statuses/101":
            return httpx.Response(200, json={"favourites_count": 3, "reblogs_count": 1, "replies_count": 0})
        return httpx.Response(404)

    k, _ = make_kernel(settings)
    sc = Social(settings, httpx.MockTransport(handler))
    item = await _draft(k, platform="mastodon", thread=["second"])
    res = await social.SocialPublish(sc).run(social.SocialPublish.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    assert res.ok and res.data["external_url"] == "https://social.example/@brand/101"
    (p1, key1), (p2, _) = seen["posts"]
    assert p1["visibility"] == "public" and "in_reply_to_id" not in p1 and p2["in_reply_to_id"] == "101"
    assert key1 == f"{item['id']}-0"
    inbox = await SocialInbox(sc).run(SocialInbox.Input(platform="mastodon"), _ctx(k, "friday"))
    assert inbox.data["messages"][0]["text"] == "Love it & thanks!"
    stats = await SocialAnalytics(sc).run(SocialAnalytics.Input(), _ctx(k, "jocasta"))
    assert stats.data["totals"]["likes"] == 3


def test_mastodon_requires_https(settings):
    settings.mastodon_base_url, settings.mastodon_access_token = "http://social.example", "t" * 12
    assert MastodonAdapter(settings).connected() is False
    assert BlueskyAdapter(settings).connected() is False


# ------------------------------------------------------------------ brains & identity
def test_each_agent_has_its_own_brain(settings):
    k, _ = make_kernel(settings)
    agents = k.registry.all()
    firsts = [a.model.preferred[0] for a in agents]
    assert all(m.endswith(":free") for a in agents for m in a.model.preferred)
    assert len(set(firsts)) >= 6  # (almost) every agent thinks with a different first-choice model
    pool = OpenRouterProvider("sk-test")
    for a in agents:
        assert pool.candidates(a.model.tier, preferred=a.model.preferred)[0] == a.model.preferred[0]
    # a cooled-down brain falls back to the shared tier list instead of failing
    import time

    from stark.providers.openrouter import ModelHealth

    jarvis = k.registry.get("jarvis")
    pool.model_health[jarvis.model.preferred[0]] = ModelHealth(cooldown_until=time.time() + 60)
    assert pool.candidates("deep", preferred=jarvis.model.preferred)[0] == jarvis.model.preferred[1]


def test_visionquest_roles_and_u_is_mute(settings):
    k, _ = make_kernel(settings)
    u = k.registry.get("u")
    assert u.voice.muted and all(not a.voice.muted for a in k.registry.all() if a.id != "u")
    for a in k.registry.all():
        assert any("[established]" in c for c in a.canon_notes)
        assert any("VisionQuest" in c for c in a.canon_notes)
    assert k.registry.get("dum_e").workflow == "publishing" and "social.pause_queue" in k.registry.get("dum_e").tools
    ultron = k.registry.get("ultron")
    assert not [t for t in ultron.tools if t.startswith(("web.", "browser.", "agent.", "social.publish"))]


# ------------------------------------------------------------------ hardening (review of the social layer)
async def test_edit_after_approval_is_not_published(settings):
    """TOCTOU: the user approves the text they saw; if the item changes before it runs, nothing is posted."""
    k, _ = make_kernel(settings, lambda a, r: [tool("social.publish", {"item_id": box[0]})]
                       if n_tool_rounds(r) == 0 else [text(last_tool_results(r)[0]["content"][:300])])
    box: list[str] = []
    box.append((await _draft(k))["id"])
    task = k.submit_chat("dum_e", "publish it")
    ap = await wait_for(lambda: _pending(k))
    ed = k.tools.get("social.edit")
    await ed.run(ed.Input(item_id=box[0], text="Totally different text"), _ctx(k, "edith"))
    k.approvals.decide(ap[0]["id"], "approved")
    done = await k.wait(task["id"], 10)
    assert "changed after you approved it" in done["result"]
    with k.db.session() as s:
        assert s.get(ContentItem, box[0]).status == "draft"


async def test_partial_thread_is_recorded_as_published_never_retried(settings):
    settings.mastodon_base_url, settings.mastodon_access_token = "https://social.example", "masto-token-123"
    calls = {"n": 0}

    def handler(req: httpx.Request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"id": "201", "url": "https://social.example/@b/201"})
        return httpx.Response(500, text="boom")

    k, _ = make_kernel(settings)
    sc = Social(settings, httpx.MockTransport(handler))
    item = await _draft(k, platform="mastodon", thread=["part two"])
    pub = social.SocialPublish(sc)
    res = await pub.run(pub.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    assert not res.ok and res.error == "partial_publish"
    again = await pub.run(pub.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    assert again.error == "not_publishable" and calls["n"] == 2  # no double post


def test_check_tool_is_read_only_and_links_exclude_punctuation(settings):
    assert check_post("x", "See https://example.com.")["length"] == len("See ") + 23 + 1
    assert bluesky_facets("Go to https://example.com, now")[0]["features"][0]["uri"] == "https://example.com"


def test_claim_check_ignores_negations_and_research():
    from stark.core.workflows import post_process

    lookup = {}.get
    out, meta = verify_content_claims("Nothing has been published yet; the draft is ready.", lookup)
    assert not meta["unsupported_publish_claim"]
    out, meta = post_process("research", "The competitor's video was posted on Monday.", [], lookup)
    assert "unsupported_publish_claim" not in meta
    out, meta = post_process("publishing", "Done, it was posted!", [], lookup)
    assert meta["unsupported_publish_claim"]


async def test_bluesky_retry_after_interruption_never_double_posts(settings):
    """If part 1 went out and the process died, a retry reuses the deterministic record key."""
    settings.bluesky_handle, settings.bluesky_app_password = "brand.bsky.social", "app-pass-1234"
    seen: dict = {"stored": {}}
    k, _ = make_kernel(settings)
    item = await _draft(k)
    rkey = social.tid_for(item["id"], item["created_at"] if "created_at" in item else
                          k._content_item(item["id"])["created_at"], 0)
    seen["stored"][rkey] = {"uri": f"at://did:plc:abc/app.bsky.feed.post/{rkey}", "cid": "cid-old"}
    sc = Social(settings, _bsky_transport(seen))
    res = await social.SocialPublish(sc).run(social.SocialPublish.Input(item_id=item["id"]), _ctx(k, "dum_e"))
    assert res.ok and "records" not in seen  # nothing new was created
    assert res.data["external_url"].endswith(rkey)


async def test_cancellation_mid_thread_records_the_public_part(settings):
    import asyncio

    settings.mastodon_base_url, settings.mastodon_access_token = "https://social.example", "masto-token-123"
    gate = asyncio.Event()

    async def handler(req: httpx.Request):
        if req.headers.get("idempotency-key", "").endswith("-0"):
            return httpx.Response(200, json={"id": "301", "url": "https://social.example/@b/301"})
        await gate.wait()  # hang on part two
        return httpx.Response(200, json={"id": "302"})

    k, _ = make_kernel(settings)
    sc = Social(settings, httpx.MockTransport(handler))
    item = await _draft(k, platform="mastodon", thread=["part two"])
    job = asyncio.create_task(social.SocialPublish(sc).run(social.SocialPublish.Input(item_id=item["id"]),
                                                           _ctx(k, "dum_e")))
    await wait_for(lambda: k._content_item(item["id"])["external_id"] == "301")
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    row = k._content_item(item["id"])
    assert row["status"] == "published" and "thread incomplete" in row["error"]


async def test_concurrent_publish_of_same_item_posts_once(settings):
    import asyncio

    settings.mastodon_base_url, settings.mastodon_access_token = "https://social.example", "masto-token-123"
    posts = []

    async def handler(req: httpx.Request):
        posts.append(1)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"id": "401", "url": "https://social.example/@b/401"})

    k, _ = make_kernel(settings)
    sc = Social(settings, httpx.MockTransport(handler))
    item = await _draft(k, platform="mastodon")
    pub = social.SocialPublish(sc)
    a, b = await asyncio.gather(pub.run(pub.Input(item_id=item["id"]), _ctx(k, "dum_e")),
                                pub.run(pub.Input(item_id=item["id"]), _ctx(k, "dum_e")))
    assert sorted([a.ok, b.ok]) == [False, True] and len(posts) == 1


async def test_global_pause_covers_failed_and_new_drafts_and_utc_schedule(settings):
    k, _ = make_kernel(settings)
    old = await _draft(k)
    with k.db.session() as s:
        s.get(ContentItem, old["id"]).status = "failed"
    k.engage_emergency_stop()
    k.reset_emergency_stop()
    new = await _draft(k)
    pub = k.tools.get("social.publish")
    for it in (old, new):
        res = await pub.run(pub.Input(item_id=it["id"]), _ctx(k, "dum_e"))
        assert res.error == "paused"
    social.pause_queue(k, False)
    sch = k.tools.get("social.schedule")
    when = datetime.now(timezone(timedelta(hours=5))) + timedelta(hours=1)
    res = await sch.run(sch.Input(item_id=new["id"], when=when), _ctx(k, "dum_e"))
    stored = datetime.fromisoformat(res.data["scheduled_for"])
    assert abs((stored - when).total_seconds()) < 1  # same instant, whatever the offset
    assert social.list_queue(k)[0]["due"] is False


def test_facets_do_not_overlap_and_claims_use_tool_results():
    facets = bluesky_facets("See https://example.com/#top #news")
    assert [f["features"][0]["$type"].rsplit("#", 1)[1] for f in facets] == ["link", "tag"]
    for phrase in ["Done - posted to Bluesky!", "Your post is live on Bluesky.", "It went out at 9am.",
                   "No worries, I published it."]:
        _, meta = verify_content_claims(phrase, {}.get, confirmed_publish=False)
        assert meta["unsupported_publish_claim"], phrase
    _, meta = verify_content_claims("Posted to Bluesky!", {}.get, confirmed_publish=True)
    assert not meta["unsupported_publish_claim"]
