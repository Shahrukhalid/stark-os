"""OpenAI-compatible chat-completions adapter.

Base class for the OpenRouter provider (OpenRouter speaks this protocol).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .base import RETRYABLE_STATUS, ModelProvider, ModelRequest, ModelResponse, ProviderError


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": msg["role"], "content": content})
            continue
        texts = [b["text"] for b in content if b.get("type") == "text"]
        if msg["role"] == "assistant":
            calls = [
                {"id": b["id"], "type": "function",
                 "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
                for b in content if b.get("type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
        else:
            for b in content:
                if b.get("type") == "tool_result":
                    body = b.get("content", "")
                    if isinstance(body, list):
                        body = "\n".join(x.get("text", "") for x in body)
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": body})
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return out


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in tools]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # some providers return content parts
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return ""


def from_openai_response(data: dict[str, Any], provider: str, model: str) -> ModelResponse:
    if not isinstance(data, dict):
        raise ProviderError(f"{provider}: unexpected response shape", retryable=True)
    if data.get("error"):  # OpenRouter can return HTTP 200 with an error body
        err = data["error"] if isinstance(data["error"], dict) else {"message": str(data["error"])}
        code = err.get("code")
        raise ProviderError(f"{provider} error {code}: {str(err.get('message', ''))[:300]}",
                            status=code if isinstance(code, int) else None, retryable=True)
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError(f"{provider}: response had no choices", retryable=True)
    choice = choices[0] or {}
    message = choice.get("message") or {}
    content: list[dict[str, Any]] = []
    text = _text_of(message.get("content"))
    if text:
        content.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw_args = fn.get("arguments")
        if isinstance(raw_args, dict):
            args = raw_args
        else:
            try:
                args = json.loads(raw_args or "{}")
            except (TypeError, ValueError):
                args = {"_raw": raw_args}
            if not isinstance(args, dict):
                args = {"_raw": args}
        content.append({"type": "tool_use", "id": call.get("id") or f"call_{len(content)}",
                        "name": fn.get("name", ""), "input": args})
    finish = choice.get("finish_reason")
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else (
        "max_tokens" if finish == "length" else "end_turn")
    usage = data.get("usage") or {}
    return ModelResponse(content=content, stop_reason=stop,
                         input_tokens=int(usage.get("prompt_tokens") or 0),
                         output_tokens=int(usage.get("completion_tokens") or 0),
                         model=data.get("model", model), provider=provider)


class OpenAICompatProvider(ModelProvider):
    def __init__(self, name: str, base_url: str, api_key: str = "", *,
                 health_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 180.0) -> None:
        self.name = name
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._health_url = health_url
        self._transport = transport
        self._timeout = timeout_s
        self._health_cache: tuple[float, tuple[bool, str]] | None = None

    def configured(self) -> tuple[bool, str]:
        if not self._base:
            return False, f"{self.name}: no base URL configured"
        return True, self._base

    def _client(self) -> httpx.AsyncClient:
        headers = {"content-type": "application/json"}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        return httpx.AsyncClient(base_url=self._base, timeout=self._timeout, transport=self._transport,
                                 headers=headers)

    async def health(self) -> tuple[bool, str]:
        ok, detail = self.configured()
        if not ok:
            return ok, detail
        if self._health_cache and time.monotonic() - self._health_cache[0] < 30:
            return self._health_cache[1]
        try:
            async with httpx.AsyncClient(timeout=3.0, transport=self._transport) as client:
                url = self._health_url or f"{self._base}/models"
                resp = await client.get(url, headers={"authorization": f"Bearer {self._key}"} if self._key else {})
            result = (resp.status_code == 200, f"HTTP {resp.status_code} from {url}")
        except httpx.HTTPError as exc:
            result = (False, f"unreachable: {exc.__class__.__name__}")
        self._health_cache = (time.monotonic(), result)
        return result

    async def list_models(self) -> list[str]:
        ok, _ = self.configured()
        if not ok:
            return []
        try:
            async with self._client() as client:
                resp = await client.get("/models")
            return [m["id"] for m in resp.json().get("data", [])] if resp.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        ok, detail = self.configured()
        if not ok:
            raise ProviderError(detail)
        body: dict[str, Any] = {
            "model": request.model,
            "messages": to_openai_messages(request.system, request.messages),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.tools:
            body["tools"] = to_openai_tools(request.tools)
        try:
            async with self._client() as client:
                resp = await client.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.name} timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} network error: {exc}", retryable=True) from exc
        if resp.status_code != 200:
            raise ProviderError(f"{self.name} HTTP {resp.status_code}: {resp.text[:300]}",
                                status=resp.status_code, retryable=resp.status_code in RETRYABLE_STATUS)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name}: response was not JSON", retryable=True) from exc
        return from_openai_response(data, self.name, request.model)
