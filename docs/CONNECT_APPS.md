# "Log in with …": Nexonic's official apps

STARK OS shows **Log in with Facebook / Instagram / Threads / LinkedIn / TikTok / YouTube / Pinterest** when it knows
the address of a **STARK Connect** server (`STARK_CONNECT_URL`, or `DEFAULT_CONNECT_URL` in
`services/api/stark/config.py` for release builds). STARK Connect (`services/connect/worker.js`) keeps the app secrets,
sends the browser back to the user's own computer after sign-in and swaps the code for tokens. It stores nothing.

Until a platform approves an app, only people added to that app as testers/developers can log in. Everyone else can
still use **Own app** (their own developer app), as before.

## 1. Deploy STARK Connect (a free serverless worker plan is enough)

```bash
cd services/connect
npx wrangler login
npx wrangler deploy                      # note the address, e.g. https://stark-connect.<you>.workers.dev
```

Optionally attach a custom domain (e.g. `connect.yourdomain.com`). Set `PUBLIC_ORIGIN` in `wrangler.toml` to that
final address and deploy again. Then set the shared signing key once:

```bash
npx wrangler secret put STATE_KEY        # paste 32+ random characters (e.g. from: openssl rand -base64 32)
```

For every platform below add two secrets: `npx wrangler secret put <PLATFORM>_CLIENT_ID` and
`npx wrangler secret put <PLATFORM>_CLIENT_SECRET` (`FACEBOOK_…`, `INSTAGRAM_…`, `THREADS_…`, `LINKEDIN_…`,
`TIKTOK_…` with the client key as ID, `YOUTUBE_…`, `PINTEREST_…`). A platform without secrets simply reports
"not set up". Check with `https://<PUBLIC_ORIGIN>/health`.

Every redirect URI is `<PUBLIC_ORIGIN>/cb/<platform>`, e.g. `https://connect.yourdomain.com/cb/facebook`.

## 2. Register the apps

| Platform | Where | Product / scopes | Before everyone can log in |
|---|---|---|---|
| Facebook Pages | Meta for Developers → Create app → Business → Facebook Login for Business | `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `business_management` | App Review for those permissions + Business Verification of Nexonic Technologies |
| Instagram | Same or a second Meta app → Instagram use case → API setup with Instagram login | `instagram_business_basic`, `instagram_business_content_publish` | App Review (Advanced Access) |
| Threads | Meta app → Threads use case | `threads_basic`, `threads_content_publish`, `threads_manage_insights` | App Review |
| LinkedIn | LinkedIn Developers → Create app (needs a Nexonic LinkedIn Page) → products **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect** | `openid profile w_member_social` | Nothing: both products are self-serve |
| TikTok | TikTok for Developers → app (platform: Web) → Login Kit + Content Posting API (Direct Post) | `user.info.basic`, `video.upload`, `video.publish` | App review to go live; the Content Posting audit to post publicly (until then posts are private) |
| YouTube | Google Cloud → enable YouTube Data API v3 → OAuth consent screen (External) → OAuth client **Web application** | `youtube.upload`, `youtube.readonly` | Google verification of the sensitive scopes (until then: a warning screen and at most 100 users) and the YouTube API audit for public uploads |
| Pinterest | Pinterest Developers → Create app | `boards:read`, `pins:read`, `pins:write`, `user_accounts:read` | Standard access (request with a demo video; until then Pins are visible only to you) |

Every review asks for a privacy policy URL, a terms URL, an app icon and a screen recording of the log in and a
post being published. Record them in STARK OS with a tester account.

## 3. Ship it

Set `DEFAULT_CONNECT_URL` in `services/api/stark/config.py` to the STARK Connect address and release. Users can also
set `STARK_CONNECT_URL` in `.env` (self-hosting) to use their own STARK Connect.

## Notes

- Instagram and Threads tokens last about 60 days; STARK OS renews them about once a week, so they don't expire
  while the app runs at least every few weeks. Pinterest (30 days) is renewed through STARK Connect when the login
  returned a refresh token. LinkedIn tokens can't be renewed by ordinary apps: Account health warns 10 days before
  the 60 days are up. TikTok and YouTube refresh themselves.
- STARK Connect only redirects to `http://127.0.0.1:<port>/api/oauth/<platform>/callback`, signs the state, and
  rejects sign-ins older than 15 minutes.
