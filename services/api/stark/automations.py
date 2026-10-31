"""Automations: "when this happens, do that" recipes that run inside STARK OS.

trigger  → an event (post.published, mention.found, …), a schedule (daily / weekly) or an incoming webhook
conditions → all must match (equals, contains, greater than, …) on fields of the event
actions  → ask an agent, create a draft, label a mention, add UTM tags to a draft, notify your phone, call a webhook

Safety: no action can publish (publishing always needs your approval); events caused by an automation never
trigger automations again (no loops); each automation runs at most RATE_LIMIT times an hour; webhook calls go
only to https addresses.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select

from .core.db import Automation, AutomationRun, Mention, to_dict, utcnow
from .core.observability import log
from .hub import create_draft, webhook_payload

EVENTS = ["post.drafted", "post.scheduled", "post.published", "post.failed", "mention.found", "approval.needed",
          "autopilot.alert"]
TRIGGERS = ("event", "schedule", "webhook")
OPS = ("equals", "not_equals", "contains", "not_contains", "matches", "greater_than", "less_than", "is_empty",
       "not_empty")
ACTIONS = ("ask_agent", "create_draft", "label_mention", "add_utm", "notify", "webhook")
AGENTS = ("jarvis", "friday", "edith", "ultron", "jocasta", "dum_e", "u")
RATE_LIMIT = 20  # runs per automation per hour
MAX_ACTIONS = 6
TEMPLATE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


class AutomationError(ValueError):
    pass


# ------------------------------------------------------------------ helpers
def lookup(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def render(template: str, payload: dict[str, Any]) -> str:
    """{{data.text}}-style placeholders; unknown fields become empty. Plain substitution, never code."""
    return TEMPLATE.sub(lambda m: "" if lookup(payload, m.group(1)) is None else str(lookup(payload, m.group(1))),
                        template)


def matches(cond: dict[str, Any], payload: dict[str, Any]) -> bool:
    val = lookup(payload, cond["field"])
    want = str(cond.get("value", ""))
    text = "" if val is None else str(val)
    op = cond["op"]
    if op == "equals":
        return text.lower() == want.lower()
    if op == "not_equals":
        return text.lower() != want.lower()
    if op == "contains":
        return any(w.strip().lower() in text.lower() for w in want.split(",") if w.strip())
    if op == "not_contains":
        return not any(w.strip().lower() in text.lower() for w in want.split(",") if w.strip())
    if op == "matches":
        try:
            return re.search(want, text, re.I) is not None
        except re.error:
            return False
    if op in ("greater_than", "less_than"):
        try:
            a, b = float(text), float(want)
        except ValueError:
            return False
        return a > b if op == "greater_than" else a < b
    if op == "is_empty":
        return not text.strip()
    return bool(text.strip())  # not_empty


def clean(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        raise AutomationError("Give the automation a name")
    trig = dict(data.get("trigger") or {})
    if trig.get("type") not in TRIGGERS:
        raise AutomationError("Trigger must be an event, a schedule or a webhook")
    if trig["type"] == "event" and trig.get("event") not in EVENTS:
        raise AutomationError(f"Event must be one of: {', '.join(EVENTS)}")
    if trig["type"] == "schedule":
        if trig.get("every") not in ("day", "week"):
            raise AutomationError("Schedule must repeat every day or every week")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(trig.get("time", ""))):
            raise AutomationError("Schedule time must look like 09:30")
        if trig["every"] == "week" and int(trig.get("weekday", -1)) not in range(7):
            raise AutomationError("Pick a weekday (0 = Monday)")
    trig = {k: trig[k] for k in ("type", "event", "every", "weekday", "time") if k in trig}
    conds = []
    for c in (data.get("conditions") or [])[:10]:
        if c.get("op") not in OPS or not re.fullmatch(r"[\w.]{1,80}", str(c.get("field", ""))):
            raise AutomationError("Each condition needs a field like data.platform and a valid comparison")
        if c["op"] == "matches":
            try:
                re.compile(str(c.get("value", "")))
            except re.error as exc:
                raise AutomationError(f"Bad pattern: {exc}") from None
        conds.append({"field": c["field"], "op": c["op"], "value": str(c.get("value", ""))[:300]})
    acts = []
    for a in (data.get("actions") or [])[:MAX_ACTIONS]:
        t = a.get("type")
        if t not in ACTIONS:
            raise AutomationError(f"Unknown action {t!r}")
        if t == "ask_agent":
            if a.get("agent") not in AGENTS or not str(a.get("message", "")).strip():
                raise AutomationError("Ask an agent: pick an agent and write the message")
            acts.append({"type": t, "agent": a["agent"], "message": str(a["message"])[:4000]})
        elif t == "create_draft":
            from .tools.social import PLATFORMS

            if a.get("platform") not in PLATFORMS or not str(a.get("text", "")).strip():
                raise AutomationError("Create a draft: pick a platform and write the text")
            acts.append({"type": t, "platform": a["platform"], "text": str(a["text"])[:5000],
                         "category": str(a.get("category") or "")[:40]})
        elif t == "label_mention":
            if not str(a.get("label", "")).strip():
                raise AutomationError("Label: write the label")
            acts.append({"type": t, "label": str(a["label"]).strip()[:30]})
        elif t == "add_utm":
            acts.append({"type": t})
        elif t == "notify":
            acts.append({"type": t, "text": str(a.get("text") or "{{event}}: {{data.text}}")[:2000]})
        else:
            url = str(a.get("url", "")).strip()
            if not url.startswith("https://"):
                raise AutomationError("Webhook addresses must start with https://")
            acts.append({"type": t, "url": url[:500]})
    if not acts:
        raise AutomationError("Add at least one action")
    return {"name": name, "trigger": trig, "conditions": conds, "actions": acts,
            "enabled": bool(data.get("enabled", True)), "recipe": str(data.get("recipe") or "")[:60]}


# ------------------------------------------------------------------ recipes (gallery)
RECIPES: list[dict[str, Any]] = [
    {"recipe": "thank-praise", "name": "Thank people who praise us",
     "description": "When Listening finds praise, F.R.I.D.A.Y. drafts a warm thank-you reply for you to approve.",
     "trigger": {"type": "event", "event": "mention.found"},
     "conditions": [{"field": "data.category", "op": "equals", "value": "praise"}],
     "actions": [{"type": "ask_agent", "agent": "friday",
                  "message": "Friday, draft a short, warm thank-you reply on {{data.platform}} to {{data.author}} for this post: \"{{data.text}}\" ({{data.url}}). Reply in their language."}]},
    {"recipe": "urgent-complaints", "name": "Alert me about complaints and crises",
     "description": "Complaints and possible crises found by Listening are labelled Urgent and sent to your phone.",
     "trigger": {"type": "event", "event": "mention.found"},
     "conditions": [{"field": "data.category", "op": "contains", "value": "complaint, escalate"}],
     "actions": [{"type": "label_mention", "label": "Urgent"},
                 {"type": "notify", "text": "🚨 {{data.category}} on {{data.platform}} from {{data.author}}: {{data.text}} {{data.url}}"}]},
    {"recipe": "competitor-viral", "name": "Competitor post going viral",
     "description": "When a competitor post you follow passes 50 likes, you get a phone alert and an idea draft.",
     "trigger": {"type": "event", "event": "mention.found"},
     "conditions": [{"field": "data.kind", "op": "equals", "value": "account"},
                    {"field": "data.likes", "op": "greater_than", "value": "50"}],
     "actions": [{"type": "notify", "text": "🔥 {{data.author}} is taking off ({{data.likes}} likes): {{data.text}} {{data.url}}"},
                 {"type": "ask_agent", "agent": "edith",
                  "message": "EDITH, this competitor post is doing very well: \"{{data.text}}\". Write our own original take in our brand voice and save it as a draft. Never copy the wording."}]},
    {"recipe": "blog-to-thread", "name": "Turn each new blog post into a thread",
     "description": "When your blog feed announces a new article, E.D.I.T.H. also writes a 4-part thread from it.",
     "trigger": {"type": "event", "event": "post.drafted"},
     "conditions": [{"field": "data.campaign", "op": "equals", "value": "own-blog"},
                    {"field": "data.platform", "op": "equals", "value": "bluesky"}],
     "actions": [{"type": "ask_agent", "agent": "edith",
                  "message": "EDITH, read {{data.text}} and write a 4-part Bluesky thread with the key takeaways and the link in the last part. Save it as a draft."}]},
    {"recipe": "weekly-recap", "name": "Friday recap of the week",
     "description": "Every Friday at 16:00, JOCASTA reviews the week's results and drafts a recap post.",
     "trigger": {"type": "schedule", "every": "week", "weekday": 4, "time": "16:00"},
     "conditions": [],
     "actions": [{"type": "ask_agent", "agent": "jocasta",
                  "message": "Jocasta, look at this week's published posts and their real engagement (social.analytics), then draft a short, honest 'this week at our project' recap post for Bluesky and Mastodon."}]},
    {"recipe": "daily-ideas", "name": "Three post ideas every morning",
     "description": "Every day at 08:30, J.A.R.V.I.S. proposes three post ideas as drafts, using the Library and recent trends.",
     "trigger": {"type": "schedule", "every": "day", "time": "08:30"},
     "conditions": [],
     "actions": [{"type": "ask_agent", "agent": "jarvis",
                  "message": "JARVIS, propose three varied post ideas for today in our brand voice (use the Library templates), have E.D.I.T.H. write them as drafts, and keep it to three."}]},
    {"recipe": "failed-alert", "name": "Tell me when a post fails",
     "description": "If publishing fails, you get a phone message with the reason.",
     "trigger": {"type": "event", "event": "post.failed"}, "conditions": [],
     "actions": [{"type": "notify", "text": "⚠️ A {{data.platform}} post failed to publish: {{data.text}}"}]},
    {"recipe": "utm-drafts", "name": "Tag links in every new draft",
     "description": "Links to your own site in each new draft get utm_source / utm_medium / utm_campaign, so you can see which network brings visitors.",
     "trigger": {"type": "event", "event": "post.drafted"},
     "conditions": [{"field": "data.text", "op": "contains", "value": "https://"}],
     "actions": [{"type": "add_utm"}]},
    {"recipe": "approval-ping", "name": "Ping me when an agent needs approval",
     "description": "When an agent asks permission for an action, you get a phone message so nothing waits for hours.",
     "trigger": {"type": "event", "event": "approval.needed"}, "conditions": [],
     "actions": [{"type": "notify", "text": "🛂 {{data.agent_id}} wants to {{data.tool_id}}: {{data.action}}"}]},
    {"recipe": "log-published", "name": "Log every published post to another app",
     "description": "Each published post is sent to a webhook, e.g. an automation app that writes it to a spreadsheet or a notes database.",
     "trigger": {"type": "event", "event": "post.published"}, "conditions": [],
     "actions": [{"type": "webhook", "url": "https://example.com/your-webhook"}]},
    {"recipe": "inbound-draft", "name": "Drafts from other apps",
     "description": "Another app sends {\"platform\": \"bluesky\", \"text\": \"…\"} to this automation's address and a draft appears for you to approve.",
     "trigger": {"type": "webhook"}, "conditions": [{"field": "data.text", "op": "not_empty", "value": ""}],
     "actions": [{"type": "create_draft", "platform": "bluesky", "text": "{{data.text}}"}]},
]


def from_recipe(recipe_id: str) -> dict[str, Any]:
    r = next((x for x in RECIPES if x["recipe"] == recipe_id), None)
    if r is None:
        raise AutomationError("No such recipe")
    return {k: r[k] for k in ("recipe", "name", "trigger", "conditions", "actions")}


# ------------------------------------------------------------------ engine
class Engine:
    def __init__(self, kernel, social, settings, notifier=None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.kernel = kernel
        self.social = social
        self.settings = settings
        self.notifier = notifier
        self.transport = transport

    # -- storage
    def list(self) -> list[dict[str, Any]]:
        with self.kernel.db.session() as s:
            return [self._out(to_dict(a)) for a in s.scalars(select(Automation).order_by(Automation.created_at)).all()]

    def get(self, automation_id: str) -> dict[str, Any] | None:
        with self.kernel.db.session() as s:
            row = s.get(Automation, automation_id)
            return to_dict(row) if row is not None else None

    @staticmethod
    def _out(a: dict[str, Any]) -> dict[str, Any]:
        a = dict(a)
        a["hook_path"] = f"/api/hooks/{a['id']}/{a['hook_key']}" if a.get("hook_key") else None
        a.pop("hook_key", None)
        return a

    def save(self, data: dict[str, Any], automation_id: str | None = None) -> dict[str, Any]:
        c = clean(data)
        with self.kernel.db.session() as s:
            if automation_id:
                row = s.get(Automation, automation_id)
                if row is None:
                    raise KeyError("no such automation")
            else:
                if len(s.scalars(select(Automation.id)).all()) >= 100:
                    raise AutomationError("Up to 100 automations")
                row = Automation()
                s.add(row)
            for k, v in c.items():
                setattr(row, k, v)
            if c["trigger"]["type"] == "webhook" and not row.hook_key:
                row.hook_key = secrets.token_urlsafe(24)
            if c["trigger"]["type"] != "webhook":
                row.hook_key = None
            s.flush()
            return self._out(to_dict(row))

    def delete(self, automation_id: str) -> bool:
        with self.kernel.db.session() as s:
            row = s.get(Automation, automation_id)
            if row is None:
                return False
            s.delete(row)
            for r in s.scalars(select(AutomationRun).where(AutomationRun.automation_id == automation_id)).all():
                s.delete(r)
            return True

    def history(self, automation_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.kernel.db.session() as s:
            q = select(AutomationRun).order_by(AutomationRun.at.desc()).limit(limit)
            if automation_id:
                q = q.where(AutomationRun.automation_id == automation_id)
            return [to_dict(r) for r in s.scalars(q).all()]

    # -- running
    def _recent_runs(self, automation_id: str) -> int:
        with self.kernel.db.session() as s:
            return s.scalar(select(func.count()).select_from(AutomationRun).where(
                AutomationRun.automation_id == automation_id, AutomationRun.at >= utcnow() - timedelta(hours=1))) or 0

    def plan(self, a: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """What would happen for this payload (used by Test run and before a real run)."""
        failed = [c for c in a["conditions"] if not matches(c, payload)]
        steps = []
        for act in a["actions"]:
            step = {"type": act["type"]}
            for k in ("message", "text"):
                if k in act:
                    step[k] = render(act[k], payload)
            for k in ("agent", "platform", "label", "url", "category"):
                if k in act:
                    step[k] = act[k]
            steps.append(step)
        return {"would_run": not failed, "failed_conditions": failed, "steps": steps}

    async def run(self, a: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
        p = self.plan(a, payload)
        if not p["would_run"]:
            return None
        if self._recent_runs(a["id"]) >= RATE_LIMIT:
            log.warning(f"automation {a['id']} hit its hourly limit")
            return None
        done, ok = [], True
        for step in p["steps"]:
            try:
                done.append({**step, "result": await self._do(a, step, payload)})
            except Exception as exc:  # one failing step is recorded; the rest still run
                ok = False
                done.append({**step, "error": str(exc)[:300]})
        with self.kernel.db.session() as s:
            s.add(AutomationRun(automation_id=a["id"], event=payload.get("event", "?"), ok=ok, steps=done))
            row = s.get(Automation, a["id"])
            if row is not None:
                row.runs = (row.runs or 0) + 1
                row.last_run_at = utcnow()
        self.kernel.bus.publish("automation.run", {"id": a["id"], "name": a["name"], "ok": ok, "steps": len(done)})
        return {"ok": ok, "steps": done}

    async def _do(self, a: dict[str, Any], step: dict[str, Any], payload: dict[str, Any]) -> str:
        t = step["type"]
        if t == "ask_agent":
            task = self.kernel.submit_chat(step["agent"], step["message"])
            return f"task {task['id']} for {step['agent']}"
        if t == "create_draft":
            d = create_draft(self.kernel, self.social, self.settings,
                             {"platform": step["platform"], "text": step["text"], "category": step.get("category")},
                             created_by=f"automation:{a['id']}")
            return f"draft {d['id']} ({d['check']['verdict']})"
        if t == "label_mention":
            mid = lookup(payload, "data.id")
            with self.kernel.db.session() as s:
                m = s.get(Mention, mid) if mid else None
                if m is None:
                    return "no mention in this event"
                m.labels = list(dict.fromkeys([*(m.labels or []), step["label"]]))
            return f"labelled {mid}"
        if t == "add_utm":
            from .reach import tag_item

            pid = lookup(payload, "data.id")
            if not pid or not str(pid).startswith("cnt"):
                return "no post in this event"
            out = tag_item(self.kernel, self.settings, str(pid))
            return f"tagged links in {pid}" if out else "post not found"
        if t == "notify":
            if self.notifier is None or not (self.notifier.telegram or self.notifier.discord):
                return "skipped: no phone notifications set up"
            await self.notifier.send(step["text"])
            return "sent"
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
            r = await client.post(step["url"], json={"automation": a["name"], **payload})
        return f"HTTP {r.status_code}"

    def automations_for(self, trigger_type: str, event: str | None = None) -> list[dict[str, Any]]:
        with self.kernel.db.session() as s:
            rows = [to_dict(a) for a in s.scalars(select(Automation).where(Automation.enabled.is_(True))).all()]
        return [a for a in rows if a["trigger"].get("type") == trigger_type
                and (event is None or a["trigger"].get("event") == event)]

    async def on_event(self, ev: dict[str, Any]) -> int:
        p = webhook_payload(ev)
        if p is None:
            return 0
        if str((p["data"] or {}).get("created_by") or "").startswith("automation:"):
            return 0  # no loops: what an automation made never triggers automations
        if ev["type"] == "listening.hit":  # give recipes the full mention (id, likes, kind, …)
            p["data"] = dict(ev["data"])
        n = 0
        for a in self.automations_for("event", p["event"]):
            if await self.run(a, p):
                n += 1
        return n

    def due(self, a: dict[str, Any], now: datetime) -> bool:
        t = a["trigger"]
        hh, mm = map(int, t["time"].split(":"))
        if (now.hour, now.minute) < (hh, mm):
            return False
        if t["every"] == "week" and now.weekday() != int(t["weekday"]):
            return False
        last = a.get("last_run_at")
        if last:
            last_local = datetime.fromisoformat(last).astimezone(now.tzinfo)
            if last_local.date() == now.date():
                return False
        return True

    async def tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now().astimezone()
        n = 0
        for a in self.automations_for("schedule"):
            if self.due(a, now):
                if await self.run(a, {"event": "schedule", "at": now.isoformat(), "data": {}}):
                    n += 1
        return n

    async def inbound(self, automation_id: str, key: str, body: Any) -> dict[str, Any] | None:
        with self.kernel.db.session() as s:
            row = s.get(Automation, automation_id)
            a = to_dict(row) if row is not None else None
        if a is None or not a["enabled"] or not a.get("hook_key") or \
                not hmac.compare_digest(a["hook_key"].encode(), key.encode()):
            return None
        data = body if isinstance(body, dict) else {"value": body}
        res = await self.run(a, {"event": "webhook", "at": utcnow().isoformat(), "data": data})
        return res or {"ok": True, "steps": [], "note": "conditions did not match"}

    async def loop(self) -> None:
        q = self.kernel.bus.subscribe()

        async def events() -> None:
            while True:
                ev = json.loads(await q.get())
                try:
                    await self.on_event(ev)
                except Exception as exc:
                    log.warning(f"automation error: {exc}")

        async def schedule() -> None:
            while True:
                try:
                    await self.tick()
                except Exception as exc:
                    log.warning(f"automation schedule error: {exc}")
                await asyncio.sleep(30)

        jobs = [asyncio.create_task(events()), asyncio.create_task(schedule())]
        try:
            await asyncio.gather(*jobs)
        finally:
            for j in jobs:
                j.cancel()
            self.kernel.bus.unsubscribe(q)
