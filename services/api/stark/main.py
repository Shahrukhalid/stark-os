"""FastAPI application factory and HTTP API."""

from __future__ import annotations

import asyncio
import hmac
import json
from csv import Error as csv_error
import platform
import time
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
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
from .ics import build_calendar
from .core.model_router import ModelRouter, NoModelAvailable
from .core.observability import configure_logging, log
from .core.permissions import Mode
from .core.runtime import TERMINAL, Kernel
from .providers import ModelProvider
from . import autopilot as ap
from . import automations, growth, hub, insights, reach
from .core.db import Campaign
from .tools import build_registry
from .tools import social as social_tools


def _owner_only(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:  # e.g. Windows or a read-only mount: best effort
        pass


def build_kernel(settings: Settings, providers: dict[str, ModelProvider] | None = None) -> Kernel:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _owner_only(settings.data_dir, 0o700)  # conversations, memories and logins: owner only
    for root in settings.workspace_roots:
        root.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_url)
    db.create_all()
    if settings.database_url.startswith("sqlite:///"):
        db_file = Path(settings.database_url.removeprefix("sqlite:///"))
        for f in (db_file, db_file.with_name(db_file.name + "-wal"), db_file.with_name(db_file.name + "-shm")):
            if f.exists():
                _owner_only(f, 0o600)
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


class WatchIn(BaseModel):
    kind: Literal["keyword", "hashtag", "account"] | None = None
    query: str | None = Field(None, max_length=200)
    platforms: list[str] | None = None
    label: str | None = Field(None, max_length=120)
    enabled: bool | None = None
    interval_min: int | None = Field(None, ge=5, le=1440)


class ImageIn(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=600)
    width: int = Field(1024, ge=256, le=1536)
    height: int = Field(1024, ge=256, le=1536)


class RulesIn(BaseModel):
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class FeedsIn(BaseModel):
    feeds: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class MessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class PlanIn(BaseModel):
    categories: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    slots: list[dict[str, Any]] = Field(default_factory=list, max_length=70)


class ItemOptionsIn(BaseModel):
    category: str | None = Field(None, max_length=40)
    reply_control: str | None = None


class StarterPackIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field("", max_length=300)
    handles: list[str] = Field(..., min_length=1, max_length=150)


class DraftIn(BaseModel):
    platform: str
    category: str = Field("", max_length=40)
    reply_control: str | None = None
    text: str = Field(..., min_length=1, max_length=10_000)
    thread: list[str] = Field(default_factory=list, max_length=25)
    kind: str = "post"
    campaign: str = Field("", max_length=120)
    reply_to: str | None = Field(None, max_length=300)


class ImportIn(BaseModel):
    csv: str = Field(..., min_length=10, max_length=2_000_000)


class EvergreenIn(BaseModel):
    days: int | None = None


class SnippetIn(BaseModel):
    kind: str
    name: str = Field(..., max_length=120)
    body: str = Field(..., max_length=5000)
    platforms: list[str] = Field(default_factory=list)


class ItemActionIn(BaseModel):
    fingerprint: str = Field(..., min_length=64, max_length=64, description="from the queue: the text you saw")


class PublishIn(ItemActionIn):
    live: bool | None = Field(None, description="what the dashboard told you: true = real post, false = simulation")


class ScheduleIn(ItemActionIn):
    when: datetime
    auto: bool = False


class SourceIn(BaseModel):
    type: Literal["rss", "hn", "reddit", "search"]
    value: str = Field(..., min_length=1, max_length=500)


class CampaignPatch(BaseModel):
    enabled: bool | None = None
    topics: list[str] | None = Field(None, max_length=30)
    keywords: list[str] | None = Field(None, max_length=30)
    avoid_terms: list[str] | None = Field(None, max_length=30)
    audience: str | None = Field(None, max_length=500)
    tone: str | None = Field(None, max_length=300)
    platforms: list[str] | None = Field(None, max_length=6)
    sources: list[SourceIn] | None = Field(None, max_length=20)
    post_times: list[str] | None = Field(None, max_length=12)
    timezone: str | None = Field(None, max_length=64)
    daily_cap: int | None = Field(None, ge=1, le=10)
    min_gap_minutes: int | None = Field(None, ge=15, le=1440)
    trust_level: Literal["copilot", "veto", "auto"] | None = None
    veto_minutes: int | None = Field(None, ge=10, le=1440)
    link_policy: Literal["always", "never"] | None = None
    fact_check: bool | None = None
    research_every_h: float | None = Field(None, ge=1, le=48)
    max_new_per_run: int | None = Field(None, ge=1, le=5)


class CampaignIn(CampaignPatch):
    name: str = Field(..., min_length=2, max_length=120)
    platforms: list[str] = Field(..., min_length=1, max_length=6)
    sources: list[SourceIn] = Field(..., min_length=1, max_length=20)
    post_times: list[str] = Field(default_factory=lambda: ["09:00", "13:00", "18:00"], min_length=1, max_length=12)
    timezone: str = Field("UTC", max_length=64)


class ApproveItem(BaseModel):
    id: str = Field(..., max_length=40)
    fingerprint: str = Field(..., min_length=64, max_length=64)


class AutomationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    actions: list[dict[str, Any]] = Field(..., min_length=1, max_length=6)
    recipe: str = ""


class RecipeIn(BaseModel):
    recipe: str = Field(..., max_length=60)


class AutomationTestIn(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    run: bool = False


class ApproveIn(BaseModel):
    items: list[ApproveItem] = Field(..., min_length=1, max_length=50)


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
                   settings.tavily_api_key, settings.brave_api_key, settings.telegram_bot_token,
                   settings.discord_webhook_url, settings.webhook_secret, *settings.webhook_urls,
                   settings.threads_access_token, settings.discord_post_webhook_url, settings.slack_webhook_url):
        register_secret(secret)
    holder: dict[str, Kernel] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        holder["k"] = build_kernel(settings, providers)
        app.state.kernel = holder["k"]
        await holder["k"].router.prepare()
        log.info("STARK OS API ready", extra={"ctx": {"agents": holder["k"].registry.ids(),
                                                      "providers": holder["k"].router.configured_providers()}})
        social = holder["k"].tools.get("social.publish").social
        holder["k"].autopilot = ap.Autopilot(holder["k"], social, settings)
        holder["k"].listening = growth.Listening(holder["k"], social, settings)
        holder["k"].notifier = growth.Notifier(holder["k"], social, settings)
        scheduler = asyncio.create_task(_scheduler_loop(holder["k"]))
        holder["k"].webhooks = hub.Webhooks(holder["k"], settings)
        background = [asyncio.create_task(holder["k"].notifier.run()), asyncio.create_task(holder["k"].webhooks.run()),
                      asyncio.create_task(hub.recycler_loop(holder["k"], social, settings)),
                      asyncio.create_task(_snapshot_loop(holder["k"], social)),
                      asyncio.create_task(_feeds_loop(holder["k"], social))]
        holder["k"].automations = automations.Engine(holder["k"], social, settings, holder["k"].notifier)
        background.append(asyncio.create_task(holder["k"].automations.loop()))
        yield
        scheduler.cancel()
        for job in background:
            job.cancel()
        for job in list(holder["k"]._running.values()):
            job.cancel()

    async def _snapshot_loop(k: Kernel, social) -> None:
        """Follower counts of connected accounts, a few times a day (the latest one each day is kept)."""
        while True:
            try:
                await insights.snapshot(k, social)
            except Exception as exc:  # never let the loop die
                log.warning(f"snapshot error: {exc}")
            await asyncio.sleep(6 * 3600)

    async def _feeds_loop(k: Kernel, social) -> None:
        """Your own YouTube / podcast / blog feeds: new items become drafts (checked every hour)."""
        while True:
            await asyncio.sleep(60)
            try:
                if reach.get_feeds(k):
                    await reach.check_feeds(k, social, settings, lambda url: reach.fetch_feed_items(k, url))
            except Exception as exc:
                log.warning(f"own feeds error: {exc}")
            await asyncio.sleep(3540)

    async def _scheduler_loop(k: Kernel) -> None:
        """Publishes posts approved for a time (by you, or by an Autopilot campaign you set to veto/auto)
        and runs due Autopilot campaigns."""
        social = k.tools.get("social.publish").social
        autopilot_job: asyncio.Task | None = None
        listen_job: asyncio.Task | None = None
        try:
            while True:
                await asyncio.sleep(max(1.0, settings.scheduler_interval_s))
                try:
                    await social_tools.run_scheduler_once(k, social, settings)
                except Exception as exc:  # never let the loop die
                    log.warning(f"scheduler error: {exc}")
                # Autopilot runs (research + model calls) take minutes: run them beside the publisher, so a long
                # run never delays a post that is due. At most one tick at a time.
                if autopilot_job is None or autopilot_job.done():
                    if autopilot_job is not None and not autopilot_job.cancelled() and autopilot_job.exception():
                        log.warning(f"autopilot error: {autopilot_job.exception()}")
                    autopilot_job = asyncio.create_task(k.autopilot.tick())
                if settings.listening_enabled and (listen_job is None or listen_job.done()):
                    listen_job = asyncio.create_task(k.listening.run_once())
        finally:
            for job in (autopilot_job, listen_job):
                if job is not None:
                    job.cancel()

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
    async def publish_now(item_id: str, body: PublishIn, k: Kernel = Depends(kernel)):
        """You clicked Publish on the exact text shown: that click is the approval."""
        item = _item_or_404(k, item_id, body.fingerprint)
        if body.live is not None:
            really_live = _social(k).adapter(item["platform"]) is not None
            if really_live != body.live:
                # Never post publicly when the person clicked "Run simulation" (or claim a simulation was real).
                raise HTTPException(409, "Your account connection changed since this page loaded. "
                                         "Refresh and check whether this will post for real.")
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

    @app.get("/api/social/calendar.ics", dependencies=[api])
    async def social_calendar(k: Kernel = Depends(kernel)):
        items = social_tools.list_queue(k, "scheduled", None, None, 500)
        items.sort(key=lambda i: i["scheduled_for"] or "")
        return Response(build_calendar(items), media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="stark-schedule.ics"',
                                 "Cache-Control": "no-store"})

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
        if item.get("autopilot"):
            _ap(k).veto(item_id)  # discarding an Autopilot post is a veto: it counts against the campaign's trust
        else:
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

    analytics_cache: dict[str, Any] = {"at": 0.0, "data": None}

    @app.get("/api/social/analytics", dependencies=[api])
    async def social_analytics(refresh: bool = False, k: Kernel = Depends(kernel)):
        """Published posts with real engagement. Cached for 5 minutes to stay inside platform rate limits."""
        now = time.monotonic()
        if not refresh and analytics_cache["data"] is not None and now - analytics_cache["at"] < 300:
            return analytics_cache["data"]
        data = await social_tools.analytics_report(k, _social(k))
        analytics_cache.update(at=now, data=data)
        return data

    # ---------------------------------------------------------- listening, notifications, images
    @app.get("/api/listening/watches", dependencies=[api])
    async def list_watches(k: Kernel = Depends(kernel)):
        return {"watches": k.listening.watches(), "enabled": settings.listening_enabled}

    @app.post("/api/listening/watches", dependencies=[api])
    async def add_watch(body: WatchIn, k: Kernel = Depends(kernel)):
        try:
            w = k.listening.add(body.model_dump(exclude_none=True))
        except growth.GrowthError as exc:
            raise HTTPException(400, str(exc)) from None
        k.obs.audit("user", "listening.watch", "ok", target=f"{w['kind']} {w['query']}")
        return w

    @app.patch("/api/listening/watches/{watch_id}", dependencies=[api])
    async def edit_watch(watch_id: str, body: WatchIn, k: Kernel = Depends(kernel)):
        try:
            w = k.listening.update(watch_id, body.model_dump(exclude_none=True))
        except growth.GrowthError as exc:
            raise HTTPException(400, str(exc)) from None
        if w is None:
            raise HTTPException(404, "no such watch")
        return w

    @app.delete("/api/listening/watches/{watch_id}", dependencies=[api])
    async def delete_watch(watch_id: str, k: Kernel = Depends(kernel)):
        if not k.listening.delete(watch_id):
            raise HTTPException(404, "no such watch")
        return {"ok": True}

    @app.get("/api/listening/mentions", dependencies=[api])
    async def list_mentions(status: str = "new", watch_id: str | None = None, limit: int = Query(100, ge=1, le=500),
                            k: Kernel = Depends(kernel)):
        if status not in ("new", "done", "dismissed", "all"):
            raise HTTPException(400, "bad status")
        return {"mentions": k.listening.mentions(status, watch_id, limit), "competitors": k.listening.competitors()}

    @app.post("/api/listening/mentions/{mention_id}/status", dependencies=[api])
    async def mention_status(mention_id: str, status: str, k: Kernel = Depends(kernel)):
        try:
            ok = k.listening.set_status(mention_id, status)
        except growth.GrowthError as exc:
            raise HTTPException(400, str(exc)) from None
        if not ok:
            raise HTTPException(404, "no such mention")
        return {"ok": True}

    @app.post("/api/listening/run", dependencies=[api])
    async def run_listening(k: Kernel = Depends(kernel)):
        return await k.listening.run_once(force=True)

    @app.get("/api/notify/status", dependencies=[api])
    async def notify_status(k: Kernel = Depends(kernel)):
        return k.notifier.status()

    @app.post("/api/notify/test", dependencies=[api])
    async def notify_test(k: Kernel = Depends(kernel)):
        n = k.notifier
        if not (n.telegram or n.discord):
            raise HTTPException(409, "Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID or DISCORD_WEBHOOK_URL in .env first.")
        await n.send("✅ STARK OS is connected. Approvals, new drafts and urgent mentions will arrive here.")
        return {"ok": True}

    @app.post("/api/notify/digest", dependencies=[api])
    async def notify_digest(k: Kernel = Depends(kernel)):
        n = k.notifier
        if not (n.telegram or n.discord):
            raise HTTPException(409, "No phone notifications configured.")
        await n.send(n.digest_text())
        return {"ok": True}

    @app.post("/api/media/generate", dependencies=[api])
    async def media_generate(body: ImageIn, k: Kernel = Depends(kernel)):
        try:
            out = await growth.generate_image(settings, body.prompt, body.width, body.height)
        except growth.GrowthError as exc:
            raise HTTPException(400, str(exc)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach the image service. Check your internet connection.") from None
        k.obs.audit("user", "media.generate_image", "ok", target=out["file"])
        return out

    @app.get("/api/media/file", dependencies=[api])
    async def media_file(name: str):
        """A generated image, by file name. The file is picked from the folder listing, never built from input."""
        folder = settings.workspace_roots[0] / growth.IMAGE_DIR if settings.workspace_roots else None
        found = next((p for p in folder.iterdir() if p.is_file() and p.name == name), None) \
            if folder is not None and folder.is_dir() else None
        if found is None:
            raise HTTPException(404, "no such image")
        try:
            meta, data = social_tools.load_media_file(settings, f"{growth.IMAGE_DIR}/{found.name}")
        except social_tools.MediaFileError as exc:
            raise HTTPException(404, str(exc)) from None
        return Response(data, media_type=meta["mime"], headers={"Cache-Control": "private, max-age=3600"})

    # ---------------------------------------------------------- reach: UTM, own feeds, inbox rules, DMs, uploads
    @app.post("/api/social/items/{item_id}/utm", dependencies=[api])
    async def item_utm(item_id: str, k: Kernel = Depends(kernel)):
        try:
            out = reach.tag_item(k, settings, item_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        if out is None:
            raise HTTPException(404, "no such content item")
        return out

    @app.get("/api/inbox/rules", dependencies=[api])
    async def inbox_rules(k: Kernel = Depends(kernel)):
        return {"rules": reach.get_rules(k)}

    @app.put("/api/inbox/rules", dependencies=[api])
    async def put_inbox_rules(body: RulesIn, k: Kernel = Depends(kernel)):
        return {"rules": reach.save_rules(k, body.rules)}

    @app.get("/api/feeds", dependencies=[api])
    async def own_feeds(k: Kernel = Depends(kernel)):
        return {"feeds": [{x: f[x] for x in ("url", "kind", "platforms", "template", "primed")} for f in reach.get_feeds(k)]}

    @app.put("/api/feeds", dependencies=[api])
    async def put_own_feeds(body: FeedsIn, k: Kernel = Depends(kernel)):
        try:
            feeds = reach.save_feeds(k, body.feeds)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None
        return {"feeds": [{x: f[x] for x in ("url", "kind", "platforms", "template", "primed")} for f in feeds]}

    @app.post("/api/feeds/check", dependencies=[api])
    async def check_own_feeds(k: Kernel = Depends(kernel)):
        return await reach.check_feeds(k, _social(k), settings, lambda url: reach.fetch_feed_items(k, url))

    @app.get("/api/inbox/dms", dependencies=[api])
    async def dms(k: Kernel = Depends(kernel)):
        try:
            return {"convos": await reach.bluesky_dms(_social(k))}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach Bluesky.") from None

    @app.get("/api/inbox/dms/{convo_id}", dependencies=[api])
    async def dm_messages(convo_id: str, k: Kernel = Depends(kernel)):
        try:
            return {"messages": await reach.bluesky_dm_messages(_social(k), convo_id)}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach Bluesky.") from None

    @app.post("/api/inbox/dms/{convo_id}", dependencies=[api])
    async def dm_send(convo_id: str, body: MessageIn, k: Kernel = Depends(kernel)):
        try:
            out = await reach.bluesky_dm_send(_social(k), convo_id, body.text)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach Bluesky.") from None
        k.obs.audit("user", "bluesky.dm", "ok", target=convo_id)
        return out

    @app.post("/api/media/upload", dependencies=[api])
    async def media_upload(request: Request, name: str = "card"):
        if int(request.headers.get("content-length") or 0) > social_tools.MAX_MEDIA_BYTES:
            raise HTTPException(413, "Image too large")
        data = await request.body()
        try:
            return reach.save_upload(settings, data, name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    # ---------------------------------------------------------- posting plan, growth, Bluesky extras
    @app.get("/api/plan", dependencies=[api])
    async def get_plan(k: Kernel = Depends(kernel)):
        return insights.get_plan(k)

    @app.put("/api/plan", dependencies=[api])
    async def put_plan(body: PlanIn, k: Kernel = Depends(kernel)):
        try:
            return insights.save_plan(k, body.model_dump())
        except (insights.InsightError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/social/items/{item_id}/options", dependencies=[api])
    async def item_options(item_id: str, body: ItemOptionsIn, k: Kernel = Depends(kernel)):
        try:
            out = insights.set_item_options(k, item_id, body.category, body.reply_control)
        except insights.InsightError as exc:
            raise HTTPException(400, str(exc)) from None
        if out is None:
            raise HTTPException(404, "no such content item")
        return out

    @app.get("/api/growth", dependencies=[api])
    async def growth_report(k: Kernel = Depends(kernel)):
        return insights.growth_report(k)

    @app.post("/api/growth/snapshot", dependencies=[api])
    async def growth_snapshot(k: Kernel = Depends(kernel)):
        return {"saved": await insights.snapshot(k, _social(k))}

    @app.get("/api/growth/fans", dependencies=[api])
    async def growth_fans(k: Kernel = Depends(kernel)):
        return await insights.top_fans(_social(k))

    @app.get("/api/growth/trends", dependencies=[api])
    async def growth_trends(k: Kernel = Depends(kernel)):
        return {"hashtags": insights.rising_hashtags(k), "outliers": insights.outliers(k)}

    @app.post("/api/bluesky/starter-pack", dependencies=[api])
    async def starter_pack(body: StarterPackIn, k: Kernel = Depends(kernel)):
        try:
            out = await insights.create_starter_pack(_social(k), body.name, body.description, body.handles)
        except (insights.InsightError, social_tools.AdapterError) as exc:
            raise HTTPException(400, str(exc)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach Bluesky.") from None
        k.obs.audit("user", "bluesky.starter_pack", "ok", target=out["uri"], detail={"added": out["added"]})
        return out

    # ---------------------------------------------------------- drafts from outside, import, evergreen, library
    def _social_for(k: Kernel):
        return k.tools.get("social.publish").social

    @app.post("/api/social/drafts", dependencies=[api])
    async def new_draft(body: DraftIn, k: Kernel = Depends(kernel)):
        try:
            item = hub.create_draft(k, _social_for(k), settings, body.model_dump(), created_by="user")
        except hub.HubError as exc:
            raise HTTPException(400, str(exc)) from None
        k.obs.audit("user", "social.draft", "ok", target=item["id"])
        return item

    @app.post("/api/social/import", dependencies=[api])
    async def import_posts(body: ImportIn, k: Kernel = Depends(kernel)):
        try:
            out = hub.import_csv(k, _social_for(k), settings, body.csv)
        except (hub.HubError, csv_error) as exc:
            raise HTTPException(400, str(exc)) from None
        k.obs.audit("user", "social.import", "ok", detail={"created": out["created"], "scheduled": out["scheduled"]})
        return out

    @app.post("/api/social/items/{item_id}/evergreen", dependencies=[api])
    async def evergreen(item_id: str, body: EvergreenIn, k: Kernel = Depends(kernel)):
        try:
            out = hub.set_evergreen(k, item_id, body.days)
        except hub.HubError as exc:
            raise HTTPException(400, str(exc)) from None
        if out is None:
            raise HTTPException(404, "no such content item")
        return out

    @app.get("/api/library", dependencies=[api])
    async def library(k: Kernel = Depends(kernel)):
        return {"snippets": hub.snippets(k)}

    @app.post("/api/library", dependencies=[api])
    async def library_add(body: SnippetIn, k: Kernel = Depends(kernel)):
        try:
            return hub.add_snippet(k, body.model_dump())
        except hub.HubError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.delete("/api/library/{snippet_id}", dependencies=[api])
    async def library_delete(snippet_id: str, k: Kernel = Depends(kernel)):
        if not hub.delete_snippet(k, snippet_id):
            raise HTTPException(404, "no such snippet")
        return {"ok": True}

    @app.get("/api/media", dependencies=[api])
    async def media_list():
        folder = settings.workspace_roots[0] / growth.IMAGE_DIR if settings.workspace_roots else None
        if folder is None or not folder.is_dir():
            return {"images": []}
        files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in social_tools.IMAGE_TYPES),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:200]
        return {"images": [{"name": p.name, "file": f"{growth.IMAGE_DIR}/{p.name}", "bytes": p.stat().st_size,
                            "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}
                           for p in files]}

    @app.get("/api/webhooks", dependencies=[api])
    async def webhooks_status(k: Kernel = Depends(kernel)):
        return k.webhooks.status()

    @app.post("/api/webhooks/test", dependencies=[api])
    async def webhooks_test(k: Kernel = Depends(kernel)):
        if not k.webhooks.urls:
            raise HTTPException(409, "Add STARK_WEBHOOK_URLS (https://…) to .env first.")
        ok = await k.webhooks.send({"event": "test", "at": datetime.now(timezone.utc).isoformat(),
                                    "data": {"message": "STARK OS webhook test"}})
        return {"delivered": ok, "of": len(k.webhooks.urls)}

    # ---------------------------------------------------------- automations
    def _auto(k: Kernel) -> automations.Engine:
        return k.automations

    @app.get("/api/automations", dependencies=[api])
    async def list_automations(k: Kernel = Depends(kernel)):
        return {"automations": _auto(k).list(), "events": automations.EVENTS, "ops": list(automations.OPS),
                "actions": list(automations.ACTIONS), "agents": list(automations.AGENTS),
                "platforms": list(social_tools.PLATFORMS)}

    @app.get("/api/automations/recipes", dependencies=[api])
    async def automation_recipes():
        return {"recipes": automations.RECIPES}

    @app.get("/api/automations/runs", dependencies=[api])
    async def automation_runs(automation_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                              k: Kernel = Depends(kernel)):
        return {"runs": _auto(k).history(automation_id, limit)}

    @app.post("/api/automations", dependencies=[api])
    async def create_automation(body: AutomationIn, k: Kernel = Depends(kernel)):
        try:
            return _auto(k).save(body.model_dump())
        except automations.AutomationError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/automations/from-recipe", dependencies=[api])
    async def automation_from_recipe(body: RecipeIn, k: Kernel = Depends(kernel)):
        try:
            return _auto(k).save({**automations.from_recipe(body.recipe), "enabled": False})
        except automations.AutomationError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.put("/api/automations/{automation_id}", dependencies=[api])
    async def update_automation(automation_id: str, body: AutomationIn, k: Kernel = Depends(kernel)):
        try:
            return _auto(k).save(body.model_dump(), automation_id)
        except automations.AutomationError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.delete("/api/automations/{automation_id}", dependencies=[api])
    async def delete_automation(automation_id: str, k: Kernel = Depends(kernel)):
        if not _auto(k).delete(automation_id):
            raise HTTPException(404, "no such automation")
        return {"deleted": automation_id}

    @app.post("/api/automations/{automation_id}/test", dependencies=[api])
    async def test_automation(automation_id: str, body: AutomationTestIn, k: Kernel = Depends(kernel)):
        a = _auto(k).get(automation_id)
        if a is None:
            raise HTTPException(404, "no such automation")
        payload = {"event": "test", "at": datetime.now(timezone.utc).isoformat(), "data": body.data}
        plan = _auto(k).plan(a, payload)
        if body.run and plan["would_run"]:
            return {**plan, "result": await _auto(k).run(a, payload)}
        return plan

    @app.post("/api/hooks/{automation_id}/{key}")
    async def inbound_hook(automation_id: str, key: str, request: Request, k: Kernel = Depends(kernel)):
        """Called by another app. No API token: the secret key in the address is the password."""
        raw = await request.body()
        if len(raw) > 64_000:
            raise HTTPException(413, "body too large (64 KB max)")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {"text": raw.decode("utf-8", "replace")}
        res = await _auto(k).inbound(automation_id, key, body)
        if res is None:
            raise HTTPException(404, "unknown hook")
        return {"ok": res["ok"], "steps": [{x: s.get(x) for x in ("type", "result", "error")} for s in res["steps"]],
                **({"note": res["note"]} if "note" in res else {})}

    # ---------------------------------------------------------- autopilot
    def _ap(k: Kernel) -> ap.Autopilot:
        return k.autopilot

    def _campaign_or_404(k: Kernel, campaign_id: str) -> dict:
        c = _ap(k).get(campaign_id)
        if c is None:
            raise HTTPException(404, "no such campaign")
        return c

    def _clean(body: BaseModel, creating: bool) -> dict:
        data = body.model_dump(exclude_none=True)
        if "sources" in data:
            data["sources"] = [dict(s) for s in data["sources"]]
        try:
            return ap.validate_campaign(data, creating=creating)
        except (ap.AutopilotError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/autopilot/campaigns", dependencies=[api])
    async def campaigns(k: Kernel = Depends(kernel)):
        return {"campaigns": [_ap(k).describe(c) for c in _ap(k).all()], "auto_unlock": ap.AUTO_UNLOCK,
                "queue_paused": social_tools.queue_paused(k), "emergency_stop": k.perms.emergency_stop,
                "can_write": bool(k.router.configured_providers()),
                "search_configured": bool(settings.tavily_api_key or settings.brave_api_key)}

    @app.post("/api/autopilot/campaigns", dependencies=[api])
    async def create_campaign(body: CampaignIn, k: Kernel = Depends(kernel)):
        data = _clean(body, True)
        if data.get("trust_level") == "auto":
            raise HTTPException(409, f"Full auto unlocks after {ap.AUTO_UNLOCK} clean posts. Start with co-pilot "
                                     "or veto.")
        with k.db.session() as s:
            if s.scalars(select(Campaign).where(Campaign.name == data["name"])).first() is not None:
                raise HTTPException(409, "A campaign with that name already exists.")
            row = Campaign(**data, next_run_at=datetime.now(timezone.utc))
            s.add(row)
            s.flush()
            out = to_dict(row)
        k.obs.audit("user", "autopilot.create", "ok", target=out["name"], detail={"trust": out["trust_level"]})
        return _ap(k).describe(out)

    @app.get("/api/autopilot/campaigns/{campaign_id}", dependencies=[api])
    async def campaign(campaign_id: str, k: Kernel = Depends(kernel)):
        c = _campaign_or_404(k, campaign_id)
        out = _ap(k).describe(c)
        out["keywords_table"] = _ap(k).keyword_table(c)
        out["research"] = _ap(k).research_list(campaign_id)
        out["items"] = social_tools.list_queue(k, "all", None, c["name"], 100)
        return out

    @app.patch("/api/autopilot/campaigns/{campaign_id}", dependencies=[api])
    async def patch_campaign(campaign_id: str, body: CampaignPatch, k: Kernel = Depends(kernel)):
        c = _campaign_or_404(k, campaign_id)
        data = _clean(body, False)
        if data.get("trust_level") == "auto" and c["trust_level"] != "auto" and _ap(k).streak(c) < ap.AUTO_UNLOCK:
            raise HTTPException(409, f"Full auto unlocks after {ap.AUTO_UNLOCK} clean Autopilot posts in a row "
                                     f"(this campaign has {_ap(k).streak(c)}).")
        if any(key in data for key in ("sources", "topics", "keywords", "post_times", "timezone", "platforms")):
            data["next_run_at"] = datetime.now(timezone.utc)  # use the new settings on the next tick
        rank = {"copilot": 0, "veto": 1, "auto": 2}
        lowered = "trust_level" in data and rank[data["trust_level"]] < rank.get(c["trust_level"], 0)
        out = _ap(k).save(campaign_id, **data)
        if lowered or data.get("enabled") is False:
            # less trust (or switched off) applies to posts already queued, not just to future ones
            _ap(k).revoke_auto(out, "You lowered this campaign's trust level or switched it off; this post now waits "
                                    "for you.")
        k.obs.audit("user", "autopilot.update", "ok", target=c["name"], detail={"fields": sorted(data)})
        return _ap(k).describe(out)

    @app.delete("/api/autopilot/campaigns/{campaign_id}", dependencies=[api])
    async def delete_campaign(campaign_id: str, k: Kernel = Depends(kernel)):
        c = _campaign_or_404(k, campaign_id)
        pending = social_tools.list_queue(k, "scheduled", None, c["name"], 500)
        for i in pending:
            if i.get("autopilot"):
                social_tools._update(k, i["id"], status="rejected", auto_publish=False, approved_fp=None,
                                     error="Campaign deleted.")
        with k.db.session() as s:
            from .core.db import ResearchItem

            for r in s.scalars(select(ResearchItem).where(ResearchItem.campaign_id == campaign_id)).all():
                s.delete(r)
            row = s.get(Campaign, campaign_id)
            if row is not None:
                s.delete(row)
        k.obs.audit("user", "autopilot.delete", "ok", target=c["name"])
        return {"deleted": True, "cancelled_posts": sum(1 for i in pending if i.get("autopilot"))}

    @app.post("/api/autopilot/campaigns/{campaign_id}/run", dependencies=[api])
    async def run_campaign(campaign_id: str, k: Kernel = Depends(kernel)):
        c = _campaign_or_404(k, campaign_id)
        if k.perms.emergency_stop:
            raise HTTPException(409, "Emergency stop is engaged.")
        if c["paused"]:
            raise HTTPException(409, "This campaign is paused. Resume it first.")
        if social_tools.queue_paused(k):
            raise HTTPException(409, "The content queue is paused (emergency stop or fire suppression). Resume it "
                                     "on the Content page first.")
        k.obs.audit("user", "autopilot.run_now", "ok", target=c["name"])
        return await _ap(k).run(campaign_id)

    @app.post("/api/autopilot/campaigns/{campaign_id}/pause", dependencies=[api])
    async def pause_campaign(campaign_id: str, paused: bool = True, k: Kernel = Depends(kernel)):
        c = _campaign_or_404(k, campaign_id)
        out = _ap(k).pause(c, "Paused by you.", actor="user") if paused else _ap(k).resume(c)
        return _ap(k).describe(out)

    @app.post("/api/autopilot/approve", dependencies=[api])
    async def approve_posts(body: ApproveIn, k: Kernel = Depends(kernel)):
        """Your click on the posts you saw is the approval (batch). Each must still match what you saw."""
        if k.perms.emergency_stop:
            raise HTTPException(409, "Emergency stop is engaged.")
        results = []
        for it in body.items:
            # The reason comes from a check that returns plain messages, so no exception text reaches the response.
            problem = _ap(k).approval_problem(it.id, it.fingerprint)
            if problem:
                results.append({"id": it.id, "ok": False, "error": problem})
                continue
            try:
                data = _ap(k).approve(it.id, it.fingerprint)
            except (ap.AutopilotError, KeyError):
                log.warning("autopilot approve failed after checks", exc_info=True)
                results.append({"id": it.id, "ok": False, "error": "This post could not be approved. Refresh and check it again."})
                continue
            results.append({"id": it.id, "ok": True, "scheduled_for": data["scheduled_for"]})
            k.obs.audit("user", "autopilot.approve", "ok", target=it.id)
        return {"results": results, "approved": sum(r["ok"] for r in results)}

    @app.post("/api/autopilot/items/{item_id}/veto", dependencies=[api])
    async def veto_post(item_id: str, k: Kernel = Depends(kernel)):
        try:
            _ap(k).veto(item_id)
        except ap.AutopilotError as exc:
            raise HTTPException(409, str(exc)) from None
        except KeyError:
            raise HTTPException(404, "no such content item") from None
        k.obs.audit("user", "autopilot.veto", "ok", target=item_id)
        return {"ok": True}

    @app.get("/api/autopilot/digest", dependencies=[api])
    async def digest(hours: int = Query(24, ge=1, le=168), k: Kernel = Depends(kernel)):
        return _ap(k).digest(hours)

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
        except NoModelAvailable as exc:  # our own, user-facing setup message
            data["model_in_use"] = {"provider": None, "model": None, "reason": exc.args[0] if exc.args else "no model"}
        except Exception:  # never send internal error details to the client
            log.exception("model routing failed")
            data["model_in_use"] = {"provider": None, "model": None, "reason": "model routing failed (see API log)"}
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
        try:
            args = await request.json() if await request.body() else {}
        except ValueError:
            raise HTTPException(400, "request body must be JSON") from None
        if not isinstance(args, dict):
            raise HTTPException(400, "request body must be a JSON object")
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
