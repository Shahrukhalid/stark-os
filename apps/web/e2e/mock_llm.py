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
    if has_tools and "before i publish it" in low and n == 0:  # the model-pool ping request
        msg = call("social__check", {"platform": "bluesky", "text": "Hello world"}, n)
    elif has_tools and "draft a launch post" in low and "social__draft" in tool_names:
        if n == 0:
            msg = call("social__draft", {"platform": "bluesky", "text": "STARK OS is live: seven agents, one "
                                         "social team. https://example.com/launch #launch"}, n)
        else:
            d = last["data"]
            msg = {"role": "assistant", "content": f"Drafted {d['id']} for Bluesky. Check: {d['check']['verdict'].upper()}."}
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
    else:
        msg = {"role": "assistant", "content": f"{who} acknowledges: {user[:120]}"}

    return {"id": "mock", "object": "chat.completion", "model": body.get("model", "mock"),
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}}


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

    def do_GET(self):
        if self.path.endswith("/key"):
            self._send(200, {"data": {"label": "e2e", "is_free_tier": True,
                                      "free_model_daily_requests": {"limit": 50, "remaining": 49, "used": 1}}})
            return
        self._send(200, {"data": [{"id": "mock/free-tools:free", "name": "Mock (test only)", "context_length": 8192,
                                   "pricing": {"prompt": "0", "completion": "0"},
                                   "supported_parameters": ["tools"],
                                   "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self._send(200, respond(body))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
