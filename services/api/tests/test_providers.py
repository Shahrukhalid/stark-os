"""OpenRouter free-model pool and the OpenAI-compatible wire format (recorded API shapes, no live calls)."""

from __future__ import annotations

import json

import httpx
import pytest

from stark.core.model_router import ModelRouter, NoModelAvailable
from stark.providers import ModelRequest, OpenAICompatProvider, OpenRouterProvider, ProviderError
from stark.providers.openai_compat import to_openai_messages
from stark.providers.openrouter import (EXCLUDED, META_ROUTER, TIER_PREFERENCES, classify_failure,
                                        rank_free_tool_models)

from .conftest import make_kernel


def _req(**kw) -> ModelRequest:
    base = dict(model="m", system="You are a test.", max_tokens=100, temperature=0.2,
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "fs__list", "description": "list", "input_schema": {"type": "object"}}])
    base.update(kw)
    return ModelRequest(**base)


# Shape copied from GET https://openrouter.ai/api/v1/models
CATALOG = {"data": [
    {"id": "big/paid-model", "context_length": 200000, "pricing": {"prompt": "0.000003", "completion": "0.00001"},
     "supported_parameters": ["tools"], "architecture": {"output_modalities": ["text"]}},
    {"id": "small/free-no-tools:free", "context_length": 128000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["temperature"], "architecture": {"output_modalities": ["text"]}},
    {"id": "nvidia/nemotron-3.5-super-vl:free", "context_length": 1000000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["tools"], "architecture": {"output_modalities": ["text"]}},
    {"id": "cohere/north-mini-code:free", "context_length": 256000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["tools"], "architecture": {"output_modalities": ["text"]}},
    {"id": "brand/new-model:free", "context_length": 64000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["tools"], "architecture": {"output_modalities": ["text"]}},
    {"id": "google/lyria-3-pro-preview", "context_length": 1048576, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": [], "architecture": {"output_modalities": ["audio"]}},
    {"id": "thinkingmachines/inkling:free", "context_length": 1048576, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["tools"], "architecture": {"output_modalities": ["text"]}},
]}


def _transport(seen: dict, fail: dict[str, tuple[int, str]] | None = None):
    fail = fail or {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.setdefault("calls", []).append(request.url.path)
        seen["auth"] = request.headers.get("authorization")
        seen["title"] = request.headers.get("x-title")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=CATALOG)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"label": "sk-or-v1-abc...xyz", "is_free_tier": True,
                                                      "free_model_daily_requests": {"limit": 50, "remaining": 41, "used": 9}}})
        body = json.loads(request.content)
        seen.setdefault("models", []).append(body["model"])
        if body["model"] in fail:
            status, msg = fail[body["model"]]
            return httpx.Response(status, json={"error": {"message": msg}})
        return httpx.Response(200, json={"model": body["model"], "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "system__metrics", "arguments": "{}"}}]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
    return httpx.MockTransport(handler)


def test_ranking_keeps_only_free_chat_tool_models():
    assert rank_free_tool_models(CATALOG["data"]) == [
        "nvidia/nemotron-3.5-super-vl:free", "cohere/north-mini-code:free", "brand/new-model:free"]


def test_tier_preferences_only_reference_free_models():
    for models in TIER_PREFERENCES.values():
        assert all(m.endswith(":free") or m == META_ROUTER for m in models)
        assert not set(models) & EXCLUDED


async def test_catalog_candidates_and_new_models_are_picked_up():
    seen: dict = {}
    p = OpenRouterProvider("sk-or-test", transport=_transport(seen))
    await p.refresh_catalog()
    assert "google/lyria-3-pro-preview" in p.catalog and "big/paid-model" not in p.catalog
    cands = p.candidates("fast", limit=10)
    assert cands[0] == "nvidia/nemotron-3.5-super-vl:free"      # verified preference first
    assert "brand/new-model:free" in cands                       # newly listed free model included
    assert "big/paid-model" not in cands and META_ROUTER in cands
    assert not set(cands) & EXCLUDED


async def test_offline_catalog_falls_back_to_snapshot():
    p = OpenRouterProvider("sk-or-test", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    pool = await p.refresh_catalog()
    assert pool and "nvidia/nemotron-3.5-super-vl:free" in pool and p.catalog_error


async def test_ping_and_key_info_and_headers():
    seen: dict = {}
    p = OpenRouterProvider("sk-or-test", transport=_transport(seen))
    res = await p.ping("cohere/north-mini-code:free")
    assert res["ok"] and res["tool_calling"] and seen["auth"] == "Bearer sk-or-test" and seen["title"] == "STARK OS"
    info = await p.key_info()
    assert info["free_model_daily_requests"]["remaining"] == 41 and "sk-or-test" not in json.dumps(info)
    bad = OpenRouterProvider("sk-or-test", transport=_transport({}, {"x/y:free": (404, "No endpoints found for x/y")}))
    res = await bad.ping("x/y:free")
    assert not res["ok"] and res["kind"] == "unavailable" and bad.model_health["x/y:free"].as_dict()["cooling_down_s"] > 0


@pytest.mark.parametrize("status,msg,kind", [
    (429, "Provider returned error", "rate_limited"), (403, "only available on agentic harnesses", "forbidden"),
    (404, "No endpoints found", "unavailable"), (502, "bad gateway", "server"), (401, "No auth", "auth"),
    (400, "messages: invalid", "request")])
def test_failure_classification(status, msg, kind):
    assert classify_failure(ProviderError(msg, status=status)) == kind


def test_openai_message_conversion_roundtrip():
    msgs = [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                          {"type": "tool_use", "id": "c1", "name": "fs__list", "input": {"path": "."}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"ok\":true}"}]},
    ]
    out = to_openai_messages("sys", msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {"name": "fs__list", "arguments": "{\"path\": \".\"}"}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\":true}"}


async def test_tool_call_parsing():
    seen: dict = {}
    p = OpenAICompatProvider("x", "https://example.test/api/v1", transport=_transport(seen))
    resp = await p.complete(_req(model="cohere/north-mini-code:free"))
    assert resp.stop_reason == "tool_use" and resp.tool_calls[0]["name"] == "system__metrics"
    assert resp.input_tokens == 10


def test_router_requires_key(settings):
    k, _ = make_kernel(settings)
    with pytest.raises(NoModelAvailable, match="OPENROUTER_API_KEY"):
        k.router.select(k.registry.get("jarvis"))


async def test_router_tiers_and_pins(settings):
    settings.openrouter_api_key = "sk-or-test"
    settings.openrouter_models = {"deep": "cohere/north-mini-code:free"}
    r = ModelRouter(settings, {"openrouter": OpenRouterProvider("sk-or-test", transport=_transport({}))})
    await r.prepare()
    k, _ = make_kernel(settings)
    assert r.select(k.registry.get("ultron")).model == "cohere/north-mini-code:free"  # deep tier pinned
    route = r.select(k.registry.get("friday"))  # fast tier
    assert route.model == "nvidia/nemotron-3.5-super-vl:free" and len(route.candidates) > 1


async def test_kernel_fails_over_to_next_free_model(settings):
    seen: dict = {}
    pool = OpenRouterProvider("sk-or-test", transport=_transport(seen, {
        "nvidia/nemotron-3.5-super-vl:free": (429, "Provider returned error"),
        "cohere/north-mini-code:free": (404, "No endpoints found")}))
    await pool.refresh_catalog()
    settings.openrouter_api_key = "sk-or-test"
    from stark.main import build_kernel

    k = build_kernel(settings, {"openrouter": pool})
    agent = k.registry.get("friday")
    task = k._create_task(agent_id="friday", instruction="cpu")
    resp = await k._call_model(agent, task, "sys", [{"role": "user", "content": "cpu?"}], [])
    assert seen["models"][:3] == ["nvidia/nemotron-3.5-super-vl:free", "cohere/north-mini-code:free",
                                  seen["models"][2]] and resp.model == seen["models"][2]
    assert pool.model_health["nvidia/nemotron-3.5-super-vl:free"].cooldown_reason == "rate_limited"
    # the cooling-down models are skipped on the next call
    assert pool.candidates("fast")[0] not in {"nvidia/nemotron-3.5-super-vl:free", "cohere/north-mini-code:free"}


async def test_daily_quota_exhaustion_is_reported_clearly(settings):
    msg = "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day"
    pool = OpenRouterProvider("sk-or-test", transport=_transport({}, {m: (429, msg) for m in
                                                                     sum(TIER_PREFERENCES.values(), [])}))
    from stark.main import build_kernel

    settings.openrouter_api_key = "sk-or-test"
    k = build_kernel(settings, {"openrouter": pool})
    task = k._create_task(agent_id="u", instruction="hi")
    with pytest.raises(ProviderError, match="daily free-request limit"):
        await k._call_model(k.registry.get("u"), task, "sys", [{"role": "user", "content": "hi"}], [])


def test_cost_accounting_free_only(settings):
    k, _ = make_kernel(settings)
    assert k.obs.cost("cohere/north-mini-code:free", 10**6, 10**6, "openrouter") == (0.0, True)
    assert k.obs.cost("openrouter/free", 10, 10, "openrouter") == (0.0, True)
    assert k.obs.cost("big/paid-model", 10, 10, "openrouter") == (0.0, False)
