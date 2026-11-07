# Implementation inventory

Evidence levels below describe source plus relevant automated fixtures. No new live external-platform testing was performed. “Implemented” does not mean an account is configured, an app approved, or every feature manually accepted.

## Preserved existing product

- Seven agents, specialization, delegation, task state, timeout/cancel/E-STOP and approvals. Sources `core/runtime.py`, `agent_registry.py`, `permissions.py`; tests `test_runtime.py`, `test_security_regressions.py`, `test_policy_memory.py`.
- OpenRouter free-model catalogue, candidate ordering, rate-limit cooldowns, usage/budgets, optional paid opt-in. `providers/`, `core/model_router.py`; `test_providers.py`. Live model availability was not rechecked.
- Drafts, queue, exact-text approval, schedule, pause, brand review and history. `tools/social.py`; `test_social.py`, `test_autopilot.py`, `test_social_ui.py`. Disconnected adapters can produce explicitly simulated results, not real publishes.
- Bluesky/Mastodon publishing and inbox; Threads, Facebook Pages, LinkedIn, Telegram, Discord, Slack adapters; Instagram/Pinterest/TikTok/YouTube media and OAuth paths. `tools/social.py`, `channels.py`, `oauth.py`; `test_social.py`, `test_meta_linkedin.py`, `test_media_platforms.py`, `test_official_login.py`. Transport fixtures do not validate platform permissions or production login. Needs credentials and sometimes platform app review. X remains draft-only.
- Brands, library, scheduling plans, analytics, growth, listening and automations. Dedicated backend modules and UI views; `test_brands_and_insight.py`, `test_growth.py`, `test_hub.py`, `test_automations.py`, `test_reach.py`. Real metrics require connected platforms. Simulation must stay labeled.
- Image generation, browser card rendering, FFmpeg video studio, caption/transcription jobs and model download. `growth.py`, `video.py`, `shorts.py`, `StudioView.tsx`, `VideoStudio.tsx`; `test_v16.py`, `test_v17.py`, `test_v18.py`. Model/media tools are optional and require native dependencies or external services. Not a full assistant voice pipeline.
- Layered lexical memory, consent, namespace/project/brand checks, edit/export/expiry. `core/memory.py`; `test_policy_memory.py`, `test_health_and_isolation.py`. Semantic embeddings, contradiction handling and personal/brand policy expansion remain future work.
- REST + SSE, stdio MCP, pywebview desktop and updater. `main.py`, `mcp_server.py`, desktop launcher/spec; `test_api.py`, `test_hub.py`, `test_desktop.py`, `test_desktop_instance.py`. Existing installer CI succeeded at baseline; this PR needs its own package acceptance.
- Browser voice input, wake handling and system voice selection with speaking suppression. `apps/web/lib/voice.ts`, `tests/logic.test.ts`. Device microphone, Urdu quality, latency and offline STT are not established.

## M1 additions

Authenticated encrypted desktop credential stores and verified migration backup, explicit downgrade export, provider pin enforcement, redacted connection errors and early settings-name validation. New `test_credential_store.py` exercises real AES-GCM with a fake vault, with a separate opt-in native OS test. No changes to social publishing permissions, data schemas, identifiers or the seven configurations.

## Planned, not implemented

Vision/Wanda, Ollama discovery/download/control, dedicated streaming voice, native desktop actions, personal semantic memory, new assistant UI, modules, Teach Nexonic, Mission Control, ecosystem integrations and secure remote pairing. See [roadmap](NEXONIC_MASTER_PLAN.md). No mock UI is added to imply these exist.
