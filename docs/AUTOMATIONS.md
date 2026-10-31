# Automations

STARK OS has its own **Automations** page ("when this happens, do that"). It also connects to other automation apps in both directions:

| Direction | How | Typical use |
|---|---|---|
| **Inside STARK OS** | Automations page: trigger → conditions → actions | Thank-you drafts for praise, phone alerts for complaints, daily ideas, weekly recaps, UTM tags |
| **Other app → STARK OS** | An automation with the trigger *Another app calls a webhook* | Spreadsheet rows, new shop products, feed items or form answers become **drafts** |
| **STARK OS → other app** | The action *Send to a webhook*, or `STARK_WEBHOOK_URLS` for every event | Log published posts to a spreadsheet or notes database, email a weekly digest, open a help-desk ticket |

Automations never publish on their own. They can draft, label, tag links, notify your phone, ask an agent and call webhooks. Every post still waits for your approval (or for an Autopilot trust level you chose).

## 1. Automations inside STARK OS

Open **Automations** in the left menu.

- **Recipe gallery**: ready-made automations. *Use recipe* adds one **switched off**, so you can check it first.
- **New automation**:
  1. **When**: an event (a draft is created, a post is scheduled, published or fails, Listening finds a mention, an agent needs approval, Autopilot raises an alert), a schedule (every day or every week at a time), or a webhook.
  2. **Only if**: conditions that must all match, e.g. `data.platform` *is* `bluesky`, `data.category` *contains any of* `complaint, escalate`, `data.likes` *is more than* `50`.
  3. **Then do**: up to six actions in order. Text fields can use placeholders such as `{{data.text}}`, `{{data.author}}`, `{{data.url}}`, `{{event}}`.
- **Test**: paste sample event data and click *Dry run* to see which conditions match and the exact text of each step. *Run for real* performs the actions.
- **Run history**: every run with the result or error of each step.

Safety limits: at most 20 runs per automation per hour; what an automation creates never triggers automations again (no loops); webhook calls go only to `https://` addresses.

### Event fields

| Event | Useful fields |
|---|---|
| `post.drafted`, `post.scheduled`, `post.published`, `post.failed` | `data.id`, `data.platform`, `data.text`, `data.campaign`, `data.scheduled_for`, `data.external_url`, `data.created_by` |
| `mention.found` | `data.id`, `data.platform`, `data.author`, `data.text`, `data.url`, `data.category` (praise, question, complaint, escalate…), `data.likes`, `data.kind` (keyword, hashtag, account), `data.watch` |
| `approval.needed` | `data.agent_id`, `data.tool_id`, `data.action` |
| `autopilot.alert` | `data.campaign`, `data.message` |
| webhook | whatever JSON the other app sent, as `data.…` |

## 2. Other app → STARK OS (drafts)

1. In STARK OS, open **Automations → Recipe gallery** and use **Drafts from other apps**. Edit it if you want another platform, then switch it on.
2. Copy the secret address shown on the automation, e.g. `http://127.0.0.1:8000/api/hooks/aut_…/…`. The long last part is the password: keep it private. Deleting the automation, or changing its trigger away from webhook, retires the address.
3. If the other app runs in the cloud, it cannot reach `127.0.0.1`. Put a tunnel (an HTTPS reverse proxy to your computer) in front of STARK OS and forward **only** paths starting with `/api/hooks/`; answer everything else with 404.
   - The `/api/hooks/` endpoints need no API token (the secret in the address is the password), accept at most 64 KB and only run switched-on automations. Every other `/api/…` endpoint still requires your `STARK_API_TOKEN`.
4. In the other app, add an HTTP request step:

   | Setting | Value |
   |---|---|
   | URL | your tunnel address + `/api/hooks/aut_…/…` |
   | Method | `POST` |
   | Body | JSON |
   | Content type | `application/json` |
   | Body content | `{"platform": "bluesky", "text": "<title> <link>"}` (map the fields from the earlier step) |

   The response is `{"ok": true, "steps": [{"type": "create_draft", "result": "draft cnt_… (pass)"}]}`.
5. The draft appears in **Content**, with the usual policy check, for you to approve.

### Example set-ups

| In the other app | STARK OS automation |
|---|---|
| **New spreadsheet row** → HTTP request with `{"platform": "<platform column>", "text": "<text column>"}` | Webhook trigger → *Create a draft* with `{{data.text}}` (one automation per platform, or a condition on `data.platform`) |
| **New shop product** → HTTP request with `{"text": "New in the shop: <title> <url>"}` | Webhook trigger → *Ask an agent*: "EDITH, write a launch post for: {{data.text}}" |
| **New feed item** → HTTP request with `{"text": "<title> <url>"}` | Webhook trigger → *Ask an agent*: "EDITH, write a 4-part thread from {{data.text}}" |
| **New form answer** → HTTP request | Webhook trigger → *Create a draft* or *Message my phone* |

## 3. STARK OS → other app

**Per automation**: add the action **Send to a webhook** with the incoming-webhook address the other app gives you. The recipe **Log every published post to another app** does this for each published post. The body is:

```json
{"automation": "Log every published post to another app", "event": "post.published", "at": "2026-11-01T09:00:00Z",
 "data": {"id": "cnt_…", "platform": "bluesky", "text": "…", "external_url": "https://bsky.app/…"}}
```

Run the automation once with **Test → Run for real**, so the other app learns the fields.

**For every event**: set `STARK_WEBHOOK_URLS=https://…` in `.env`. Each request is signed with `X-Stark-Signature: sha256=…` when `STARK_WEBHOOK_SECRET` is set (HMAC-SHA256 of the raw body).

### Example set-ups

| Goal | In the other app |
|---|---|
| **Published posts → spreadsheet log** | Incoming webhook → add a row (date, platform, text, link) |
| **Published posts → notes database** | Incoming webhook → create a database item |
| **Failed posts → email** | Incoming webhook → filter `event = post.failed` → send an email |
| **Complaints → help-desk ticket** | Incoming webhook (from an automation on `mention.found` with category *complaint*) → create a ticket |
