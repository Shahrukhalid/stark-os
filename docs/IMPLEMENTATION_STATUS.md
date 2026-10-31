# Implementation status

_Last updated: 2026-11-01 · release 1.1.0 (Automations: triggers, conditions and actions; recipe gallery; inbound and outbound webhooks for automation apps)_

Legend: ✅ **Implemented & tested** · 🟡 **Implemented, not fully live-tested** · 🔑 **Requires credentials** · 🧪 **Simulated** · 📋 **Planned** · ⛔ **Unsupported by design**

## Test results (this release)

| Suite | Result |
|---|---|
| Backend `pytest` (runtime, social tools & adapters, Autopilot, tools, permissions, memory, free-model pool, API, security regressions, automations) | **238 passed** (7 PostgreSQL-only skipped locally) on Python 3.13 and real Chromium |
| Frontend type-check + `vitest` | **26 passed** |
| End-to-end (Playwright: real dashboard + real API + a test-only scripted server speaking the OpenRouter protocol) | **22 passed** (incl. Automations, Library, Listening, Studio, Live, Calendar, Analytics and the command palette;  Autopilot campaign → research → writing → fact-check → batch approval, one-click publish, approved auto-publish at a time, account-connect checks, chat approval card, inbox triage, 360 px layout, safe markdown) |
| `next build` | passed · `npm audit`: **0 vulnerabilities** · `pip-audit`: **0 known vulnerabilities** |
| Secret scan (gitleaks) on the publishable tree | no leaks |
| Live OpenRouter check (2026-10-16, from the owner's machine) | key valid (free tier, 50 free requests/day); **10 of 15** chat-capable free models answered with a correct tool call; 4 were temporarily rate-limited upstream (429); 2 are restricted to agentic harnesses (403, excluded) |

## Automations (1.1.0, 2026-11-01)

✅ **Engine** (`stark/automations.py`, tables `automations` and `automation_runs`): triggers on bus events (mapped to the public webhook event names), daily/weekly schedules (local time, once per day) and inbound webhooks; conditions (`equals`, `contains`, `greater_than`, `matches`, …) that must all match; up to six actions (`ask_agent`, `create_draft`, `label_mention`, `add_utm`, `notify`, `webhook`) with `{{data.x}}` placeholders. No action can publish.
✅ **Safety**: what an automation created (`created_by = automation:<id>`) never triggers automations (no loops); 20 runs per automation per hour; webhook actions only to `https://`; each run and each step's result or error stored.
✅ **API**: `GET/POST /api/automations`, `PUT/DELETE /api/automations/{id}`, `GET /api/automations/recipes`, `POST /api/automations/from-recipe` (added switched off), `POST /api/automations/{id}/test` (dry run or real run), `GET /api/automations/runs`.
✅ **Inbound webhooks**: `POST /api/hooks/{id}/{key}` without the API token; a 32-character random key compared in constant time; 64 KB body limit; only switched-on webhook automations. Exposure guide (a tunnel that exposes only the hooks path) in `docs/AUTOMATIONS.md`.
✅ **Dashboard**: Automations page with builder, recipe gallery (11 recipes), test runs, run history and instructions for connecting other apps.
🟡 **Other automation apps**: the HTTP contract (JSON in, JSON out, signed outgoing requests) is tested; set-up inside each app is described generically.

## Channels, reach and inbox (1.0.0, 2026-11-01)

🔑 **New publishing channels** (`stark/channels.py`): Threads Graph API (text posts and threads; engagement via insights), Telegram channel (bot admin; photo with caption), Discord channel webhook (mentions disabled), Slack incoming webhook. Configured in `.env`; publishing goes through the same approval and `publish_item` path.
✅ **UTM tagging** (`reach.add_utm`): own links only (social networks and already-tagged links are skipped); per draft (`POST /api/social/items/{id}/utm`, an edit that re-runs the check and cancels earlier approvals) or for every new draft with `STARK_UTM=true`.
✅ **Own channels → drafts**: `GET/PUT /api/feeds` (YouTube channel id/URL, podcast or blog RSS); hourly check through Autopilot's SSRF-safe reader; the first check only remembers existing items.
✅ **Inbox rules**: `GET/PUT /api/inbox/rules`; labels added to Listening results (`mentions.labels`); never automatic replies.
🔑 **Bluesky DMs**: list, read and send (owner-typed only) via `chat.bsky.convo.*` with the chat proxy header; needs an app password with DM access.
✅ **Saved replies** (Library kind `reply`), **translation** and **reply in the poster's language** (agent instructions), **quote cards and carousels** drawn in the browser and stored with `POST /api/media/upload`.

## Smarter posting and growth (0.9.0, 2026-11-01)

✅ **Compose**: manual composer with per-platform previews, character counter, Library snippets, category, Bluesky reply control, *Save draft* / *Add to queue* (next free posting-plan slot, no auto-publish).
✅ **Engagement score** (`lib/score.ts`): 0-100 against the owner's own average from measured posts with the same traits; general guidance (clearly labelled) below 5 measured posts.
✅ **Posting plan**: `GET/PUT /api/plan` (categories with target shares, weekly slots); `category` on content items; planned vs target mix in Calendar.
✅ **Bluesky reply controls**: `reply_control` → `app.bsky.feed.threadgate` record after the post is created (a failed threadgate never hides a live post).
✅ **Growth**: daily follower snapshots (`account_stats`, every 6 h), `GET /api/growth` (series, summary, posting streak, consistency), `GET /api/growth/fans` (top interactors from notifications), `GET /api/growth/trends` (rising hashtags in Listening results; competitor posts ≥ 3× their average).
✅ **Bluesky starter packs**: `POST /api/bluesky/starter-pack` creates a reference list, list items and a starter pack (up to 150 handles).

## Workflow (0.8.0, 2026-11-01)

✅ **Library**: templates, hashtag groups (normalised to unique #tags) and signatures; `library.list` for J.A.R.V.I.S., E.D.I.T.H., F.R.I.D.A.Y. and U, whose prompts say to use them. Media library of generated images.
✅ **Bulk import**: `POST /api/social/import` (CSV: platform, text, scheduled_for, campaign, thread), max 500 rows; policy check per row; times become scheduled without auto-publish.
✅ **Evergreen**: `POST /api/social/items/{id}/evergreen` (7-365 days); an hourly job turns due published posts into fresh drafts and moves the setting to the copy.
✅ **Report**: Analytics → Report downloads a self-contained HTML report.
✅ **MCP server** (`python -m stark.mcp_server`, stdio): status, queue, create/schedule drafts (no auto-publish), ask the team, task status, analytics, mentions. No publish tool by design. `POST /api/social/drafts` backs it.
✅ **Webhooks**: `STARK_WEBHOOK_URLS` get post.drafted/scheduled/published/failed, mention.found, approval.needed, autopilot.alert and estop, once per post and state, HMAC-signed with `STARK_WEBHOOK_SECRET`.
⛔ Auto-like, auto-follow-back and auto-comment (offered by some schedulers) are left out on purpose: they break Bluesky's and Mastodon's anti-spam rules.

## Growth (0.7.0, 2026-10-31)

✅ **Listening**: watches (keyword, hashtag, account) checked every 15 minutes on Bluesky (search via the connected account or the public AppView; author feeds) and Mastodon (search with a token, hashtag timelines, account statuses). Results are de-duplicated, triaged with the inbox rules and shown in a Listening page; competitor accounts get a best-posts summary.
✅ **Phone notifications**: Telegram (long polling, no public URL) with Approve / Reject and Publish / Discard buttons. Only the configured chat may press them; a Publish button carries the fingerprint of the text it showed and refuses if the post changed. Discord webhook messages and a daily digest.
✅ **Free AI images**: `media.generate_image` (U) and the Studio save Pollinations images in `media/generated/`, checked like any attachment. `STARK_IMAGE_GENERATOR=off` turns it off.
✅ **Studio**: repurpose a link or text through J.A.R.V.I.S.'s team, A/B hook tests (campaign `ab:…`, compared under Analytics → Experiments), *Learn my voice* from the best real posts.
✅ **Auto-schedule drafts** in Calendar (one per free day at the best hour; auto-publish stays off) and an installable web-app manifest.
🔑 Telegram / Discord need your own bot token, chat id or webhook in `.env`.

## Dashboard upgrade (0.6.0, 2026-10-31)

✅ **Live view**: animated agent network (signals fly along every real agent message), live counters and a streaming feed of thoughts, tool calls, results and approvals, filterable by agent and pausable.
✅ **Calendar**: month and week views of scheduled and published posts; drag a scheduled post or a draft onto a day to (re)schedule it through the same checked API as the Content page. An auto-publish approval is kept only when the post already had one for that exact text.
✅ **Analytics**: `GET /api/social/analytics` (cached 5 minutes) returns queue counts and real engagement for published Bluesky/Mastodon posts; the page shows totals, a 30-day chart, a best-time-to-post heatmap in the viewer's time zone, top posts and CSV export. Simulated posts never get numbers.
✅ **Command palette** (Ctrl/⌘ K) and the **FX** switch (Maximum: particle network, scanlines and boot-up sequences; Calm: animations only; Off). Reduce-motion is respected.
✅ Light theme contrast fixes for accent colours and the active navigation item.

## Autopilot (0.5.0, 2026-10-17)

✅ Campaigns, research (RSS/Atom, Hacker News, Reddit; 🔑 web search with Tavily/Brave), scoring, SEO keywords and hashtags, writing (E.D.I.T.H.) and fact-checking (JOCASTA) in two free-model requests per story, quality gate, posting times / daily caps / spacing, trust levels with the 10-post unlock and veto downgrade, batch approval, cancel window, crisis / failure / engagement auto-pause, engagement learning, digest API, dashboard page. 30 tests in `services/api/tests/test_autopilot.py` (plus one on PostgreSQL) and one end-to-end test. An independent review before release found 3 high-severity issues: a pause, deletion or trust change during a run, or after posts were queued, did not stop those posts. It also found 7 medium/low ones: a malformed source could stop a run, re-creating a campaign or simulated posts counted toward the Full auto unlock, the fact-check accepted any truthy value, bare web addresses were not flagged, and long runs could delay due posts. All are fixed with regression tests. Guide: [AUTOPILOT.md](AUTOPILOT.md).

Not included: Google Trends (no public API), images and video for Instagram/TikTok/YouTube, email or phone notifications (the digest is in the dashboard and the API).

## Security audit (2026-10-16)

Three independent reviews (backend security, frontend/infra/dependencies, runtime correctness) found 30 issues; all confirmed issues were fixed and each has a regression test in `services/api/tests/test_security_regressions.py`.

| Severity | Finding | Fix |
|---|---|---|
| High | `git status` could execute commands from a planted `.git/config` | git removed from default allowlist (terminal tool removed entirely in 0.3.0); git (if re-added) runs with config hooks disabled; agents can never write/move inside `.git` |
| High | Approval after delegation in the same turn crashed the task and left an orphan approval | state machine fixed; approvals always cleaned up when a task ends |
| High | Task cancelled before its first step stayed `queued` forever | done-callback records cancellation |
| Med-High | `docs.ingest` read `.env` without approval and shared it with every agent | secrets refused; ingestion requires approval |
| Medium | Standing grants escapable with `..`, whole-folder moves and `inbox2` prefix | grants matched on resolved paths, every touched path must be inside the scope |
| Medium | Moving `.env` to a new name bypassed the sensitive-read approval | moving sensitive files always needs approval |
| Medium | SSRF: DNS rebinding, CGNAT (100.64/10), WebSockets from the headless browser | IP pinning with TLS verification, only global addresses, WebSockets refused |
| Medium | Injected text in shared memory was replayed into every system prompt | memories fenced as untrusted data; shared/procedural writes need approval; project memory limited to own task tree |
| Medium | Read-only web fetch could exfiltrate file contents in the URL | exfiltration guard (approval after file reads unless the URL came from a search) |
| Medium | Sync file I/O blocked the event loop (E-STOP unresponsive) | moved to worker threads, bounded reads |
| Medium | 200-with-error bodies and odd response shapes from OpenRouter counted as success or crashed | parsed into failover-able provider errors |
| Medium | Tools still ran on the final step; failed delegations could not be retried; SSE stream silently died for slow clients | fixed |
| Medium | No Content-Security-Policy; long-lived token in localStorage | strict CSP; token in sessionStorage unless "remember" is ticked |
| Low-Med | Home Assistant path injection via `entity_id` | strict entity-id pattern (tool later removed in 0.3.0) |
| Low | Symlinked secrets in search, missing OpenRouter-key redaction/detection, query token accepted on all routes, dev server on all interfaces, `.dockerignore`/`.gitignore` gaps, `.env` briefly world-readable, unpinned CI actions, no Python lockfile, vulnerable dev/build deps (vitest/tinypool, postcss) | all fixed |

Residual risks (documented, not fully solvable here): the headless browser resolves DNS itself, so rebinding within one page load is mitigated only by per-request re-checks; agents that legitimately read files and then fetch search-result URLs still send page requests to those sites.

## Audit round 3 (2026-10-16): security, frontend, accessibility, infrastructure

Three independent reviews (backend security, dashboard/CSS/accessibility, infrastructure/dependencies). All confirmed findings fixed; tests in `test_security_regressions.py`, `test_tools.py`, `tests/markdown.test.ts` and `e2e/dashboard.spec.ts`.

| Severity | Finding | Fix |
|---|---|---|
| High | Exfiltration guard was per task: a follow-up chat turn (or memories in the prompt) could send earlier file contents out in a URL | A URL is fetched without approval only if a web search in this task returned it or you typed it in this request |
| Medium | Agents' project notes from one task tree reached unrelated later prompts, without review or expiry | Project memory is only visible inside its own task tree and expires after 30 days |
| Medium | `web.fetch` buffered whole responses before truncating (memory exhaustion) | Bodies are streamed and cut at 3 MB; only gzip/deflate accepted |
| Medium | Headless browser followed redirects to addresses that were never checked | Navigations are fetched hop by hop and every redirect target is SSRF-checked (tested with real Chromium) |
| Medium | Dashboard scrolled sideways on phones with long URLs/ids; custom CSS silently overrode Tailwind utilities | Grid children can shrink, long text wraps; component CSS moved into `@layer components` |
| Medium | Wake-word voice commands used stale state; login fields, icon buttons and filters had no accessible names; hold-to-talk was mouse-only | Fixed; keyboard push-to-talk (Space/Enter), labels, `aria-pressed/expanded/current`, focus ring, error toasts as alerts |
| Medium | Docker: sandbox not writable on Linux; compose crash-looped without a token; web didn't wait for the API | UID build arg, required-token check with a clear message, healthchecks |
| Low | Non-ASCII token returned 500; negative/unbounded list limits; screenshots wrote files without approval; approval cards truncated long writes/moves; more credential file names; paid models reachable via ping; approvals could outlive task timeouts; out-of-order fetches; SSE never reconnected after an error status; low-contrast idle badge; access logs could contain the event-stream token; CI not active; unused "physical" risk class | All fixed |
| Polish | Agent replies showed raw markdown | Safe renderer that builds React elements only and keeps only http(s) links |

## Definition of Done (Part 18)

| # | Criterion | Status |
|---|---|---|
| 1 | Application starts | ✅ |
| 2 | Dashboard connects to backend | ✅ token auth + live SSE |
| 3 | Chat with J.A.R.V.I.S. | ✅ |
| 4 | J.A.R.V.I.S. uses a real configured model | ✅ free OpenRouter models; tool calling confirmed live on 10 free models |
| 5–7 | Seven distinct agents, direct selection | ✅ |
| 8–9 | Real delegation, visible collaboration | ✅ |
| 10 | ≥3 useful tools | ✅ 28 tools (12 social) |
| 11 | Sensitive actions require approval | ✅ |
| 12–14 | Results saved, memory retrieval, visible errors | ✅ |
| 15–16 | Tests pass, setup instructions | ✅ |
| 17 | Optional services degrade gracefully | ✅ no key / no search key / no social accounts (simulation) / no Playwright / OpenRouter offline |
| 18 | Simulation clearly distinguished | ✅ |

## Capabilities

| Area | Status |
|---|---|
| 7 social agents with VisionQuest-derived roles (prompt, personality, own brain, tools, permissions, private memory, workflow, voice, limits, history, metrics) | ✅ |
| Own brain per agent (first-choice free models, then tier list with failover) | ✅ (ordering tested; models verified live on 2026-10-16) |
| Content queue: drafts, threads, replies, video posts, edit, discard, schedule, calendar view | ✅ |
| Deterministic policy / brand-safety / accessibility check | ✅ |
| Publishing to **Bluesky** (AT Protocol, threads, replies, link/hashtag facets) | 🔑 🟡 implemented and tested against recorded API shapes; needs your app password for a live post |
| Publishing to **Mastodon** (threads, replies, idempotency keys) | 🔑 🟡 implemented and tested against recorded API shapes; needs your token for a live post |
| Publishing to X, Threads, LinkedIn, Instagram, Facebook, TikTok, YouTube | 🧪 simulated (paid/reviewed APIs); real adapters 📋 |
| Inbox (Bluesky/Mastodon notifications) with triage | 🔑 · labelled sample inbox 🧪 ✅ |
| Analytics (likes, reposts, replies) for real posts | 🔑 · simulated posts report "no engagement data" ✅ |
| Approval for every publish, D.U.M.-E. only, no grants; J.A.R.V.I.S. block; re-check at publish time | ✅ |
| E-STOP pauses the queue (fire suppression); resume needs approval | ✅ |
| Content-claim check (no "it's posted" without a published item) | ✅ |
| Automatic posting at the scheduled time, for posts you approved (exact-text approval; edits cancel it; missed >6 h asks again; E-STOP/pause stop it) | ✅ |
| Connect Bluesky / Mastodon from the dashboard (verified on save; stored only locally, mode 600; app-password check) | ✅ (tested with recorded API shapes) |
| Start page (how it works, setup checklist, quick actions); one-click Publish / Schedule / Copy / Discard in Content | ✅ |
| Image / video generation and upload | ⛔ STARK OS writes briefs only |
| Delegation limits, parallel team review + Ultron challenge, retries, cancellation, E-STOP | ✅ |
| Free-model pool: catalogue, tier preferences, failover with cooldowns, quota display, ping | ✅ |
| Token streaming of replies | 📋 |
| Memory layers, consent, expiry, export, disable, document ingestion (brand guidelines) | ✅ |
| Vector retrieval | 📋 (lexical today) |
| Brand-folder files, security audit, web fetch/PDF, headless browser, memory, delegation tools | ✅ |
| Web search (Tavily / Brave) | 🔑 |
| Voice (browser speech: push-to-talk, wake phrases, per-agent voices; U is muted) | 🟡 logic tested; microphone flow needs a real browser |
| Docker Compose | 🟡 written and hardened; images not built here (Docker Hub blocked in the build sandbox) |
| CI workflow (GitHub Actions: pytest + PostgreSQL + Chromium, type-check, unit, E2E, gitleaks) | ✅ `.github/workflows/ci.yml` |

## Removed in 0.3.0
Smart-home / robotics tools (Home Assistant, simulated lab) and the allowlisted terminal: the product is a social media team, not a personal-computer assistant. System metrics remain for the Diagnostics page only (no agent has them).

## Unsupported by design ⛔
Autonomous weapons, targeting, covert surveillance/tracking or profiling of people, fake accounts, bought or automated engagement, impersonation, deepfakes, offensive intrusion, credential theft, self-replication, agents changing their own permissions, actor voice cloning, paid model calls (unless explicitly enabled).
