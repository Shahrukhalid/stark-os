"""FastAPI application factory and HTTP API."""

from __future__ import annotations

import asyncio
import hmac
import platform
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from . import __version__
from .config import REPO_ROOT, Settings, load_dotenv
from .core.addressing import parse_address
from .core.agent_registry import AgentRegistry
from .core.db import (
    Approval,
    AuditEntry,
    ContentItem,
    Conversation,
    Database,
    Grant,
    Task,
    Turn,
    UsageRecord,
    to_dict,
)
from .core.events import EventBus
from .core.model_router import ModelRouter
from .core.observability import configure_logging, log
from .core.permissions import Mode
from .core.runtime import TERMINAL, Kernel
from .providers import ModelProvider
from .tools import build_registry
from .tools import social as social_tools


def build_kernel(settings: Settings, providers: dict[str, ModelProvider] | None = None) -> Kernel:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for root in settings.workspace_roots:
        root.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_url)
    db.create_all()
    bus = EventBus()
    tools = build_registry(settings)
    registry = AgentRegistry.load(settings.agents_dir, known_tools=tools.ids())
    router = ModelRouter(settings, providers)
    kernel = Kernel(settings=settings, db=db, bus=bus, registry=registry, tools=tools, router=router)
    # emergency stop = fire suppression: nothing in the content queue can go out until resumed (with approval)
    kernel.estop_hooks = [lambda: social_tools.pause_queue(kernel, True)]
    # recover from a previous crash: nothing can still be running in a fresh process
    with db.session() as s:
        for t in s.scalars(select(Task).where(Task.status.not_in(list(TERMINAL)))).all():
            t.status, t.error = "failed", "interrupted by API restart"
        for a in s.scalars(select(Approval).where(Approval.status == "pending")).all():
            a.status, a.decided_by = "expired", "system"
        for c in s.scalars(select(ContentItem).where(ContentItem.status == "publishing")).all():
            c.status = "published" if c.external_id else "failed"
            c.error = ("interrupted by API restart while publishing. Check the platform; retrying is safe "
                       "(requests are idempotent).")
    return kernel


# ---------------------------------------------------------------- schemas
class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=20_000)
    agent_id: str | None = None
    conversation_id: str | None = None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "cancel"]
    note: str | None = None


class MemoryPatch(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    namespace: str = "user:preferences"
    layer: Literal["preference", "semantic", "procedural"] = "preference"


class MemorySettingsIn(BaseModel):
    enabled: bool


class ModeIn(BaseModel):
    mode: Mode


class PingIn(BaseModel):
    models: list[str] | None = None
    limit: int = Field(20, ge=1, le=50)


class BlueskyIn(BaseModel):
    handle: str = Field(..., min_length=3, max_length=253)
    app_password: str = Field(..., min_length=8, max_length=64)


class MastodonIn(BaseModel):
    base_url: str = Field(..., min_length=4, max_length=300)
    access_token: str = Field(..., min_length=8, max_length=300)


class ItemActionIn(BaseModel):
    fingerprint: str = Field(..., min_length=64, max_length=64, description="from the queue: the text you saw")


class ScheduleIn(ItemActionIn):
    when: datetime
    auto: bool = False


class GrantIn(BaseModel):
    agent_id: str
    tool_id: str
    scope: str = ""
    hours: int = Field(24, ge=1, le=24 * 30)


def create_app(settings: Settings | None = None, providers: dict[str, ModelProvider] | None = None) -> FastAPI:
    if settings is None:
        load_dotenv(REPO_ROOT / ".env")
        settings = Settings.from_env()
    configure_logging()
    if not settings.api_token or len(settings.api_token) < 24:
        raise RuntimeError("STARK_API_TOKEN must be set to a random string of at least 24 characters "
                           "(run: python scripts/setup.py)")
    from .core.observability import register_secret

    register_secret(settings.api_token)
    for secret in (settings.openrouter_api_key, settings.bluesky_app_password, settings.mastodon_access_token,
                   settings.tavily_api_key, settings.brave_api_key):
        register_secret(secret)
    holder: dict[str, Kernel] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        holder["k"] = build_kernel(settings, providers)
        app.state.kernel = holder["k"]
        await holder["k"].router.prepare()
        log.info("STARK OS API ready", extra={"ctx": {"agents": holder["k"].registry.ids(),
                                                      "providers": holder["k"].router.configured_providers()}})
        scheduler = asyncio.create_task(_scheduler_loop(holder["k"]))
        yield
        scheduler.cancel()
        for job in list(holder["k"]._running.values()):
            job.cancel()

    async def _scheduler_loop(k: Kernel) -> None:
        """Publishes posts you approved for a time ("publish automatically"). Nothing else runs unattended."""
        social = k.tools.get("social.publish").social
        while True:
            await asyncio.sleep(max(1.0, settings.scheduler_interval_s))
            try:
                await social_tools.run_scheduler_once(k, social, settings)
            except Exception as exc:  # never let the loop die
                log.warning(f"scheduler error: {exc}")

    app = FastAPI(title="STARK OS API", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["*"],
                       allow_headers=["authorization", "content-type"], allow_credentials=False)

    def kernel() -> Kernel:
        return holder["k"]

    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        if not token and request.url.path == "/api/events":
            token = request.query_params.get("token", "")  # EventSource cannot send headers
        if not token or not hmac.compare_digest(token.encode("utf-8", "surrogateescape"),
                                                settings.api_token.encode("utf-8")):
            raise HTTPException(401, "invalid or missing API token")

    @app.exception_handler(KeyError)
    async def _not_found(_: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    api = Depends(auth)

    # ---------------------------------------------------------- system
    @app.get("/api/system/status", dependencies=[api])
    async def system_status(k: Kernel = Depends(kernel)):
        providers_out = {}
        for name, prov in k.router.providers.items():
            configured, detail = prov.configured()
            healthy, hdetail = (await prov.health()) if configured else (False, detail)
            providers_out[name] = {"configured": configured, "healthy": healthy, "detail": hdetail,
                                   "pool_size": len(getattr(prov, "pool", []))}
        tools = [t.info() for t in k.tools.all()]
        return {
            "version": __version__,
            "host": {"os": platform.system(), "release": platform.release(), "arch": platform.machine(),
                     "python": platform.python_version()},
            "mode": k.perms.global_mode.value,
            "emergency_stop": k.perms.emergency_stop,
            "memory_enabled": k.memory.enabled,
            "providers": providers_out,
            "active_providers": k.router.configured_providers(),
            "tools": {t["id"]: t["availability"] for t in tools},
            "workspace_roots": [str(r) for r in settings.workspace_roots],
            "database": "postgresql" if settings.database_url.startswith("postgres") else "sqlite",
            "requests_today": k.obs.requests_today(),
            "quota": await _quota(k),
            "running_tasks": len(k._running),
            "pending_approvals": len(_approvals(k, "pending")),
        }

    quota_cache: dict[str, Any] = {}

    async def _quota(k: Kernel, fresh: bool = False) -> dict | None:
        """Free-request quota from OpenRouter (cached 60s). None when unknown/offline."""
        pool = k.router.openrouter
        if pool is None or not pool.configured()[0]:
            return None
        if not fresh and quota_cache.get("at", 0) > time.time() - 60:
            return quota_cache.get("value")
        try:
            info = await pool.key_info()
            value = info.get("free_model_daily_requests")
        except Exception:
            value = None
        quota_cache.update(at=time.time(), value=value)
        return value

    @app.get("/api/models", dependencies=[api])
    async def models(k: Kernel = Depends(kernel)):
        pool = k.router.openrouter
        if pool is None:
            return {"configured": False, "catalog": [], "pool": [], "tiers": {}}
        from .providers.openrouter import PING_SNAPSHOT

        catalog = list(pool.catalog.values()) or [
            {"id": m, "name": m, "context_length": None, "tools": True, "chat": True, "input_modalities": [],
             "excluded": False, "snapshot": PING_SNAPSHOT.get(m)} for m in pool.pool]
        for m in catalog:
            m["in_pool"] = m["id"] in pool.pool
            m["health"] = pool.model_health[m["id"]].as_dict() if m["id"] in pool.model_health else None
        return {
            "configured": pool.configured()[0],
            "catalog_error": pool.catalog_error,
            "catalog": sorted(catalog, key=lambda m: (not m["in_pool"], m["id"])),
            "pool": pool.pool,
            "tiers": {t: pool.candidates(t, k.router.pins.get(t), limit=6) for t in ("deep", "balanced", "fast")},
            "pins": k.router.pins,
            "quota": await _quota(k),
            "requests_today": k.obs.requests_today(),
        }

    @app.post("/api/models/refresh", dependencies=[api])
    async def models_refresh(k: Kernel = Depends(kernel)):
        await k.router.prepare()
        return await models(k)

    @app.post("/api/models/ping", dependencies=[api])
    async def models_ping(body: PingIn, k: Kernel = Depends(kernel)):
        pool = k.router.openrouter
        if pool is None or not pool.configured()[0]:
            raise HTTPException(409, "OPENROUTER_API_KEY is not configured")
        targets = body.models or pool.pool
        if not pool.allow_paid:  # never spend money on a ping either
            from .providers.openrouter import META_ROUTER

            targets = [m for m in targets if m == META_ROUTER or m.endswith(":free") or m in pool.catalog]
        results = []
        for model in targets[: body.limit]:  # sequential: free models are rate-limited
            results.append(await pool.ping(model))
            k.bus.publish("model.ping", results[-1])
        k.obs.audit("user", "models.ping", "ok", detail={"count": len(results)})
        return {"results": results, "quota": await _quota(k, fresh=True)}

    @app.post("/api/settings/mode", dependencies=[api])
    async def set_mode(body: ModeIn, k: Kernel = Depends(kernel)):
        k.set_mode(body.mode)
        return {"mode": body.mode.value}

    @app.post("/api/estop", dependencies=[api])
    async def estop(k: Kernel = Depends(kernel)):
        return k.engage_emergency_stop()

    @app.post("/api/estop/reset", dependencies=[api])
    async def estop_reset(k: Kernel = Depends(kernel)):
        k.reset_emergency_stop()
        return {"engaged": False, "note": "The content queue stays paused until D.U.M.-E. resumes it with your approval."}

    # ---------------------------------------------------------- social (read-only views)
    @app.get("/api/social/accounts", dependencies=[api])
    async def social_accounts(k: Kernel = Depends(kernel)):
        tool = k.tools.get("social.accounts")
        return {"accounts": tool.social.accounts()}

    def _social(k: Kernel):
        return k.tools.get("social.publish").social

    @app.post("/api/social/accounts/bluesky", dependencies=[api])
    async def connect_bluesky(body: BlueskyIn, k: Kernel = Depends(kernel)):
        try:
            who = await _social(k).connect_bluesky(body.handle, body.app_password)
        except (social_tools.AdapterError, httpx.HTTPError) as exc:
            k.obs.audit("user", "social.connect", "error", target="bluesky")
            raise HTTPException(400, str(exc) if isinstance(exc, social_tools.AdapterError)
                                else "Could not reach Bluesky. Check your internet connection.")
        k.obs.audit("user", "social.connect", "ok", target=f"bluesky {who}")
        return {"connected_as": who, "accounts": _social(k).accounts()}

    @app.post("/api/social/accounts/mastodon", dependencies=[api])
    async def connect_mastodon(body: MastodonIn, k: Kernel = Depends(kernel)):
        try:
            who = await _social(k).connect_mastodon(body.base_url, body.access_token)
        except (social_tools.AdapterError, httpx.HTTPError) as exc:
            k.obs.audit("user", "social.connect", "error", target="mastodon")
            raise HTTPException(400, str(exc) if isinstance(exc, social_tools.AdapterError)
                                else "Could not reach that Mastodon server. Check the address.")
        k.obs.audit("user", "social.connect", "ok", target=f"mastodon {who}")
        return {"connected_as": who, "accounts": _social(k).accounts()}

    @app.delete("/api/social/accounts/{platform}", dependencies=[api])
    async def disconnect(platform: str, k: Kernel = Depends(kernel)):
        social = _social(k)
        if platform not in social_tools.ACCOUNT_FIELDS:
            raise HTTPException(404, "unknown platform")
        if social.store.from_env.get(platform):
            raise HTTPException(409, "This account is set in your .env file; remove it there.")
        social.store.remove(platform)
        k.obs.audit("user", "social.disconnect", "ok", target=platform)
        return {"accounts": social.accounts()}

    def _item_or_404(k: Kernel, item_id: str, fp: str) -> dict:
        item = social_tools._item(k, item_id)
        if item is None:
            raise HTTPException(404, "no such content item")
        if social_tools.fingerprint(item) != fp:
            raise HTTPException(409, "This post changed since you looked at it. Refresh and check it again.")
        return item

    @app.post("/api/social/items/{item_id}/publish", dependencies=[api])
    async def publish_now(item_id: str, body: ItemActionIn, k: Kernel = Depends(kernel)):
        """You clicked Publish on the exact text shown: that click is the approval."""
        _item_or_404(k, item_id, body.fingerprint)
        res = await social_tools.publish_item(k, _social(k), settings, item_id, approved_fp=body.fingerprint,
                                              actor="user")
        k.obs.audit("user", "social.publish", "ok" if res.ok else "error", target=item_id,
                    detail={"summary": res.summary[:300], "simulated": res.simulated})
        return {"ok": res.ok, "summary": res.summary, "simulated": res.simulated, "error": res.error}

    @app.post("/api/social/items/{item_id}/schedule", dependencies=[api])
    async def schedule_item(item_id: str, body: ScheduleIn, k: Kernel = Depends(kernel)):
        item = _item_or_404(k, item_id, body.fingerprint)
        when = (body.when if body.when.tzinfo else body.when.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        if when <= datetime.now(timezone.utc):
            raise HTTPException(400, "Pick a time in the future.")
        if item["status"] not in ("draft", "scheduled", "failed"):
            raise HTTPException(409, f"This post is {item['status']}.")
        if social_tools._run_check(settings, item)["verdict"] == "fail":
            raise HTTPException(409, "Fix the problems the check found before scheduling.")
        social_tools._update(k, item_id, status="scheduled", scheduled_for=when, auto_publish=body.auto,
                             approved_fp=body.fingerprint if body.auto else None,
                             approved_at=datetime.now(timezone.utc) if body.auto else None, error=None)
        k.obs.audit("user", "social.schedule", "ok", target=item_id,
                    detail={"when": when.isoformat(), "auto_publish": body.auto})
        return {"ok": True, "scheduled_for": when.isoformat(), "auto_publish": body.auto}

    @app.post("/api/social/items/{item_id}/unschedule", dependencies=[api])
    async def unschedule_item(item_id: str, k: Kernel = Depends(kernel)):
        item = social_tools._item(k, item_id)
        if item is None:
            raise HTTPException(404, "no such content item")
        if item["status"] == "scheduled":
            social_tools._update(k, item_id, status="draft", scheduled_for=None, auto_publish=False, approved_fp=None)
        k.obs.audit("user", "social.unschedule", "ok", target=item_id)
        return {"ok": True}

    @app.post("/api/social/items/{item_id}/discard", dependencies=[api])
    async def discard_item(item_id: str, k: Kernel = Depends(kernel)):
        item = social_tools._item(k, item_id)
        if item is None:
            raise HTTPException(404, "no such content item")
        if item["status"] in ("published", "publishing"):
            raise HTTPException(409, "Already published: delete it on the platform itself.")
        social_tools._update(k, item_id, status="rejected", auto_publish=False, approved_fp=None)
        k.obs.audit("user", "social.discard", "ok", target=item_id)
        return {"ok": True}

    @app.post("/api/social/queue/pause", dependencies=[api])
    async def pause_all(paused: bool = True, k: Kernel = Depends(kernel)):
        n = social_tools.pause_queue(k, paused)
        k.obs.audit("user", "social.pause" if paused else "social.resume", "ok", detail={"items": n})
        return {"paused": paused, "items": n}

    @app.get("/api/social/queue", dependencies=[api])
    async def social_queue(status: str = "all", platform: str | None = None, limit: int = Query(100, ge=1, le=500),
                           k: Kernel = Depends(kernel)):
        if status not in {"all", "draft", "scheduled", "published", "failed", "rejected"}:
            raise HTTPException(400, "bad status")
        if platform and platform not in social_tools.PLATFORMS:
            raise HTTPException(400, "unknown platform")
        return {"items": social_tools.list_queue(k, status, platform, None, max(1, min(limit, 500))),
                "paused": social_tools.queue_paused(k)}

    # ---------------------------------------------------------- agents
    def _metrics(k: Kernel) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        with k.db.session() as s:
            rows = s.execute(select(Task.agent_id, Task.status, func.count(), func.sum(Task.input_tokens),
                                    func.sum(Task.output_tokens), func.sum(Task.cost_usd))
                             .group_by(Task.agent_id, Task.status)).all()
            finished = s.execute(select(Task.agent_id, Task.started_at, Task.finished_at)
                                 .where(Task.status == "completed", Task.started_at.is_not(None))
                                 .order_by(Task.finished_at.desc()).limit(500)).all()
        for agent_id, status, n, tin, tout, cost in rows:
            m = out.setdefault(agent_id, {"tasks": {}, "tokens": 0, "cost_usd": 0.0})
            m["tasks"][status] = n
            m["tokens"] += int((tin or 0) + (tout or 0))
            m["cost_usd"] = round(m["cost_usd"] + float(cost or 0), 4)
        durations: dict[str, list[float]] = {}
        for agent_id, start, end in finished:
            if start and end:
                durations.setdefault(agent_id, []).append((end - start).total_seconds())
        for agent_id, ds in durations.items():
            out.setdefault(agent_id, {"tasks": {}, "tokens": 0, "cost_usd": 0.0})["avg_seconds"] = round(
                sum(ds) / len(ds), 1)
        for m in out.values():
            done, failed = m["tasks"].get("completed", 0), m["tasks"].get("failed", 0)
            m["success_rate"] = round(done / (done + failed), 3) if done + failed else None
        return out

    def _agent_out(k: Kernel, cfg, metrics) -> dict[str, Any]:
        data = cfg.model_dump()
        try:
            route = k.router.select(cfg)
            data["model_in_use"] = {"provider": route.provider.name, "model": route.model, "reason": route.reason,
                                    "fallbacks": route.candidates[1:]}
        except Exception as exc:
            data["model_in_use"] = {"provider": None, "model": None, "reason": str(exc)}
        data["live"] = k.agent_status.get(cfg.id)
        data["metrics"] = metrics.get(cfg.id, {"tasks": {}, "tokens": 0, "cost_usd": 0.0, "success_rate": None})
        data["tool_details"] = [t.info() for t in k.tools.for_agent(cfg)]
        return data

    @app.get("/api/agents", dependencies=[api])
    async def agents(k: Kernel = Depends(kernel)):
        metrics = _metrics(k)
        return [_agent_out(k, a, metrics) for a in k.registry.all()]

    @app.get("/api/agents/{agent_id}", dependencies=[api])
    async def agent(agent_id: str, k: Kernel = Depends(kernel)):
        cfg = k.registry.get(agent_id)
        data = _agent_out(k, cfg, _metrics(k))
        with k.db.session() as s:
            data["recent_tasks"] = [to_dict(t) for t in s.scalars(
                select(Task).where(Task.agent_id == agent_id).order_by(Task.created_at.desc()).limit(25)).all()]
        return data

    # ---------------------------------------------------------- chat & tasks
    @app.post("/api/chat", dependencies=[api])
    async def chat(body: ChatIn, k: Kernel = Depends(kernel)):
        agent_id, text = body.agent_id, body.message
        addressed, rest = parse_address(body.message)
        if addressed and (agent_id is None or body.conversation_id is None):
            agent_id, text = addressed, rest
        agent_id = agent_id or "jarvis"
        if agent_id not in k.registry:
            raise HTTPException(404, f"unknown agent {agent_id}")
        try:
            task = k.submit_chat(agent_id, text, body.conversation_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return task

    @app.get("/api/conversations", dependencies=[api])
    async def conversations(k: Kernel = Depends(kernel), limit: int = Query(50, ge=1, le=500)):
        with k.db.session() as s:
            return [to_dict(c) for c in s.scalars(select(Conversation).order_by(Conversation.created_at.desc())
                                                   .limit(limit)).all()]

    @app.get("/api/conversations/{conv_id}/turns", dependencies=[api])
    async def turns(conv_id: str, k: Kernel = Depends(kernel)):
        with k.db.session() as s:
            return [to_dict(t) for t in s.scalars(select(Turn).where(Turn.conversation_id == conv_id)
                                                   .order_by(Turn.id)).all()]

    @app.get("/api/tasks", dependencies=[api])
    async def tasks(k: Kernel = Depends(kernel), limit: int = Query(50, ge=1, le=500), agent_id: str | None = None,
                    root_only: bool = False, status: str | None = None):
        with k.db.session() as s:
            stmt = select(Task).order_by(Task.created_at.desc()).limit(limit)
            if agent_id:
                stmt = stmt.where(Task.agent_id == agent_id)
            if root_only:
                stmt = stmt.where(Task.parent_id.is_(None))
            if status:
                stmt = stmt.where(Task.status == status)
            return [to_dict(t) for t in s.scalars(stmt).all()]

    @app.get("/api/tasks/{task_id}", dependencies=[api])
    async def task_detail(task_id: str, k: Kernel = Depends(kernel)):
        task = k.get_task(task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        with k.db.session() as s:
            tree = [to_dict(t) for t in s.scalars(select(Task).where(Task.root_id == task["root_id"])
                                                   .order_by(Task.created_at)).all()]
            audit = [to_dict(a) for a in s.scalars(select(AuditEntry).where(
                AuditEntry.task_id.in_([t["id"] for t in tree])).order_by(AuditEntry.id)).all()]
            approvals = [to_dict(a) for a in s.scalars(select(Approval).where(
                Approval.task_id.in_([t["id"] for t in tree]))).all()]
        return {"task": task, "tree": tree, "messages": k.messages.for_root(task["root_id"]),
                "audit": audit, "approvals": approvals}

    @app.post("/api/tasks/{task_id}/cancel", dependencies=[api])
    async def cancel(task_id: str, k: Kernel = Depends(kernel)):
        if not k.cancel(task_id):
            raise HTTPException(409, "task is not running")
        return {"cancelled": True}

    @app.get("/api/messages", dependencies=[api])
    async def messages(k: Kernel = Depends(kernel), root_id: str | None = None,
                       limit: int = Query(100, ge=1, le=1000)):
        return k.messages.for_root(root_id) if root_id else k.messages.recent(limit)

    # ---------------------------------------------------------- approvals
    def _approvals(k: Kernel, status: str | None) -> list[dict]:
        with k.db.session() as s:
            stmt = select(Approval).order_by(Approval.created_at.desc()).limit(200)
            if status:
                stmt = stmt.where(Approval.status == status)
            return [to_dict(a) for a in s.scalars(stmt).all()]

    @app.get("/api/approvals", dependencies=[api])
    async def approvals(k: Kernel = Depends(kernel), status: str | None = None):
        return _approvals(k, status)

    @app.post("/api/approvals/{approval_id}/decision", dependencies=[api])
    async def decide(approval_id: str, body: DecisionIn, k: Kernel = Depends(kernel)):
        status = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[body.decision]
        if status == "approved" and k.perms.emergency_stop:
            raise HTTPException(409, "emergency stop engaged; reset it before approving actions")
        out = k.approvals.decide(approval_id, status, decided_by="user", note=body.note)
        if out is None:
            raise HTTPException(409, "approval not pending")
        k.obs.audit("user", "approval.decide", status, target=out["tool_id"], task_id=out["task_id"])
        return out

    @app.get("/api/grants", dependencies=[api])
    async def grants(k: Kernel = Depends(kernel)):
        with k.db.session() as s:
            return [to_dict(g) for g in s.scalars(select(Grant)).all()]

    @app.post("/api/grants", dependencies=[api])
    async def create_grant(body: GrantIn, k: Kernel = Depends(kernel)):
        cfg = k.registry.get(body.agent_id)
        tool = k.tools.get(body.tool_id)
        if body.tool_id not in cfg.tools:
            raise HTTPException(400, f"{body.agent_id} does not have {body.tool_id} in its allowlist")
        if tool.risk.value != "write":
            raise HTTPException(400, "standing grants only cover reversible 'write' tools")
        with k.db.session() as s:
            g = Grant(agent_id=body.agent_id, tool_id=body.tool_id, scope=body.scope,
                      expires_at=datetime.now(timezone.utc) + timedelta(hours=body.hours))
            s.add(g)
            s.flush()
            data = to_dict(g)
        k.obs.audit("user", "grant.create", "ok", target=f"{body.agent_id}:{body.tool_id}:{body.scope}")
        return data

    @app.delete("/api/grants/{grant_id}", dependencies=[api])
    async def delete_grant(grant_id: str, k: Kernel = Depends(kernel)):
        with k.db.session() as s:
            g = s.get(Grant, grant_id)
            if g is None:
                raise HTTPException(404, "grant not found")
            s.delete(g)
        k.obs.audit("user", "grant.delete", "ok", target=grant_id)
        return {"deleted": True}

    # ---------------------------------------------------------- memory
    @app.get("/api/memory", dependencies=[api])
    async def memory_list(k: Kernel = Depends(kernel), namespace: str | None = None, layer: str | None = None,
                          q: str | None = None):
        return {"enabled": k.memory.enabled, "memories": k.memory.list(namespace=namespace, layer=layer, q=q)}

    @app.post("/api/memory", dependencies=[api])
    async def memory_create(body: MemoryCreate, k: Kernel = Depends(kernel)):
        try:
            return k.memory.save(actor=None, namespace=body.namespace, layer=body.layer, content=body.content,
                                 source="user", consent=True)
        except (PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/memory/{memory_id}", dependencies=[api])
    async def memory_update(memory_id: str, body: MemoryPatch, k: Kernel = Depends(kernel)):
        out = k.memory.update(memory_id, body.content)
        if out is None:
            raise HTTPException(404, "memory not found")
        k.obs.audit("user", "memory.update", "ok", target=memory_id)
        return out

    @app.delete("/api/memory/{memory_id}", dependencies=[api])
    async def memory_delete(memory_id: str, k: Kernel = Depends(kernel)):
        if not k.memory.delete(memory_id):
            raise HTTPException(404, "memory not found")
        k.obs.audit("user", "memory.delete", "ok", target=memory_id)
        return {"deleted": True}

    @app.get("/api/memory/export", dependencies=[api])
    async def memory_export(k: Kernel = Depends(kernel)):
        return PlainTextResponse(k.memory.export(), media_type="application/json",
                                 headers={"content-disposition": "attachment; filename=stark-memory-export.json"})

    @app.post("/api/memory/settings", dependencies=[api])
    async def memory_settings(body: MemorySettingsIn, k: Kernel = Depends(kernel)):
        k.memory.set_enabled(body.enabled)
        k.obs.audit("user", "memory.enabled", str(body.enabled).lower())
        return {"enabled": body.enabled}

    # ---------------------------------------------------------- tools
    @app.get("/api/tools", dependencies=[api])
    async def tools(k: Kernel = Depends(kernel)):
        out = []
        for t in k.tools.all():
            info = t.info()
            info["agents"] = [a.id for a in k.registry.all() if t in k.tools.for_agent(a)]
            out.append(info)
        return out

    @app.post("/api/tools/{tool_id}/run", dependencies=[api])
    async def run_tool(tool_id: str, request: Request, k: Kernel = Depends(kernel)):
        if tool_id not in k.tools.ids():
            raise HTTPException(404, "unknown tool")
        args = await request.json() if await request.body() else {}
        return await k.run_tool_as_user(tool_id, args)

    # ---------------------------------------------------------- observability
    @app.get("/api/audit", dependencies=[api])
    async def audit(k: Kernel = Depends(kernel), limit: int = Query(200, ge=1, le=2000)):
        with k.db.session() as s:
            return [to_dict(a) for a in s.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)).all()]

    @app.get("/api/usage", dependencies=[api])
    async def usage(k: Kernel = Depends(kernel)):
        with k.db.session() as s:
            def grouped(col):
                return [{"key": r[0], "calls": r[1], "input_tokens": int(r[2] or 0), "output_tokens": int(r[3] or 0),
                         "cost_usd": round(float(r[4] or 0), 4), "unknown_cost_calls": int(r[5] or 0)}
                        for r in s.execute(select(col, func.count(), func.sum(UsageRecord.input_tokens),
                                                  func.sum(UsageRecord.output_tokens), func.sum(UsageRecord.cost_usd),
                                                  func.sum(case((UsageRecord.cost_known.is_(False), 1), else_=0)))
                                           .group_by(col)).all()]
            recent = [to_dict(u) for u in s.scalars(select(UsageRecord).order_by(UsageRecord.id.desc()).limit(50)).all()]
            by_agent = grouped(UsageRecord.agent_id)
            by_model = grouped(UsageRecord.model)
        return {"requests_today": k.obs.requests_today(), "quota": await _quota(k),
                "by_agent": by_agent, "by_model": by_model, "recent": recent}

    @app.get("/api/events", dependencies=[api])
    async def events(request: Request, k: Kernel = Depends(kernel)):
        q = k.bus.subscribe()

        async def stream():
            try:
                yield "retry: 3000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {payload}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                k.bus.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

    app.state.kernel = kernel
    return app


def run() -> None:  # console entry point: `stark-api`
    import uvicorn

    load_dotenv(REPO_ROOT / ".env")
    settings = Settings.from_env()
    # access_log=False: the event stream authenticates with ?token=, which must never reach a log file
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    run()
