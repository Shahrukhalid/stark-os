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
| X, Instagram, Facebook, LinkedIn, Threads, TikTok, YouTube | Drafts + checks, you post | These companies charge for or restrict posting from other apps. The team still writes posts sized for each platform; use **Copy text**. |

To disconnect, click **Disconnect** (you can also revoke the app password or token on the platform at any time).

## Automation: what runs on its own

- **Approved scheduled posts** go out at their time, automatically, while STARK OS is running (`make dev`). If you, or an agent, edit a post after approving it, it won't go out until you approve the new text.
- If STARK OS was switched off and a post is more than 6 hours late, it is **not** posted late; it asks you again.
- **E-STOP** (top right) stops everything and pauses the whole queue until you press **Resume** in Content.
- Agents never publish on their own. D.U.M.-E. can publish from chat, but every time you see an approval card with the exact text.

## Tips

- Tell J.A.R.V.I.S. your brand voice once: `JARVIS, remember: friendly, short, no slang, always add alt text`. You confirm, and every agent uses it.
- Put brand guidelines in the `sandbox/` folder (e.g. `brand-guidelines.md`); agents can read it.
- Words that must never be posted: add `STARK_BRAND_BLOCKED_TERMS=word1,word2` to `.env`.
- Free AI models allow about 50 requests a day; the header shows how many are left.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach the API" on the login screen | The background part isn't running. Run `make dev` and wait for "STARK OS ready". |
| Port already in use | Set `STARK_WEB_PORT` / `STARK_PORT` in `.env` to free ports. |
| Bluesky connect fails | Check the handle (e.g. `name.bsky.social`) and create a fresh app password. |
| A scheduled post didn't go out | STARK OS must be running at that time; check the post's message in Content. |
