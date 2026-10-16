"""OpenRouter free-model pool: the only model provider STARK OS uses.

How it works
- At startup the catalogue (GET /models) is fetched and every **free** model is
  recorded. Chat models that support **tool calling** form the pool agents use.
- Each tier (deep / balanced / fast) has a preference order. It starts from a
  snapshot of models verified live on 2026-10-16 (see PING_SNAPSHOT) and then
  appends any other free tool-capable models the catalogue reports, so new
  free models are picked up automatically and retired ones drop out.
- Every call tries candidates in order. A model that fails is put on cooldown
  (rate-limited: short, unavailable/forbidden: long) and the next one is used.
- Paid models are never called unless OPENROUTER_ALLOW_PAID=true.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .base import ModelRequest, ProviderError
from .openai_compat import OpenAICompatProvider

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
META_ROUTER = "openrouter/free"  # OpenRouter's own router across currently free models

# Live ping on 2026-10-16 (one tool-calling request each). ms = round-trip latency.
PING_SNAPSHOT: dict[str, dict[str, Any]] = {
    "openrouter/free": {"ok": True, "ms": 715, "note": "meta-router; served nvidia/nemotron-3.5-super-vl:free"},
    "nvidia/nemotron-3.5-super-vl:free": {"ok": True, "ms": 666},
    "nvidia/nemotron-3-ultra-550b-a55b:free": {"ok": True, "ms": 8182},
    "nvidia/nemotron-3-super-120b-a12b:free": {"ok": True, "ms": 18085},
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": {"ok": True, "ms": 4511},
    "nvidia/nemotron-3.5-lightning:free": {"ok": True, "ms": 46229},
    "cohere/north-mini-code:free": {"ok": True, "ms": 991},
    "dots-studio/dots-3-note-preview:free": {"ok": True, "ms": 1546},
    "liquid/lfm-2.5-2.6b:free": {"ok": True, "ms": 613, "note": "very small model: fast but weak at multi-step work"},
    "google/gemma-4-31b-it:free": {"ok": False, "error": "429 upstream rate limit (transient)"},
    "google/gemma-4-26b-a4b-it:free": {"ok": False, "error": "429 upstream rate limit (transient)"},
    "poolside/laguna-s-2.1:free": {"ok": False, "error": "429 upstream rate limit (transient)"},
    "poolside/laguna-xs-2.1:free": {"ok": False, "error": "429 upstream rate limit (transient)"},
    "thinkingmachines/inkling:free": {"ok": False, "error": "403 only available on agentic harnesses"},
    "thinkingmachines/inkling-small:free": {"ok": False, "error": "403 only available on agentic harnesses"},
}

TIER_PREFERENCES: dict[str, list[str]] = {
    "deep": ["nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free",
             "nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it:free", META_ROUTER],
    "balanced": ["nvidia/nemotron-3.5-super-vl:free", "nvidia/nemotron-3-ultra-550b-a55b:free",
                 "cohere/north-mini-code:free", "google/gemma-4-31b-it:free",
                 "nvidia/nemotron-3-super-120b-a12b:free", META_ROUTER],
    "fast": ["nvidia/nemotron-3.5-super-vl:free", "cohere/north-mini-code:free",
             "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "dots-studio/dots-3-note-preview:free",
             "google/gemma-4-26b-a4b-it:free", META_ROUTER],
}
# Known not to work through the plain API (403); kept out of the pool unless pinned.
EXCLUDED = {"thinkingmachines/inkling:free", "thinkingmachines/inkling-small:free"}

COOLDOWN_S = {"rate_limited": 60, "server": 120, "unavailable": 1800, "forbidden": 6 * 3600}


def is_free(model: dict[str, Any]) -> bool:
    if model.get("id", "").endswith(":free") or model.get("id") == META_ROUTER:
        return True
    p = model.get("pricing") or {}
    try:
        if "prompt" not in p or "completion" not in p:
            return False
        return all(float(p.get(k) or 0) == 0 for k in ("prompt", "completion", "request"))
    except (TypeError, ValueError):
        return False


def is_chat_tool_model(model: dict[str, Any]) -> bool:
    arch = model.get("architecture") or {}
    outputs = arch.get("output_modalities") or ["text"]
    return "tools" in (model.get("supported_parameters") or []) and "text" in outputs


def rank_free_tool_models(models: list[dict[str, Any]]) -> list[str]:
    """Free chat models with tool support, largest context first (used for unknown models)."""
    out = [(int(m.get("context_length") or 0), m["id"]) for m in models
           if is_free(m) and is_chat_tool_model(m) and m.get("id") not in EXCLUDED]
    return [mid for _, mid in sorted(out, key=lambda x: (-x[0], x[1]))]


@dataclass
class ModelHealth:
    ok: int = 0
    failed: int = 0
    last_ok_at: float | None = None
    last_error: str | None = None
    last_latency_ms: int | None = None
    cooldown_until: float = 0.0
    cooldown_reason: str | None = None
    history: list[bool] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        now = time.time()
        return {"ok": self.ok, "failed": self.failed, "last_error": self.last_error,
                "last_latency_ms": self.last_latency_ms,
                "cooling_down_s": max(0, int(self.cooldown_until - now)),
                "cooldown_reason": self.cooldown_reason if self.cooldown_until > now else None}


class DailyQuotaExhausted(ProviderError):
    pass


def classify_failure(exc: ProviderError) -> str:
    msg = str(exc).lower()
    if exc.status == 429:
        return "rate_limited"
    if exc.status in (401,):
        return "auth"
    if exc.status in (402, 403) or "only available" in msg or "not allowed" in msg:
        return "forbidden"
    if exc.status in (400, 404) and ("no endpoints" in msg or "not a valid model" in msg or "not found" in msg):
        return "unavailable"
    if exc.status is None or exc.status >= 500 or exc.retryable:
        return "server"
    return "request"  # our request was rejected (bad input) - trying other models won't help


class OpenRouterProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, *, base_url: str = OPENROUTER_BASE, app_url: str = "",
                 allow_paid: bool = False, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__("openrouter", base_url if api_key else "", api_key,
                         health_url=f"{base_url.rstrip('/')}/key", transport=transport)
        self._root = base_url.rstrip("/")
        self._app_url = app_url
        self.allow_paid = allow_paid
        self.catalog: dict[str, dict[str, Any]] = {}  # every free model OpenRouter lists
        self.pool: list[str] = []  # free chat models with tool calling, usable by agents
        self.model_health: dict[str, ModelHealth] = {}
        self.catalog_error: str | None = None
        self.catalog_fetched_at: float | None = None

    def configured(self) -> tuple[bool, str]:
        if not self._key:
            return False, "set OPENROUTER_API_KEY in .env (free key: https://openrouter.ai/keys)"
        return True, "OpenRouter key present"

    def _client(self) -> httpx.AsyncClient:
        client = super()._client()
        client.headers["X-Title"] = "STARK OS"
        if self._app_url:
            client.headers["HTTP-Referer"] = self._app_url
        return client

    # ------------------------------------------------------------ catalogue
    async def refresh_catalog(self) -> list[str]:
        try:
            async with self._client() as client:
                resp = await client.get("/models", timeout=15)
            resp.raise_for_status()
            models = resp.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            self.catalog_error = f"{exc.__class__.__name__}: {exc}"[:200]
            if not self.pool:  # offline at startup: fall back to the verified snapshot
                self.pool = [m for m in dict.fromkeys(sum(TIER_PREFERENCES.values(), [])) if m not in EXCLUDED]
            return self.pool
        self.catalog = {
            m["id"]: {"id": m["id"], "name": m.get("name", m["id"]), "context_length": m.get("context_length"),
                      "tools": "tools" in (m.get("supported_parameters") or []),
                      "chat": is_chat_tool_model(m) or "text" in ((m.get("architecture") or {}).get("output_modalities") or ["text"]),
                      "input_modalities": (m.get("architecture") or {}).get("input_modalities") or [],
                      "excluded": m["id"] in EXCLUDED, "snapshot": PING_SNAPSHOT.get(m["id"])}
            for m in models if is_free(m)
        }
        self.pool = rank_free_tool_models(models)
        self.catalog_error = None
        self.catalog_fetched_at = time.time()
        return self.pool

    def candidates(self, tier: str, pinned: str | None = None, limit: int = 4,
                   preferred: list[str] | None = None) -> list[str]:
        """Ordered models to try: pinned, then the agent's own preferred models, then the tier list.
        Models on cooldown, retired from the catalogue or not free are skipped."""
        order: list[str] = []
        if pinned:
            order.append(pinned)
        known = set(self.pool) or None
        for m in preferred or []:
            if known is None or m in known:
                order.append(m)
        for m in TIER_PREFERENCES.get(tier, TIER_PREFERENCES["balanced"]):
            if known is None or m in known or m == META_ROUTER:
                order.append(m)
        order += self.pool
        order.append(META_ROUTER)
        seen, out, now = set(), [], time.time()
        for m in order:
            if m in seen:
                continue
            seen.add(m)
            if not self.allow_paid and m != META_ROUTER and not m.endswith(":free") and m not in self.catalog:
                continue  # never call a paid model by accident
            h = self.model_health.get(m)
            if h and h.cooldown_until > now and m != pinned:
                continue
            out.append(m)
        return out[:limit] or [META_ROUTER]

    # ------------------------------------------------------------ health
    def record_success(self, model: str, latency_ms: int) -> None:
        h = self.model_health.setdefault(model, ModelHealth())
        h.ok += 1
        h.last_ok_at = time.time()
        h.last_latency_ms = latency_ms
        h.cooldown_until = 0
        h.history = (h.history + [True])[-20:]

    def record_failure(self, model: str, exc: ProviderError) -> str:
        kind = classify_failure(exc)
        h = self.model_health.setdefault(model, ModelHealth())
        h.failed += 1
        h.last_error = str(exc)[:200]
        h.history = (h.history + [False])[-20:]
        if kind in COOLDOWN_S:
            h.cooldown_until = time.time() + COOLDOWN_S[kind]
            h.cooldown_reason = kind
        return kind

    async def key_info(self) -> dict[str, Any]:
        """Remaining free requests today etc. (GET /key). Never returns the key itself."""
        async with self._client() as client:
            resp = await client.get("/key", timeout=10)
        if resp.status_code != 200:
            raise ProviderError(f"OpenRouter /key HTTP {resp.status_code}", status=resp.status_code)
        d = resp.json().get("data", {})
        return {"label": d.get("label"), "is_free_tier": d.get("is_free_tier"),
                "free_model_daily_requests": d.get("free_model_daily_requests"),
                "usage": d.get("usage"), "limit": d.get("limit")}

    async def ping(self, model: str) -> dict[str, Any]:
        """One tiny tool-calling request: proves the model answers and can call tools."""
        tool = {"name": "social__check", "description": "Check a social media post against platform rules",
                "input_schema": {"type": "object", "properties": {"platform": {"type": "string"},
                                                                  "text": {"type": "string"}},
                                 "required": ["platform", "text"]}}
        req = ModelRequest(model=model, system="You are a social media agent. Use tools when needed.",
                           messages=[{"role": "user", "content": "Check this Bluesky post before I publish it: "
                                                                 "'Hello world'"}],
                           tools=[tool], max_tokens=300, temperature=0)
        started = time.monotonic()
        try:
            resp = await self.complete(req)
        except ProviderError as exc:
            kind = self.record_failure(model, exc)
            return {"model": model, "ok": False, "error": str(exc)[:200], "kind": kind,
                    "ms": int((time.monotonic() - started) * 1000)}
        ms = int((time.monotonic() - started) * 1000)
        self.record_success(model, ms)
        return {"model": model, "ok": True, "ms": ms, "served_by": resp.model,
                "tool_calling": bool(resp.tool_calls), "text": resp.text[:120]}

    async def list_models(self) -> list[str]:
        return list(self.pool)
