"""TEST-ONLY scripted model server speaking the OpenRouter (OpenAI-compatible) protocol.

Used by the end-to-end tests so the full stack (dashboard -> API -> model adapter
over real HTTP -> tools -> approvals) can be exercised without an API key.
It is not a language model and is never used outside tests.

Run: python3 mock_llm.py 8799
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def agent_of(system: str) -> str:
    return system.split(",")[0].replace("You are ", "").split(" (")[0].strip()


def turn_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Return the latest plain user text and the tool results that followed it."""
    idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
    user = messages[idx]["content"]
    tools = [m for m in messages[idx + 1:] if m["role"] == "tool"]
    return user, tools


def call(name: str, args: dict, n: int) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"call_{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def respond(body: dict) -> dict:
    msgs = body["messages"]
    system = msgs[0]["content"]
    who = agent_of(system)
    user, results = turn_messages(msgs)
    low = user.lower()
    has_tools = bool(body.get("tools"))
    n = len(results)
    last = json.loads(results[-1]["content"]) if results else None

    tool_names = json.dumps(body.get("tools", []))
    if "## Autopilot writing task" in system:
        platforms = [p.split(" = ")[0].strip() for p in user.split("character budgets: ", 1)[1].split("\n")[0].split(", ")]
        posts = {p: "A new open source toolkit adds approval checks for AI agents, with 12 built-in rules." for p in platforms}
        msg = {"role": "assistant", "content": json.dumps({"posts": posts})}
    elif "## Autopilot fact-check task" in system:
        posts = json.loads(user.split("Posts:\n", 1)[1].split("\n\n<<<SOURCE", 1)[0])
        msg = {"role": "assistant", "content": json.dumps({"results": {p: {"supported": True, "problems": []} for p in posts}})}
    elif has_tools and "before i publish it" in low and n == 0:  # the model-pool ping request
        msg = call("social__check", {"platform": "bluesky", "text": "Hello world"}, n)
    elif has_tools and "draft a launch post" in low and "social__draft" in tool_names:
        if n == 0:
            msg = call("social__draft", {"platform": "bluesky", "text": "STARK AI is live: seven agents, one "
                                         "social team. https://example.com/launch #launch"}, n)
        else:
            d = last["data"]
            msg = {"role": "assistant", "content": f"Drafted {d['id']} for Bluesky. Check: {d['check']['verdict'].upper()}."}
    elif has_tools and "write a " in low and " post about" in low and "social__draft" in tool_names:  # docs screenshots
        platform = next((p for p in ("linkedin", "mastodon", "bluesky") if p in low), "bluesky")
        sample = {
            "bluesky": "New video is up: how we plan a whole week of posts in 20 minutes, with an AI team that "
                       "asks before anything goes live. https://example.com/video #creators",
            "mastodon": "Behind the scenes: every post our AI team drafts gets a rule check (length, links, #ad, "
                        "alt text) before we approve it. What would you add to the list? #opensource",
            "linkedin": "Three things we learned running social media with seven AI agents:\n\n1. Approval beats "
                        "automation: nothing goes live without a human click.\n2. A red-team agent catches "
                        "tone-deaf posts early.\n3. Free models are good enough for drafts.\n\nFull write-up: "
                        "https://example.com/blog",
        }[platform]
        if n == 0:
            msg = call("social__draft", {"platform": platform, "text": sample, "campaign": "launch week"}, n)
        else:
            d = last["data"]
            name = {"linkedin": "LinkedIn", "mastodon": "Mastodon", "bluesky": "Bluesky"}[platform]
            msg = {"role": "assistant", "content": f"Here's a {name} draft ({d['id']}). "
                                                   f"Check: **{d['check']['verdict'].upper()}**. Want a punchier hook?"}
    elif has_tools and "publish cnt_" in low and "social__publish" in tool_names:
        item = next(w for w in user.split() if w.startswith("cnt_"))
        if n == 0:
            msg = call("social__publish", {"item_id": item}, n)
        else:
            msg = {"role": "assistant", "content": f"*whirr* {last['summary']}"}
    elif has_tools and "mentions" in low and "social__inbox" in tool_names:
        if n == 0:
            msg = call("social__inbox", {"limit": 6}, n)
        else:
            top = last["data"]["messages"][0]
            msg = {"role": "assistant", "content": f"{last['summary']}. Top: {top['triage']['category']} from {top['author']}."}
    elif has_tools and ("organize" in low or "organise" in low):
        if n == 0:
            msg = call("fs__propose_organization", {"path": "test-folder"}, n)
        elif n == 1:
            msg = call("fs__move", {"moves": last["data"]["moves"]}, n)
        else:
            msg = {"role": "assistant", "content": f"Done. {last['summary']}"}
    elif has_tools and "whole team" in low and "team__review" in json.dumps(body["tools"]):
        if n == 0:
            msg = call("team__review", {"subject": "Review our launch campaign plan for Bluesky and LinkedIn."}, n)
        else:
            reviews = last["data"]["reviews"]
            names = ", ".join(r["agent"] for r in reviews if r["status"] == "completed")
            msg = {"role": "assistant", "content": f"Team review complete. Contributions from: {names}. "
                                                   f"Ultron challenge: {last['data']['challenge']['status']}."}
    elif user.startswith(("Team review request", "Challenge these team review results")):
        reviews = {
            "F.R.I.D.A.Y.": "**High:** expect questions about pricing on launch day: prepare two short replies.\n**Low:** post the recap in the evening, when replies peak.",
            "E.D.I.T.H.": "**High:** the Bluesky hook is strong; add a poll (\"Which feature first?\") to day 2.\n**Medium:** LinkedIn post needs one concrete number.",
            "JOCASTA": "**High:** \"20 minutes\" claim: keep it only if you can show the timing.\n**Medium:** two competitors launched this week; avoid their hashtag.",
            "D.U.M.-E.": "*whirr* **Medium:** two posts scheduled 10 minutes apart on Mastodon; spread them out.\nChecks: all PASS.",
            "U": "Storyboard ready for a 20-second clip. **Medium:** add alt text to the cover image.",
            "ULTRON": "Weakest point: \"nothing goes live without a human\" invites \"so why use AI?\". **Verdict: REVISE** the LinkedIn opener.",
        }
        msg = {"role": "assistant", "content": reviews.get(who, f"{who}: looks good.")}
    else:
        msg = {"role": "assistant", "content": f"{who} acknowledges: {user[:120]}"}

    return {"id": "mock", "object": "chat.completion", "model": body.get("model", "mock"),
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}}


FREE_MODEL_IDS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-super-vl:free", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "dots-studio/dots-3-note-preview:free",
    "cohere/north-mini-code:free",
]


FEED = ("<?xml version='1.0'?><rss version='2.0'><channel><title>Test news</title><item>"
        "<title>Open source AI agents get a new safety toolkit</title>"
        "<link>http://127.0.0.1:8799/news/agents-toolkit</link>"
        "<description>The toolkit adds approval checks for AI agents, with 12 built-in rules.</description>"
        "</item></channel></rss>")
ARTICLE = ("<html><body><h1>Open source AI agents get a new safety toolkit</h1><p>The toolkit adds approval checks "
           "for AI agents. It ships with 12 built-in rules.</p></body></html>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _text(self, status: int, body: str, ctype: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # Autopilot research fixtures (a news feed and the article it links to)
        if self.path == "/feed.xml":
            self._text(200, FEED, "application/rss+xml")
            return
        if self.path == "/robots.txt":
            self._text(404, "", "text/plain")
            return
        if self.path == "/news/agents-toolkit":
            self._text(200, ARTICLE, "text/html")
            return
        if self.path.endswith("/key"):
            self._send(200, {"data": {"label": "e2e", "is_free_tier": True,
                                      "free_model_daily_requests": {"limit": 50, "remaining": 49, "used": 1}}})
            return
        # the scripted server answers for every id, so the agents' own first-choice models show up as in real use
        ids = ["mock/free-tools:free", *FREE_MODEL_IDS]
        self._send(200, {"data": [{"id": m, "name": "Mock (test only)" if m.startswith("mock/") else m, "context_length": 8192,
                                   "pricing": {"prompt": "0", "completion": "0"},
                                   "supported_parameters": ["tools"],
                                   "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}
                                  for m in ids]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self._send(200, respond(body))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
