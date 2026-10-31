"""Relational state (SQLite by default, PostgreSQL via DATABASE_URL)."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("conv"))
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Turn(Base):
    """Working memory: chat turns of a conversation."""

    __tablename__ = "turns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    agent_id: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tsk"))
    root_id: Mapped[str] = mapped_column(String(40), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="chat")  # chat|delegation|review|tool
    requested_by: Mapped[str] = mapped_column(String(40), default="user")
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    agent_chain: Mapped[list[Any]] = mapped_column(JSON, default=list)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMessageRow(Base):
    __tablename__ = "agent_messages"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(String(40), index=True)
    root_id: Mapped[str] = mapped_column(String(40), index=True)
    sender: Mapped[str] = mapped_column(String(32))
    recipient: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    permission_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("apr"))
    task_id: Mapped[str] = mapped_column(String(40), index=True)
    agent_id: Mapped[str] = mapped_column(String(32))
    tool_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    expected_effects: Mapped[str] = mapped_column(Text)
    risks: Mapped[str] = mapped_column(Text)
    permissions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Grant(Base):
    """A user-created standing authorization used in EXECUTE_APPROVED mode."""

    __tablename__ = "grants"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("grt"))
    agent_id: Mapped[str] = mapped_column(String(32))
    tool_id: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(Text, default="")  # e.g. path prefix
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem"))
    namespace: Mapped[str] = mapped_column(String(80), index=True)
    layer: Mapped[str] = mapped_column(String(24), index=True)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(32))
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class UsageRecord(Base):
    __tablename__ = "usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    task_id: Mapped[str] = mapped_column(String(40), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    cost_known: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class ContentItem(Base):
    """A social post / reply / thread in the content queue (drafts never leave the system)."""

    __tablename__ = "content_items"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cnt"))
    platform: Mapped[str] = mapped_column(String(24), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="post")  # post | reply | thread | video
    text: Mapped[str] = mapped_column(Text)
    thread: Mapped[list[Any]] = mapped_column(JSON, default=list)  # follow-up parts of a thread
    media: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{description, alt_text}] briefs, no files
    reply_to: Mapped[str | None] = mapped_column(String(300), nullable=True)
    campaign: Mapped[str] = mapped_column(String(120), default="")
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # draft | scheduled | publishing | published | failed | rejected
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    check: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # last social.check result
    review: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # last J.A.R.V.I.S. review verdict
    created_by: Mapped[str] = mapped_column(String(32))
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Auto-publish: the owner approved this exact content (fingerprint) to go out at scheduled_for, unattended.
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_fp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Autopilot metadata (campaign, source story, quality gate, fact-check, keywords, engagement). Empty for
    # items written by hand or by an agent.
    autopilot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)
    # Evergreen: after this many days a published post comes back as a fresh draft (None = off).
    evergreen_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    recycled_from: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    category: Mapped[str] = mapped_column(String(40), default="")  # content category from the posting plan
    # Bluesky: who may reply (everyone | followers | following | mentioned | nobody); None = everyone
    reply_control: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)


class AccountStat(Base):
    """One snapshot a day of a connected account's follower, following and post counts."""

    __tablename__ = "account_stats"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ast"))
    platform: Mapped[str] = mapped_column(String(24), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    followers: Mapped[int] = mapped_column(Integer, default=0)
    following: Mapped[int] = mapped_column(Integer, default=0)
    posts: Mapped[int] = mapped_column(Integer, default=0)


class Snippet(Base):
    """Library: reusable templates, hashtag groups and signatures the owner and the agents can use."""

    __tablename__ = "snippets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("snp"))
    kind: Mapped[str] = mapped_column(String(16))  # template | hashtags | signature
    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    platforms: Mapped[list[Any]] = mapped_column(JSON, default=list)  # empty = all
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Watch(Base):
    """Social listening: a keyword, hashtag or account to follow on Bluesky and/or Mastodon."""

    __tablename__ = "watches"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("wch"))
    kind: Mapped[str] = mapped_column(String(16))  # keyword | hashtag | account (a competitor or partner)
    query: Mapped[str] = mapped_column(String(200))
    platforms: Mapped[list[Any]] = mapped_column(JSON, default=list)
    label: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_min: Mapped[int] = mapped_column(Integer, default=15)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Mention(Base):
    """A public post found by a watch. Text is kept as found; nothing is ever posted from here."""

    __tablename__ = "mentions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("men"))
    watch_id: Mapped[str] = mapped_column(String(40), index=True)
    platform: Mapped[str] = mapped_column(String(24))
    external_id: Mapped[str] = mapped_column(String(300), index=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(24), default="general")  # from the inbox triage rules
    labels: Mapped[list[Any]] = mapped_column(JSON, default=list)  # from the owner's inbox rules
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)  # new | done | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Campaign(Base):
    """An Autopilot campaign: what to research and post about, where, when, and how much to trust it."""

    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cmp"))
    name: Mapped[str] = mapped_column(String(120), unique=True)  # = ContentItem.campaign; fixed after creation
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[list[Any]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    avoid_terms: Mapped[list[Any]] = mapped_column(JSON, default=list)  # never post these (brand safety)
    audience: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(Text, default="")
    platforms: Mapped[list[Any]] = mapped_column(JSON, default=list)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{type: rss|hn|reddit|search, value}]
    post_times: Mapped[list[Any]] = mapped_column(JSON, default=list)  # ["09:00", "17:30"] in `timezone`
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    daily_cap: Mapped[int] = mapped_column(Integer, default=3)  # posts per platform per day
    min_gap_minutes: Mapped[int] = mapped_column(Integer, default=120)
    trust_level: Mapped[str] = mapped_column(String(16), default="copilot")  # copilot | veto | auto
    veto_minutes: Mapped[int] = mapped_column(Integer, default=120)
    link_policy: Mapped[str] = mapped_column(String(16), default="always")  # always | never
    fact_check: Mapped[bool] = mapped_column(Boolean, default=True)
    research_every_h: Mapped[float] = mapped_column(Float, default=6.0)
    max_new_per_run: Mapped[int] = mapped_column(Integer, default=2)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # keywords, history, veto/crisis marks
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchItem(Base):
    """A story Autopilot found for a campaign (RSS, Hacker News, Reddit, web search)."""

    __tablename__ = "research_items"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("res"))
    campaign_id: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | used | skipped
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    used_for: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args, future=True)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        self._factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Tiny forward-only migration: add columns introduced by newer releases to existing tables."""
        from sqlalchemy import inspect, text

        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if not insp.has_table(table.name):
                    continue
                have = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in have:
                        continue
                    q = self.engine.dialect.identifier_preparer.quote
                    ddl = f"ALTER TABLE {q(table.name)} ADD COLUMN {q(col.name)} {col.type.compile(self.engine.dialect)}"
                    default = getattr(col.default, "arg", None)
                    if isinstance(default, bool):
                        ddl += f" DEFAULT {'true' if default else 'false'}" if self.engine.dialect.name == "postgresql" \
                            else f" DEFAULT {int(default)}"
                    elif isinstance(default, (int, float)):
                        ddl += f" DEFAULT {default}"
                    elif isinstance(default, str):
                        ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                    conn.execute(text(ddl))

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # --- tiny key/value settings store ---
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.session() as s:
            row = s.get(Setting, key)
            return json.loads(row.value) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.session() as s:
            row = s.get(Setting, key)
            if row:
                row.value = json.dumps(value)
            else:
                s.add(Setting(key=key, value=json.dumps(value)))


def to_dict(row: Base) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, datetime):
            if val.tzinfo is None:
                val = val.replace(tzinfo=timezone.utc)
            val = val.isoformat()
        out[col.name] = val
    return out
