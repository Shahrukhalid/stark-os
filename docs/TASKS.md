# Roadmap & task list

## Done (0.1.0)
- [x] Phase 0 — environment discovery
- [x] Phase 1 — architecture, decisions, schema, API contracts
- [x] Phase 2 — API, DB, auth, registry, providers, tools, state machine, logging
- [x] Phase 3 — J.A.R.V.I.S. chat, tool calling, approvals, history, memory
- [x] Phase 4 — seven agents with distinct configs and delegation
- [x] Phase 5 — parallel team review, shared context, aggregation, failure recovery
- [x] Phase 6 — browser voice (push-to-talk, wake phrases, per-agent voices)
- [x] Phase 7 — browser automation, diagnostics, file management, research tools, smart-home (HA + simulation)
- [x] Phase 8 — security/permission/integration/E2E tests, cost controls, docs
- [x] Phase 9 — dashboard polish (first pass)

## Done (0.2.0)
- [x] Free OpenRouter models only: pool, tier preferences, failover, quota, Models panel with ping
- [x] Deep security & correctness audit; all confirmed findings fixed with regression tests

## Done (0.3.0)
- [x] Agents redesigned as a social media team, roles from VisionQuest (2026); own brain per agent
- [x] Social tools: queue, policy check, schedule, publish (Bluesky, Mastodon real; others simulated), inbox triage, analytics, fire suppression
- [x] Content view in the dashboard; E2E for draft → approval → publish
- [x] Removed smart-home and terminal tools

## Next (priority order)
1. **Live posting test** — connect a Bluesky test account and a Mastodon test account; tune prompts from real transcripts on free models.
2. **Media upload** — attach a real image/video file from the brand folder to Bluesky/Mastodon posts (alt text already enforced).
3. **Scheduled mode** — publish due items unattended only inside a user-defined window, with a per-campaign standing approval and a daily cap.
4. **More real adapters** — Threads, LinkedIn and others once the owner has API access.
5. **Token streaming** — stream deltas through SSE into the chat bubble.
6. **Request budgeting** — warn before a team review when fewer free requests remain than it typically needs.
7. **Vector memory** — free embedding model + pgvector, lexical fallback.
8. **MCP** — expose STARK tools as an MCP server.
9. **Packaging** — verified Docker images.

## Known limitations
- Tasks don't survive an API restart (marked failed on boot).
- SSE token travels in the query string.
- The headless browser resolves DNS itself; rebinding during a single page load is only mitigated by per-request re-checks.
- Free models are rate-limited (50 requests/day on a free key) and change often.
- Bluesky character limits are counted in code points (Bluesky counts graphemes); emoji-heavy posts may be slightly under the real limit.
- Bluesky/Mastodon publishing is verified against recorded API shapes, not yet against a live account from this build environment.
