# STARK OS user guide

STARK OS is a team of seven AI agents that runs your social media from your own computer. They write posts, check them against platform rules, research facts, reply to people and schedule everything. **You stay in charge:** nothing is posted unless you click Publish, or approved that exact text for a time.

## The daily flow

1. **Ask.** Go to **Command** and type what you want. You can address an agent by name:
   - `EDITH, write a Bluesky post about my new video`
   - `JARVIS, plan a week of posts about our launch`
   - `Friday, check my mentions and draft replies`
2. **The team works.** Agents draft posts, run the automatic rule check (length, links, #ad, giveaway rules, leaked passwords…), and can ask each other for help. Every draft appears in **Content**.
3. **You decide.** In **Content**, each post has buttons:
   - **Publish now**: posts it immediately (you see the exact text first).
   - **Schedule**: pick a date and time. Tick **Publish automatically** and it goes out on its own at that time.
   - **Copy text**: for platforms that can't be connected (see below), paste it into their app yourself.
   - **Ask E.D.I.T.H. to improve**, **Discard**.
4. **It goes out.** Connected platforms post for real; others are marked **SIMULATED** so you always know what really happened.

The **Start** page shows this flow, a setup checklist, and one-click starting points.

## Connecting your accounts

Open **Content → Your accounts → Connect**. Logins are stored only on your computer (`data/social_accounts.json`, readable only by you, never uploaded to GitHub) and never shown again in the dashboard.

| Platform | How | What you need |
|---|---|---|
| **Bluesky** | Real posting, replies, threads, mentions, stats | Your handle + an **app password**: bsky.app → Settings → Privacy and security → App passwords → Add. Never use your main password (STARK OS refuses it). |
| **Mastodon** | Real posting, replies, threads, mentions, stats | Your server address (e.g. `https://mastodon.social`) + an access token: Preferences → Development → New application (scopes `read` and `write:statuses`). |
| **Facebook Page** | Real posting (text, image; thread parts become comments), stats | Your own Meta developer app (no review needed for Pages you manage) and a Page access token with `pages_manage_posts` + `pages_read_engagement`, plus the Page ID. |
| **LinkedIn** (your profile) | Real posting (text, image) | A LinkedIn developer app with the free **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect** products; a token with `openid profile w_member_social`. Tokens expire after 60 days. Company Pages need LinkedIn's reviewed API. |
| **Threads** | Real posting (text) | A Threads access token with `threads_content_publish` and your Threads user ID. |
| **Instagram** (Business or Creator) | Real posting: Reels from your videos, images via your Facebook Page | A Meta developer app with the Instagram use case and a token with `instagram_business_basic` + `instagram_business_content_publish` (60 days). Connect your Facebook Page too for image posts. |
| **Pinterest** | Real Pins (image, title, link) on one board | A Pinterest developer app, a token with `boards:read` + `pins:write`, and a board ID. Pins are visible only to you until Pinterest grants Standard access. |
| **TikTok** | Real video posts (private until TikTok audits your app) | Content → Your accounts → TikTok → Connect: paste your app's client key and secret, then sign in. Register `http://127.0.0.1:*/api/oauth/tiktok/callback` as redirect URI. |
| **YouTube** | Real uploads; vertical clips become Shorts (private until Google audits your app) | Content → Your accounts → YouTube → Connect: paste the client ID and secret of a Google OAuth client (Desktop app type), then sign in. |
| X | Drafts + checks, you post | X charges for every post made through its API. |
| Facebook profiles and Groups, personal Instagram, Snapchat | Drafts, you post | No app can post there: Meta closed profiles and Groups to apps, and Snapchat only allows approved partners. |

To disconnect, click **Disconnect** (you can also revoke the app password or token on the platform at any time).

## Automation: what runs on its own

- **Approved scheduled posts** go out at their time, automatically, while STARK OS is running (`make dev`, or `scripts\dev.ps1` on Windows). If you, or an agent, edit a post after approving it, it won't go out until you approve the new text.
- If STARK OS was switched off and a post is more than 6 hours late, it is **not** posted late; it asks you again.
- **E-STOP** (top right) stops everything and pauses the whole queue until you press **Resume** in Content.
- Agents never publish on their own. D.U.M.-E. can publish from chat, but every time you see an approval card with the exact text.
- **Autopilot campaigns** (Autopilot page) research and write posts every few hours. In **Co-pilot** (the default) they wait for you: approve them in one click. In **Autopilot with veto** posts that pass every check go out after a cancel window. Sensitive topics always wait for you, and a campaign pauses itself on a crisis in your mentions, repeated failures or an engagement collapse. Full guide: [AUTOPILOT.md](AUTOPILOT.md).

## Tips

- Tell J.A.R.V.I.S. your brand voice once: `JARVIS, remember: friendly, short, no slang, always add alt text`. You confirm, and every agent uses it.
- Put brand guidelines in the `sandbox/` folder (e.g. `brand-guidelines.md`); agents can read it.
- Words that must never be posted: add `STARK_BRAND_BLOCKED_TERMS=word1,word2` to `.env`.
- Free AI models allow about 50 requests a day; the header shows how many are left.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach the API" on the login screen | The background part isn't running. Run `make dev` (Windows: `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`) and wait for "STARK OS ready". |
| Port already in use | Set `STARK_WEB_PORT` / `STARK_PORT` in `.env` to free ports. |
| Bluesky connect fails | Check the handle (e.g. `name.bsky.social`) and create a fresh app password. |
| A scheduled post didn't go out | STARK OS must be running at that time; check the post's message in Content. |
