"""MCP server: lets AI assistants and editors that speak the Model Context Protocol (stdio) work with STARK OS.

Run it from the project's virtual environment:  python -m stark.mcp_server
It talks to the running STARK OS API (STARK_API_URL, default http://127.0.0.1:8000) with STARK_API_TOKEN from
.env. It can read the queue, analytics and mentions, save drafts, schedule drafts WITHOUT auto-publish, and
hand work to the agent team. It can never publish: going public always needs your approval in the dashboard
or on your phone.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

from . import __version__
from .config import REPO_ROOT, load_dotenv

PROTOCOL = "2025-06-18"

TOOLS: list[dict[str, Any]] = [
    {"name": "stark_status", "description": "STARK OS status: mode, emergency stop, free-model quota, agents.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_queue", "description": "Posts in the content queue (drafts, scheduled, published, failed).",
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["all", "draft", "scheduled", "published", "failed"], "default": "all"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30}}}},
    {"name": "create_draft", "description": "Save a post as a DRAFT (never published). The policy check runs and "
                                            "its verdict is returned. Platforms: bluesky, mastodon, x, threads, "
                                            "linkedin, instagram, facebook, tiktok, youtube.",
     "inputSchema": {"type": "object", "required": ["platform", "text"], "properties": {
         "platform": {"type": "string"}, "text": {"type": "string"},
         "thread": {"type": "array", "items": {"type": "string"}, "description": "Follow-up posts of a thread"},
         "campaign": {"type": "string"}}}},
    {"name": "schedule_draft", "description": "Put a draft on the calendar at a time (ISO 8601). It does NOT go out "
                                              "on its own: the owner approves it in the dashboard or on the phone.",
     "inputSchema": {"type": "object", "required": ["item_id", "when"], "properties": {
         "item_id": {"type": "string"}, "when": {"type": "string"}}}},
    {"name": "ask_team", "description": "Give the STARK OS agent team a task in plain language, e.g. 'EDITH, write "
                                        "a LinkedIn post about our launch'. Returns the task id; drafts land in the queue.",
     "inputSchema": {"type": "object", "required": ["message"], "properties": {"message": {"type": "string"}}}},
    {"name": "get_task", "description": "Status and result of a task started with ask_team.",
     "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}},
    {"name": "get_analytics", "description": "Real engagement of published posts (Bluesky/Mastodon) and queue counts.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_mentions", "description": "Posts found by social listening that still need attention.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 30}}}},
]


class Client:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=60, transport=transport,
                                 headers={"authorization": f"Bearer {token}"})

    def call(self, method: str, path: str, **kw) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:300]
            raise RuntimeError(f"STARK OS answered {r.status_code}: {detail}")
        return r.json()


def run_tool(c: Client, name: str, args: dict[str, Any]) -> Any:
    if name == "stark_status":
        s = c.call("GET", "/api/system/status")
        return {k: s.get(k) for k in ("mode", "emergency_stop", "quota", "active_providers", "version")}
    if name == "list_queue":
        status = args.get("status", "all")
        q = c.call("GET", "/api/social/queue", params={"status": status, "limit": int(args.get("limit", 30))})
        return [{k: i.get(k) for k in ("id", "platform", "status", "text", "scheduled_for", "auto_publish", "campaign")}
                | {"check": i["check"]["verdict"]} for i in q["items"]]
    if name == "create_draft":
        i = c.call("POST", "/api/social/drafts", json={k: args[k] for k in ("platform", "text", "thread", "campaign")
                                                       if k in args})
        return {"id": i["id"], "check": i["check"], "simulated": i["simulated"]}
    if name == "schedule_draft":
        q = c.call("GET", "/api/social/queue", params={"limit": 500})["items"]
        item = next((i for i in q if i["id"] == args["item_id"]), None)
        if item is None:
            raise RuntimeError("no such post")
        return c.call("POST", f"/api/social/items/{item['id']}/schedule",
                      json={"fingerprint": item["fingerprint"], "when": args["when"], "auto": False})
    if name == "ask_team":
        t = c.call("POST", "/api/chat", json={"message": args["message"]})
        return {"task_id": t.get("id") or t.get("task_id"), "agent": t.get("agent_id"), "status": t.get("status")}
    if name == "get_task":
        t = c.call("GET", f"/api/tasks/{args['task_id']}")["task"]
        return {k: t.get(k) for k in ("id", "agent_id", "status", "result", "error")}
    if name == "get_analytics":
        a = c.call("GET", "/api/social/analytics")
        return {"totals": a["totals"], "measured": a["measured"], "counts": a["counts"],
                "top_posts": sorted([p for p in a["posts"] if p["score"] is not None],
                                    key=lambda p: -p["score"])[:10]}
    if name == "list_mentions":
        m = c.call("GET", "/api/listening/mentions", params={"limit": int(args.get("limit", 30))})["mentions"]
        return [{k: x.get(k) for k in ("platform", "author", "text", "url", "category", "posted_at")} for x in m]
    raise RuntimeError(f"unknown tool {name}")


def handle(c: Client, msg: dict[str, Any]) -> dict[str, Any] | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # a notification (e.g. notifications/initialized): no answer
        return None
    if method == "initialize":
        result: Any = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "stark-os", "version": __version__}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params") or {}
        try:
            out = run_tool(c, p.get("name", ""), p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, default=str)}]}
        except (RuntimeError, httpx.HTTPError, KeyError, ValueError) as exc:
            result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    token = os.environ.get("STARK_API_TOKEN", "")
    if not token:
        sys.stderr.write("STARK_API_TOKEN is not set (run from the STARK OS folder or set it in the MCP config)\n")
        sys.exit(1)
    c = Client(os.environ.get("STARK_API_URL", "http://127.0.0.1:8000"), token)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(c, msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
