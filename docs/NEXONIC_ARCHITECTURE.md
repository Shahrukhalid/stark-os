# Architecture and extension boundaries

## Current implementation

`services/api/stark/main.py` constructs FastAPI and the shared Kernel, registry, tools, permission engine, database and background jobs. Token authentication protects owner routes. SSE uses an in-process EventBus with a bounded subscriber queue and 200-event history. Backpressure drops an old event rather than blocking the kernel; this is not a durable event log.

`core/runtime.py` owns task states, model/tool rounds, approvals, budgets, timeout, cancellation, delegation and emergency stop. `core/workflows.py` supplies specialist procedures and final-answer checks. `core/messaging.py` supplies inter-agent messages. `core/agent_registry.py` validates TOML, prompts, known tools and delegation targets. Extend this one runtime for Vision/Wanda.

`core/permissions.py` combines owner mode and per-agent ceiling. Tool allowlists, sensitive reads, external/destructive actions and scoped grants are enforced centrally. New computer-control tools must enter this same execution path. J.A.R.V.I.S. receives no unrestricted desktop authority.

SQLAlchemy models in `core/db.py` store tasks, turns, memories, grants, approvals, audit/usage, content, brands and automation state. SQLite is the local default; PostgreSQL has integration tests. Startup uses additive column inspection rather than a separately versioned migration framework. M1 changes no schema.

`core/model_router.py` selects ModelProvider routes. OpenRouter is the sole default runtime provider, with free-only model filtering and candidate cooldown/failover. OpenAI-compatible transport is reused. M1 honors explicit agent provider selection and keeps OpenRouter model pins out of other providers. M2 must introduce a distinct local adapter and explicit cloud fallback policy rather than interpreting an arbitrary custom base URL as a complete local mode.

`core/memory.py` applies namespace rules, project-root filtering and brand visibility to lexical overlap/recency retrieval. Existing empty-brand memories can be shared. Personal memory needs an explicit separate scope before Vision/Wanda are introduced. No vector engine is necessary for M1.

`apps/web` is Next.js/React with TypeScript, shared store/API/SSE state and dedicated social, agents, tasks, approvals, settings and memory views. Voice uses browser recognition and system synthesis with a speaking guard. The media studio separately uses whisper.cpp and FFmpeg; that is not the requested assistant streaming voice service.

`desktop/stark_desktop.py` supervises a loopback API child, random local token, single-instance handshake, static dashboard and pywebview window. PyInstaller packages Windows and two Mac architectures. Current paths, bundle ID, installer identity and STARK_* names remain stable. Secure credential files share one native-vault key per data directory.

`tools/social.py`, `channels.py`, `oauth.py`, `autopilot.py`, `automations.py`, `hub.py`, `brands.py`, `growth.py`, `reach.py`, `video.py` and `insights.py` provide the social product. `mcp_server.py` exposes selected API functionality via stdio without a publish tool. Wrap these into Nexonic Social later, preserving routes and approval invariants.

## Planned layering

Existing kernel -> capability-checked tools -> native desktop adapters, integrations and modules. Vision/Wanda are registry entries, not a new orchestrator. Provider and voice services produce typed results and cancellable jobs. UI observes actual task events. Persistent memory keeps provenance and explicit personal/project/brand boundaries. Remote clients use authenticated narrow interfaces; no internet-exposed unrestricted control API.

Performance baseline is still incomplete. Record startup/RSS/CPU on Windows and both Mac architectures, long-task cancellation latency, SSE saturation and large-memory retrieval before adding 3D rendering or continuous audio.
