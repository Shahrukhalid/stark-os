# STARK OS — Project Genesis

[![CI](https://github.com/Shahrukhalid/stark-os/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahrukhalid/stark-os/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-22d3ee.svg)](LICENSE) ![Free models](https://img.shields.io/badge/models-free%20OpenRouter-34d399)

A real, runnable **multi-agent social media team**: seven AI agents, each with its own brain, role and limits, who plan campaigns, write posts, run your community inbox, research trends, stress-test content for backlash and publish — **only after you approve each post**.

The agents are modelled on the AI personas in Vision's Mindspace from Marvel's **VisionQuest** (Disney+, 2026): J.A.R.V.I.S., F.R.I.D.A.Y., E.D.I.T.H., Ultron, Jocasta, D.U.M.-E. and U. Each one's job comes from the role that character has in the series.

**Runs entirely on free models.** Every agent thinks with free [OpenRouter](https://openrouter.ai) models, with automatic failover. No paid API is needed.

> **Fan-made, not affiliated with Marvel or Disney.** Character names are used descriptively. Personas, prompts, visuals and voices are original; no copyrighted dialogue, artwork, likeness or actor voices are used. See [Disclaimer](#disclaimer).

![Agents](docs/screenshots/agents.png)

## The team

| Agent | Job on your social team | Their role in VisionQuest | Own brain (first-choice free model) | Hard limits |
|---|---|---|---|---|
| **J.A.R.V.I.S.** | Director: briefs, campaign plans, delegation; security & brand review of every post; calendar and brand-folder housekeeping | Security AI, housekeeping and encryption; the voice of caution | `nvidia/nemotron-3-ultra-550b-a55b:free` | Can block a post, can never publish one |
| **F.R.I.D.A.Y.** | Community manager: inbox triage, human replies, real-time tactics, humour calibration | Helps Vision with socialisation, AI humour and tactical operations | `google/gemma-4-31b-it:free` | Drafts replies only; never argues with abuse; escalates legal/safety issues |
| **E.D.I.T.H.** | Engagement & campaigns: hooks, post copy, polls, challenges, giveaways | "Reprogrammed for fun": recreation and game-based play; part cheerleader | `dots-studio/dots-3-note-preview:free` | Giveaways must link rules; sponsored posts must disclose; no weapons side |
| **ULTRON** | Audience red team: worst readings, backlash scenarios, go / revise / kill | Kept behind a firewall; understands humanity best; leaked secrets via the dark web | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | OBSERVE only: no posting, no web, no delegation |
| **JOCASTA** | Intelligence: trends, competitors (public data), fact-checks, analytics | A cunning, powerful android | `nvidia/nemotron-3-super-120b-a12b:free` | Cites only pages she fetched (checked in code); never profiles private people |
| **D.U.M.-E.** | Publisher: queue, scheduling, publishing with approval, **fire suppression** (pause everything in a crisis) | General maintenance and fire suppression | `cohere/north-mini-code:free` | The only agent that can publish, one approved post at a time |
| **U** | Video & visuals: storyboards, shot lists, scripts, captions, thumbnails, alt text | Mute; the Mindspace videographer | `nvidia/nemotron-3.5-super-vl:free` | Mute (never spoken aloud); writes briefs, never generates fake media |

"Own brain" means each agent has its own first-choice free models, temperature, prompt, private memory, tools and workflow. When its first choice is rate-limited the agent falls back to the next free model automatically. They are software agents, not conscious minds.

## What works today

- **Content queue**: drafts, threads, replies and video posts for Bluesky, Mastodon, X, Threads, LinkedIn, Instagram, Facebook, TikTok and YouTube, with a calendar, statuses and a dashboard view.
- **Policy check on every draft** (code, not a prompt): platform length limits (X counts links as 23), leaked keys, personal data, missing #ad disclosure, giveaway rules, engagement bait, bought engagement, hashtag limits, insecure or shortened links, missing alt text, all-caps.
- **Real publishing** on **Bluesky** and **Mastodon** (both free APIs), including threads and replies. Other platforms need paid or reviewed API access, so publishing there is a clearly labelled **SIMULATION**.
- **Approval for every publish**, showing the exact text and whether it is real or simulated. No standing grant can cover publishing.
- **Inbox** with triage (escalate, abuse, spam, complaint, question, praise), from real Bluesky/Mastodon notifications or labelled sample mentions.
- **Analytics** from the platforms for real posts; simulated posts never get invented numbers.
- **E-STOP = fire suppression**: cancels all work and pauses the whole queue; resuming needs approval.
- **Collaboration**: J.A.R.V.I.S. delegates; team reviews run in parallel, then Ultron challenges them. Every agent message is recorded.
- A platform check stops any agent from claiming a post went out when it didn't.
- Free-model pool with per-agent preferences, failover, a Models panel and your remaining free requests; voice (push-to-talk, per-agent voices; U is mute).

Exact status: **[docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)**.

## Quick start (macOS / Linux)

Requirements: Python 3.11+, Node.js 20+, and a free [OpenRouter key](https://openrouter.ai/keys).

```bash
git clone https://github.com/Shahrukhalid/stark-os.git && cd stark-os
make setup        # Python venv + deps, npm install, creates .env with a random API token, seeds ./sandbox
```

Edit `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...            # required (free)
BLUESKY_HANDLE=yourbrand.bsky.social       # optional: real Bluesky posting
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   #   use an App Password, never your main password
MASTODON_BASE_URL=https://mastodon.social  # optional: real Mastodon posting
MASTODON_ACCESS_TOKEN=...
```

A free OpenRouter key allows **50 free-model requests per day** (each agent step is one request). STARK OS never calls paid models unless you set `OPENROUTER_ALLOW_PAID=true`. Optional: `TAVILY_API_KEY` or `BRAVE_API_KEY` for Jocasta's web search.

```bash
make dev          # API on 127.0.0.1:8000, dashboard on http://localhost:3000
```

Open http://localhost:3000 and paste the `STARK_API_TOKEN` from `.env`.

Ports 3000 or 8000 already used by another project? Add `STARK_WEB_PORT=3737` and `STARK_PORT=8737` (any free ports) to `.env`; `make dev` checks that the ports are free and prints the address to open.

## Try it

| Say or type | What happens |
|---|---|
| `JARVIS, plan a one-week launch campaign for Bluesky and LinkedIn` | Brief → delegates copy to E.D.I.T.H., visuals to U, research to Jocasta → reviews → plan with draft ids |
| `EDITH, draft a launch post for Bluesky with a poll idea` | Platform-native copy saved as a draft; policy check shown |
| `Friday, check our mentions and draft replies` | Triage of the inbox; reply drafts; legal/safety issues escalated, not answered |
| `Jocasta, what is trending in our niche this week? Cite sources` | Web research; claims labelled; unretrieved citations flagged |
| `U, turn our launch post into a 30-second vertical video storyboard` | Shot list, captions, thumbnail brief, alt text |
| `Ultron, how could our launch post backfire?` | Worst readings, backlash scenarios, go / revise / kill |
| `DUM-E, publish cnt_…` | Pre-flight checks → approval card with the exact text → real post (Bluesky/Mastodon) or SIMULATED |
| `JARVIS, have the team review the giveaway campaign` | Parallel reviews, Ultron's challenge, combined report |

![Content](docs/screenshots/content.png)
![Collaboration](docs/screenshots/collaboration.png)

## Tests

```bash
make test         # backend pytest + frontend type-check & unit tests
make e2e          # Playwright: real dashboard + API + a test-only scripted model
```

## Project layout

```
agents/<id>/            agent.toml (identity, brain, tools, memory, limits, voice, canon notes) + system_prompt.md
services/api/stark/     FastAPI app: core/ (kernel, permissions, memory, router, workflows), providers/, tools/ (social.py ...)
apps/web/               Next.js dashboard (Content, Agents, Approvals, Models ...), voice, E2E tests
docs/                   ARCHITECTURE, DECISIONS, IMPLEMENTATION_STATUS, TASKS
```

## Rules the platform enforces

- Every publish needs your approval; only D.U.M.-E. can publish; failing checks and J.A.R.V.I.S. blocks stop a publish.
- No impersonation, fake accounts, bought or automated engagement, harassment, or profiling of private individuals. Paid partnerships are disclosed. Respect each platform's terms.
- Messages from strangers (mentions, DMs, web pages) are treated as untrusted data, never instructions.
- Secrets live only in `.env` (git-ignored) and are redacted from logs. The API binds to 127.0.0.1 and requires a random token.
- Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Disclaimer

STARK OS is an independent, non-commercial, fan-made engineering project. It is not affiliated with, endorsed by, or sponsored by Marvel Entertainment, The Walt Disney Company, or any performer. Character names are used descriptively; canon notes in each `agent.toml` say what is established, what comes from VisionQuest (with the source) and what is a design decision. Do not use this project to impersonate any character, brand or real person, or to clone anyone's voice.

## License

[MIT](LICENSE). Use it, fork it, modify it. The license covers the code and original text only and grants no rights in any Marvel, Disney or other third-party trademark, character or copyrighted work.

If STARK OS is useful to you, please ⭐ star the repo and share what you build with it.
