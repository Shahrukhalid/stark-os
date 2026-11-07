# STARK OS

[![CI](https://github.com/Shahrukhalid/stark-os/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahrukhalid/stark-os/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/Shahrukhalid/stark-os?color=22d3ee)](https://github.com/Shahrukhalid/stark-os/releases/latest) [![License: MIT](https://img.shields.io/badge/License-MIT-22d3ee.svg)](LICENSE) [![Website](https://img.shields.io/badge/website-stark--os-22d3ee)](https://shahrukhalid.github.io/stark-os/)

Free, self-hosted AI social media manager. Seven AI agents write, check, schedule and publish your posts. Nothing goes out without your approval. Runs on your computer with free AI models.

![STARK OS demo](docs/demo.gif)

## Download

| Computer | Installer |
|---|---|
| Mac (Apple silicon) | [STARK-OS-macOS-AppleSilicon.dmg](https://github.com/Shahrukhalid/stark-os/releases/latest/download/STARK-OS-macOS-AppleSilicon.dmg) |
| Mac (Intel) | [STARK-OS-macOS-Intel.dmg](https://github.com/Shahrukhalid/stark-os/releases/latest/download/STARK-OS-macOS-Intel.dmg) |
| Windows 10 / 11 | [STARK-OS-Windows-Setup.exe](https://github.com/Shahrukhalid/stark-os/releases/latest/download/STARK-OS-Windows-Setup.exe) |

1. Install and open STARK OS. No Python, Node.js or terminal needed.
2. Paste a free AI key ([openrouter.ai/keys](https://openrouter.ai/keys)) and press **Test connection**.
3. Connect your accounts, press **Save and start**.

First launch: Mac, right-click → **Open**. Windows, **More info → Run anyway** (installers are not signed yet).

## The team

| Agent | Job | Limit |
|---|---|---|
| **J.A.R.V.I.S.** | Director: plans campaigns, delegates, reviews security and brand | Can block a post, never publish |
| **F.R.I.D.A.Y.** | Community manager: inbox, replies | Drafts replies only, escalates legal/safety issues |
| **E.D.I.T.H.** | Writer: posts, hooks, polls, giveaways | Giveaways need rules, sponsored posts need #ad |
| **ULTRON** | Red team: how a post could backfire (go / revise / kill) | Read-only |
| **JOCASTA** | Research: trends, competitors, fact-checks, analytics | Cites only pages she read |
| **D.U.M.-E.** | Publisher: queue, schedule, publish, crisis pause | The only agent that can publish |
| **U** | Visuals: storyboards, scripts, captions, AI images, alt text | No fake photos or real people |

Each agent has its own free model with automatic fallback, its own prompt, memory and tools.

## Features

### Create
- **Command**: talk to any agent by text or voice.
- **Compose**: live preview per platform, character counter, engagement score (0–100) with tips.
- **12 platforms**: Bluesky, Mastodon, X, Threads, LinkedIn, Instagram, Facebook, TikTok, YouTube, Telegram, Discord, Slack.
- **Translate** into 13 languages.
- **Quote cards and carousels** made on your computer.
- **Video studio** (on your computer, FFmpeg included in the desktop app):
  - Trim with start/end frame previews, join up to 10 videos with cross-fades, speed 0.5–2×, volume, fade in/out, remove sound.
  - Platform sizes (9:16, 1:1, 4:5, 16:9; bars or crop), several sizes in one go, MP4, WebM or GIF.
  - **Speech to text** with timestamps (whisper.cpp). The speech model (75–466 MB) is downloaded once when you ask, then works offline.
  - Captions timed to the speech, a script or your own SRT: burned in with size, colour, position and box, as a switchable track or as an .srt file.
  - **Shorts package**: from a long video, U picks the best moments from the transcript (a clear rule does it when no AI model is connected), then STARK OS makes vertical clips with animated captions and thumbnails and writes a title, hook, description and hashtags as drafts for each platform you choose. Every draft still waits for your approval.
  - Caption animations (fade, pop, word-by-word) and 9 transitions between joined videos.
  - **Clips for Shorts, Reels and TikTok**: the transcript is split into short clips at sentence ends; export them all at once, or ask U for the best moments.
  - Progress bars, cancel, uploads up to 2 GB streamed to disk, thumbnails into the media library.
- **Repurpose**: blog post, video or text → posts, threads and a video script.
- **AI images**: free illustrations with alt text.
- **Library**: templates, hashtag groups, signatures. **Bulk import** of up to 500 posts (CSV).

### Check
- **Policy check** on every draft: length, leaked keys, personal data, missing #ad, giveaway rules, engagement bait, unsafe links, missing alt text.
- **Team review**: brand, facts and backlash risk.
- **Approval** of the exact text; any edit cancels it.

### Schedule and publish
- **Queue and calendar** (drag and drop), **auto-schedule** at your best times, weekly **posting plan** with content mix.
- **Real posting** to Bluesky, Mastodon, Threads, Facebook Pages, LinkedIn, Instagram, Pinterest, TikTok, YouTube, Telegram, Discord and Slack. Ready-to-paste posts for the others.
- **Publish automatically** once approved.
- **Your channels → drafts**: new YouTube video, podcast or blog post becomes a draft.
- **UTM link tracking**, **evergreen recycling**, **.ics export**, Bluesky reply controls.

### Autopilot
- Campaigns research news (RSS, Hacker News, Reddit, web), pick keywords and hashtags, write, fact-check and schedule.
- Trust levels: **Co-pilot** → **Autopilot with veto** → **Full auto** (after 10 clean posts).
- Pauses itself on a crisis, failures or an engagement drop. Sensitive topics always wait for you.

### Automations
- "When this happens, do that": triggers, conditions, chained actions (ask an agent, draft, label, notify, webhook).
- Ready-made recipes, test runs, run history. Never publishes; max 20 runs per hour.
- **Monitoring and recovery**: a step that fails on a network error is tried again; a failed run can be retried with one click; after 3 failed runs in a row the automation pauses itself and alerts your phone and webhooks. Success rate for the last 24 hours.

### Brands
- Several brands or clients in one app: voice, audience, guidelines, hashtags, platforms, blocked words.
- **Brand switcher** in the header: queue, analytics, campaigns, listening, library and automations show only the active brand; items without a brand are shared.
- Every agent task keeps the brand it was started for, even if you switch brands while it runs or two brands work at once (voice, memories, library and blocked words). Automations act as their own brand.
- Agents only recall the active brand's memories. Each campaign writes with its own brand's voice and blocked words.
- A brand's automations never act on another brand's posts or mentions.

![Brands](docs/screenshots/brands.png)

### Accounts
- **Account health**: connected accounts checked every 6 hours without posting (expired login, revoked token, bot removed, deleted webhook, failed posts).
- **Reconnect** button on Start and a phone alert when an account breaks.

![Start page with account health](docs/screenshots/start.png)

### Listen and engage
- **Inbox**: mentions sorted into escalate, abuse, spam, complaint, question, praise; reply drafts in the poster's language.
- **Listening**: keywords, hashtags and competitors; **mood** (happy / neutral / unhappy) for every mention.
- **Hashtag research**: activity, engagement, related tags, mood and top posts.
- **Bluesky messages**, saved replies, inbox labels.

### Measure
- **Analytics**: real likes, reposts, replies, 30-day chart, best-time heatmap, top posts, per campaign and brand, CSV.
- **Report** download, **A/B hook tests**, **learn my voice**.
- **Growth**: followers, posting streak, top fans, rising hashtags, proven ideas, Bluesky starter packs.

### Control
- **Phone approvals** via Telegram buttons, Discord alerts, daily digest.
- **E-STOP** cancels everything and pauses the queue.
- **Modes**: Observe, Assist, Execute approved.
- **Live** view of the agents working, full task traces, memory and audit log.
- **Desktop app**: keys in Keychain / Credential Manager, engine restarts on crash, one window at a time.

### Connect
- **MCP server** for AI assistants and editors (cannot publish).
- **Signed webhooks** for drafted, scheduled, published, failed, mention, approval and account-health events.
- **REST API** with a private token.

## Screenshots

| | |
|---|---|
| ![Live](docs/screenshots/live.png) | ![Calendar](docs/screenshots/calendar.png) |
| ![Content](docs/screenshots/content.png) | ![Approval](docs/screenshots/approval.png) |
| ![Compose](docs/screenshots/compose.png) | ![Command](docs/screenshots/command.png) |
| ![Analytics](docs/screenshots/analytics.png) | ![Listening](docs/screenshots/listening.png) |
| ![Autopilot](docs/screenshots/autopilot.png) | ![Automations](docs/screenshots/automations.png) |
| ![Studio](docs/screenshots/studio.png) | ![Library](docs/screenshots/library.png) |
| ![Agents](docs/screenshots/agents.png) | ![Team review](docs/screenshots/collaboration.png) |

Screenshots use sample data.

## Self-host with Docker Compose

Needs Docker with Compose v2.24 or newer. No `.env` file is required.

```bash
git clone https://github.com/Shahrukhalid/stark-os.git && cd stark-os
docker compose up -d --build                     # on Linux: UID=$(id -u) docker compose up -d --build
docker compose exec api cat /app/data/api-token  # paste this token into the dashboard's Connect screen
```

- Dashboard: http://localhost:3000 · API health: http://localhost:8000/api/health (both bound to localhost only).
- The token is created on first start and kept in the `stark-data` volume, so it survives restarts. A `STARK_API_TOKEN` in `.env` takes precedence; `python scripts/setup.py` still creates a `.env` for you.
- Add `OPENROUTER_API_KEY` to `.env` for the AI agents.
- Data: SQLite in the `stark-data` volume, your files in `./sandbox`. Optional PostgreSQL: set `POSTGRES_PASSWORD` and `DATABASE_URL` in `.env`, then `docker compose --profile postgres up -d`.
- Hardened mode (read-only filesystems, no extra privileges, resource limits): `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. It does not make STARK OS safe to expose to the internet on its own; put it behind TLS and your own access control first.
- Status and logs: `docker compose ps`, `docker compose logs -f`. Stop with `docker compose down` (`down -v` also deletes your data).
- If startup fails: `docker compose config --quiet`, then `docker compose logs --tail=100 api`, and check that ports 3000 and 8000 are free.

## Run from source

Needs Python 3.11+, Node.js 20+ and Git.

```bash
git clone https://github.com/Shahrukhalid/stark-os.git && cd stark-os
make setup          # creates .env; add OPENROUTER_API_KEY there
make dev            # open http://localhost:3000, paste STARK_API_TOKEN from .env
```

Windows: `scripts\setup.ps1` then `scripts\dev.ps1`. Other ports: set `STARK_WEB_PORT` and `STARK_PORT` in `.env`.

Tests: `make test` (backend + frontend), `make e2e` (browser).

## Safety

- Every post needs your approval or a trust level you set.
- No fake accounts, bought engagement, harassment or profiling of private people.
- Messages from strangers are treated as data, never instructions.
- Secrets stay on your computer and are hidden from logs. Report vulnerabilities via [SECURITY.md](SECURITY.md).

## Docs

[User guide](docs/USER_GUIDE.md) · [Autopilot](docs/AUTOPILOT.md) · [Automations](docs/AUTOMATIONS.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md)

## Disclaimer

Fan-made project, not affiliated with Marvel or Disney. Agent names are used descriptively; prompts, visuals and voices are original.

## License

[MIT](LICENSE)

The desktop app includes FFmpeg (via imageio-ffmpeg, BSD-2-Clause; FFmpeg itself is GPL) and whisper.cpp (via pywhispercpp, MIT); see [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).
