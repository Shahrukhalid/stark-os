# Implementation status

_Last updated: 2026-10-16 · release 0.4.0 (connect accounts in the dashboard, approved auto-publishing, Start page)_

Legend: ✅ **Implemented & tested** · 🟡 **Implemented, not fully live-tested** · 🔑 **Requires credentials** · 🧪 **Simulated** · 📋 **Planned** · ⛔ **Unsupported by design**

## Test results (this release)

| Suite | Result |
|---|---|
| Backend `pytest` (runtime, social tools & adapters, tools, permissions, memory, free-model pool, API, security regressions) | **153 passed** on Python 3.12 with PostgreSQL 16 and real Chromium (148 passed, 5 skipped on 3.11 without those) |
| Frontend type-check + `vitest` | **18 passed** |
| End-to-end (Playwright: real dashboard + real API + a test-only scripted server speaking the OpenRouter protocol) | **15 passed** (incl. one-click publish, approved auto-publish at a time, account-connect checks, chat approval card, inbox triage, 360 px layout, safe markdown) |
| `next build` | passed · `npm audit`: **0 vulnerabilities** · `pip-audit`: **0 known vulnerabilities** |
| Secret scan (gitleaks) on the publishable tree | no leaks |
| Live OpenRouter check (2026-10-16, from the owner's machine) | key valid (free tier, 50 free requests/day); **10 of 15** chat-capable free models answered with a correct tool call; 4 were temporarily rate-limited upstream (429); 2 are restricted to agentic harnesses (403, excluded) |

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
