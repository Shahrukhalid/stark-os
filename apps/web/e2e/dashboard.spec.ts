import { expect, test, type Page } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";

const TOKEN = "e2e-token-0123456789abcdefghijkl";

async function connect(page: Page) {
  await page.goto("/");
  await page.getByLabel("API address", { exact: false }).or(page.locator("input").first()).fill("http://127.0.0.1:8100");
  await page.getByPlaceholder("STARK_API_TOKEN from your .env").fill(TOKEN);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Project Genesis").first()).toBeVisible();
  await expect(page.getByRole("banner").getByText("Live", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Your AI social media team")).toBeVisible(); // lands on the Start page
  await page.getByRole("button", { name: "Command", exact: true }).click();
}

async function send(page: Page, text: string) {
  await page.getByLabel("Message").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test("rejects a wrong token", async ({ page }) => {
  await page.goto("/");
  await page.locator("input").first().fill("http://127.0.0.1:8100");
  await page.getByPlaceholder("STARK_API_TOKEN from your .env").fill("wrong-token");
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Token rejected by the API.")).toBeVisible();
});

test("all seven agents are registered with distinct identities", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  for (const name of ["J.A.R.V.I.S.", "F.R.I.D.A.Y.", "E.D.I.T.H.", "ULTRON", "JOCASTA", "D.U.M.-E.", "U"]) {
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await page.screenshot({ path: "e2e/screenshots/agents.png", fullPage: true });
});

test("EDITH drafts; you publish from Content with one click, and the simulation is labelled", async ({ page }) => {
  await connect(page);
  await send(page, "EDITH, draft a launch post for Bluesky");
  await expect(page.getByText(/Drafted (cnt_[0-9a-f]{16}) for Bluesky\. Check: PASS\./)).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Content", exact: true }).click();
  const item = page.getByTestId("content-item").first();
  await expect(item.getByText("STARK OS is live: seven agents, one social team.", { exact: false })).toBeVisible();
  await expect(item.getByText("check PASS")).toBeVisible();
  await expect(page.getByText("NOT CONNECTED").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/content.png", fullPage: true });
  await item.getByRole("button", { name: "Publish (simulation)" }).click();
  await expect(item.getByText(/isn.t connected, so this is a/)).toBeVisible();
  await item.getByRole("button", { name: "Run simulation" }).click();
  await expect(page.getByTestId("content-item").first().getByText("SIMULATED", { exact: true })).toBeVisible({ timeout: 10_000 });
});

test("an approved scheduled post goes out by itself at its time", async ({ page }) => {
  test.setTimeout(180_000);
  await connect(page);
  const drafts = page.getByText(/Drafted (cnt_[0-9a-f]{16})/);
  await page.waitForTimeout(500);
  const before = await drafts.count();
  await send(page, "EDITH, draft a launch post for Bluesky");
  await expect(drafts).toHaveCount(before + 1, { timeout: 20_000 });
  await page.getByRole("button", { name: "Content", exact: true }).click();
  const item = page.getByTestId("content-item").filter({ hasText: "Draft" }).first();
  const id = (await item.innerText()).match(/cnt_[0-9a-f]{16}/)![0];
  const card = page.getByTestId("content-item").filter({ hasText: id });
  await card.getByRole("button", { name: "Schedule" }).click();
  const soon = new Date(Date.now() + 70_000);
  const local = new Date(soon.getTime() - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  await card.getByLabel("Publish date and time").fill(local);
  await card.getByRole("button", { name: "Save schedule" }).click();
  await expect(card.getByText("auto-publish approved")).toBeVisible({ timeout: 10_000 });
  // the scheduler (every second in tests) publishes it once its minute arrives
  await expect(card.getByText("SIMULATED", { exact: true })).toBeVisible({ timeout: 130_000 });
});

test("connecting Bluesky refuses a main password and explains app passwords", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Content", exact: true }).click();
  await page.getByRole("button", { name: "Connect", exact: true }).first().click();
  await page.getByLabel("Bluesky handle").fill("me.bsky.social");
  await page.getByLabel("Bluesky app password").fill("MyRealPassword1");
  await page.getByRole("button", { name: "Connect", exact: true }).first().click();
  await expect(page.getByText(/doesn.t look like a Bluesky app password/)).toBeVisible();
});

test("DUM-E publishes from chat only after the approval card", async ({ page }) => {
  await connect(page);
  const drafts = page.getByText(/Drafted (cnt_[0-9a-f]{16})/);
  await page.waitForTimeout(500); // let an earlier EDITH conversation finish rendering
  const before = await drafts.count();
  await send(page, "EDITH, draft a launch post for Bluesky");
  await expect(drafts).toHaveCount(before + 1, { timeout: 20_000 }); // wait for *this* draft, not an older one
  const id = (await drafts.last().innerText()).match(/cnt_[0-9a-f]{16}/)![0];
  await send(page, `DUM-E, publish ${id}`);
  const approve = page.getByRole("button", { name: "Approve once" });
  await expect(approve).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/SIMULATION ONLY - nothing will be sent to Bluesky/).first()).toBeVisible();
  await approve.click();
  // the reply is rendered as markdown: "*whirr*" becomes italic "whirr"
  await expect(page.getByText(/whirr\s+SIMULATED publish to Bluesky: nothing was sent/).last()).toBeVisible({ timeout: 20_000 });
});

test("FRIDAY triages the inbox and labels sample mentions as simulated", async ({ page }) => {
  await connect(page);
  await send(page, "Friday, check our mentions");
  await expect(page.getByText(/SIMULATED sample inbox: 6 message\(s\), 3 high priority\. Top: escalate/)).toBeVisible({ timeout: 20_000 });
});

test("JARVIS organises the brand folder only after approval", async ({ page }) => {
  await connect(page);
  await send(page, "JARVIS, organize the files in my test folder");
  const approve = page.getByRole("button", { name: "Approve once" });
  await expect(approve).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("test-folder/photo.jpg -> test-folder/Images/photo.jpg")).toBeVisible();
  const sandbox = path.join(process.env.STARK_E2E_DIR!, "sandbox", "test-folder");
  expect(existsSync(path.join(sandbox, "photo.jpg"))).toBe(true);
  await page.screenshot({ path: "e2e/screenshots/approval.png", fullPage: true });
  await approve.click();
  await expect(page.getByText(/Done\. Moved 3 file\(s\), 0 failed/)).toBeVisible({ timeout: 20_000 });
  expect(existsSync(path.join(sandbox, "Images", "photo.jpg"))).toBe(true);
  expect(existsSync(path.join(sandbox, "photo.jpg"))).toBe(false);
});

test("JARVIS runs a whole-team review with visible collaboration", async ({ page }) => {
  await connect(page);
  await send(page, "JARVIS, ask the whole team to review my project");
  await expect(page.getByText(/Team review complete\. Contributions from: friday, edith, jocasta, dum_e, u\. Ultron challenge: completed/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "trace" }).last().click();
  await expect(page.getByText(/Agent messages \(\d+\)/)).toBeVisible();
  await expect(page.getByText("REVIEW_REQUEST").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/collaboration.png", fullPage: true });
});

test("Diagnostics shows real API-host metrics", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Diagnostics", exact: true }).click();
  await page.getByRole("button", { name: "Measure now" }).click();
  await expect(page.getByText("Top CPU process")).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: "e2e/screenshots/diagnostics.png", fullPage: true });
});

test("emergency stop blocks new work until reset", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "E-STOP" }).click();
  await expect(page.getByText(/Emergency stop engaged: all tasks were cancelled/)).toBeVisible();
  await expect(page.getByLabel("Message")).toBeDisabled();
  await page.getByRole("button", { name: "Reset E-Stop" }).click();
  await expect(page.getByLabel("Message")).toBeEnabled();
  await page.screenshot({ path: "e2e/screenshots/command.png", fullPage: true });
});

test("Models panel lists the free pool and pings a model", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Models", exact: true }).click();
  await expect(page.getByText("mock/free-tools:free").first()).toBeVisible();
  await expect(page.getByText(/49 of 50 free requests left today/)).toBeVisible();
  await page.getByRole("button", { name: "Ping", exact: true }).first().click();
  await expect(page.getByText(/ok · \d+ms · tool call/)).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: "e2e/screenshots/models.png", fullPage: true });
});

test("no sideways page scroll on a 360px phone, even with long unbroken text", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await connect(page);
  await send(page, "Jocasta, summarise https://example.com/" + "a".repeat(180) + " for our audience");
  await expect(page.getByText(/JOCASTA acknowledges/)).toBeVisible({ timeout: 20_000 });
  for (const view of ["Start", "Command", "Content", "Autopilot", "Agents", "Tasks", "Approvals", "Memory", "Models", "Tools", "Activity", "Settings"]) {
    await page.getByRole("button", { name: view, exact: true }).first().click();
    await page.waitForTimeout(300);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width, `${view} page width`).toBeLessThanOrEqual(362);
  }
});

test("agent replies render markdown safely", async ({ page }) => {
  await connect(page);
  await send(page, "Ultron, **bold** test [x](javascript:alert(1))");
  const reply = page.getByText(/ULTRON acknowledges/);
  await expect(reply).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
});

test("Start page explains the flow and shows what is left to set up", async ({ page }) => {
  await page.goto("/");
  await page.locator("#stark-api-url").fill("http://127.0.0.1:8100");
  await page.getByPlaceholder("STARK_API_TOKEN from your .env").fill(TOKEN);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Your AI social media team")).toBeVisible({ timeout: 15_000 });
  for (const step of ["1. Ask", "2. The team works", "3. You approve", "4. It goes out"]) await expect(page.getByText(step)).toBeVisible();
  await expect(page.getByText("Connect a social account")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/start.png", fullPage: true });
  await page.getByRole("button", { name: /Write a post/ }).click();
  await expect(page.getByLabel("Message")).toHaveValue(/EDITH, write a friendly Bluesky post about/);
});

test("Autopilot: create a campaign, it researches and writes, you approve the batch", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Autopilot", exact: true }).click();
  await page.getByRole("button", { name: "Create your first campaign" }).click();
  await page.getByLabel("Campaign name").fill("AI agents news");
  await page.getByLabel("Topics (comma separated)").fill("AI agents, open source");
  await page.getByLabel("SEO keywords (comma separated)").fill("ai agents, open source");
  await page.getByLabel("Source type").selectOption("rss");
  await page.getByLabel("Source", { exact: true }).fill("http://127.0.0.1:8799/feed.xml");
  await page.getByLabel("Mastodon").uncheck();
  await page.getByLabel("Posting times").fill("00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00");
  await page.getByLabel("Time zone").fill("UTC");
  await expect(page.getByLabel("Co-pilot")).toBeChecked(); // the safe default
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByRole("heading", { name: "AI agents news" })).toBeVisible();
  // an earlier test pulled the emergency stop: the page says so and Autopilot does not run until you resume
  const halted = page.getByText("Autopilot does not run and nothing is posted", { exact: false });
  if (await halted.isVisible().catch(() => false)) {
    await expect(page.getByRole("button", { name: "Run now" })).toBeDisabled();
    await page.getByRole("button", { name: "Content", exact: true }).click();
    await page.getByRole("button", { name: "Resume" }).first().click();
    await page.getByRole("button", { name: "Autopilot", exact: true }).click();
    await page.getByRole("button", { name: "Open" }).first().click();
    await expect(halted).toBeHidden();
  }
  await page.getByRole("button", { name: "Run now" }).click();
  const post = page.getByTestId("autopilot-post").first();
  await expect(post).toBeVisible({ timeout: 20_000 });
  await expect(post.getByText("approval checks for AI agents", { exact: false })).toBeVisible();
  await expect(post.getByText("#AiAgents", { exact: false })).toBeVisible(); // SEO hashtag added by STARK OS
  // the test feed links over plain http, so the quality gate asks for a look instead of passing it
  await expect(post.getByText("checks need a look")).toBeVisible();
  await expect(post.getByText("Link is not HTTPS", { exact: false })).toBeVisible();
  await expect(post.getByText("fact-checked")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/autopilot.png", fullPage: true });
  await page.getByRole("button", { name: "Approve all" }).click();
  await expect(page.getByText("1 post approved")).toBeVisible();
  await page.getByRole("tab", { name: /Going out/ }).click();
  await expect(page.getByTestId("autopilot-post").first()).toBeVisible();
  // full auto stays locked until the campaign has a clean track record
  await expect(page.getByRole("button", { name: /Full auto/ })).toBeDisabled();
  // phone width: campaign page and the campaign form have no sideways scroll
  await page.setViewportSize({ width: 360, height: 800 });
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(362);
  await page.getByRole("button", { name: "Settings" }).last().click();
  await expect(page.getByText("How much to trust it")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(362);
});

test("Live, Calendar, Analytics and the command palette", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Live agent activity" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Agent network/ })).toBeVisible();
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await page.keyboard.press("Control+k");
  const search = page.getByLabel("Search commands");
  await expect(search).toBeFocused();
  await search.fill("calen");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Drag a scheduled post", { exact: false })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Week" })).toBeVisible();
  // effects can be switched off entirely
  await page.getByRole("button", { name: /Visual effects/ }).click();
  await page.getByRole("button", { name: /Visual effects/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-fx", "off");
  await page.setViewportSize({ width: 360, height: 800 });
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(362);
});

test("Listening, Studio and phone notification settings", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Listening", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Listening" })).toBeVisible();
  await page.getByRole("radio", { name: "hashtag" }).click();
  await page.getByLabel("Keyword, hashtag or account").fill("#BuildInPublic");
  await page.getByRole("button", { name: "Follow", exact: true }).click();
  await expect(page.getByText("BuildInPublic", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "Stop following BuildInPublic" }).click();
  await expect(page.getByText("Start with your brand name")).toBeVisible();

  await page.getByRole("button", { name: "Studio", exact: true }).click();
  await page.getByLabel("Link or text to repurpose").fill("https://example.com/blog/launch-week");
  await page.getByRole("button", { name: "Repurpose with the team" }).click();
  await expect(page.getByLabel("Message")).toHaveValue(/repurpose this content for bluesky, mastodon, linkedin/);

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByText("Telegram: off")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send a test" })).toBeDisabled();
});

test("Library: snippets, CSV import and integrations", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByRole("tab", { name: /Hashtag groups/ }).click();
  await page.getByLabel("Name").fill("Launch");
  await page.getByLabel("Text").fill("launch ShipIt");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("#launch #ShipIt")).toBeVisible();
  await page.getByLabel("CSV file").setInputFiles({ name: "posts.csv", mimeType: "text/csv", buffer: Buffer.from("platform,text\nbluesky,Imported from a spreadsheet #csv\n") });
  await expect(page.getByText("1 imported · 0 scheduled")).toBeVisible();
  await expect(page.getByText("stark.mcp_server")).toBeVisible();
  await page.getByRole("button", { name: "Delete Launch" }).click();
  await expect(page.getByText("#launch #ShipIt")).toBeHidden();
});

test("Automations: recipe gallery, builder, test run and inbound webhook", async ({ page, request }) => {
  await connect(page);
  await page.getByRole("button", { name: "Automations", exact: true }).click();
  await page.getByRole("tab", { name: /Recipe gallery/ }).click();
  await page.getByRole("button", { name: "Use recipe Drafts from other apps" }).click();
  await expect(page.getByText("Drafts from other apps").first()).toBeVisible();
  await page.getByRole("switch", { name: /Switch Drafts from other apps/ }).click();
  await expect(page.getByText("1 on")).toBeVisible();
  const hook = (await page.getByText("/api/hooks/").first().textContent())!.trim();
  const res = await request.post(hook, { data: { platform: "bluesky", text: "Hello from another app" } });
  expect((await res.json()).ok).toBe(true);
  await page.getByRole("tab", { name: /Run history/ }).click();
  await expect(page.getByText(/Create a draft: draft cnt/)).toBeVisible();

  await page.getByRole("tab", { name: /My automations/ }).click();
  await page.getByRole("button", { name: "New automation" }).click();
  await page.getByLabel("Automation name").fill("Praise to thank-you");
  await page.getByLabel("Event").selectOption("mention.found");
  await page.getByRole("button", { name: "Add condition" }).click();
  await page.getByLabel("Condition 1 field").fill("data.category");
  await page.getByLabel("Condition 1 value").fill("praise");
  await page.getByLabel("Action 1", { exact: true }).selectOption("label_mention");
  await page.getByRole("button", { name: "Save automation" }).click();
  await expect(page.getByText("Saved “Praise to thank-you”")).toBeVisible();
  await page.getByRole("button", { name: "Test" }).last().click();
  await page.getByRole("button", { name: "Dry run" }).click();
  await expect(page.getByText("All conditions match: these steps run.")).toBeVisible();
  await page.getByRole("button", { name: "Delete Praise to thank-you" }).click();
  await expect(page.getByRole("button", { name: "Delete Praise to thank-you" })).toBeHidden();
});

test("Compose with preview and score, posting plan, Growth", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Compose", exact: true }).click();
  await page.getByLabel("Post text").fill("Which feature should we build next? #opensource");
  await expect(page.getByText("Which feature should we build next?").last()).toBeVisible(); // preview
  await expect(page.getByText(/General guidance|Compared with your average/)).toBeVisible();
  await page.getByLabel("Who can reply").selectOption("followers");
  await page.getByRole("button", { name: "Add to queue" }).click();
  await expect(page.getByText(/Queued for/)).toBeVisible();
  await page.getByRole("button", { name: "Calendar", exact: true }).click();
  await expect(page.getByText("Posting plan")).toBeVisible();
  await page.getByLabel("New category").fill("Behind the scenes");
  await page.getByRole("button", { name: "Save plan" }).click();
  await expect(page.getByText("Posting plan saved")).toBeVisible();
  await page.getByRole("button", { name: "Growth", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Growth" })).toBeVisible();
  await expect(page.getByText("Bluesky starter pack")).toBeVisible();
});

test("Channels, translation, quote cards, inbox rules and own feeds", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: "Compose", exact: true }).click();
  await page.getByRole("radio", { name: /Telegram/ }).click();
  await page.getByLabel("Post text").fill("Release notes are out https://blog.example.com/v1");
  await page.getByLabel("Tag links for click tracking").check();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Draft saved in Content.")).toBeVisible();
  await page.getByRole("button", { name: "Studio", exact: true }).click();
  await page.getByLabel("Card text").fill("Ship small.\n\nShip often.");
  await expect(page.getByText("1/2")).toBeVisible();
  await page.getByRole("button", { name: "Save 2 slides" }).click();
  await expect(page.getByText("2 image(s) saved to Media.")).toBeVisible();
  await page.getByRole("button", { name: "Listening", exact: true }).click();
  await page.getByLabel("Rule words").fill("refund, money back");
  await page.getByLabel("Rule label").fill("Billing");
  await page.getByRole("button", { name: "Add rule" }).click();
  await expect(page.getByText("Rules saved")).toBeVisible();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByLabel("Feed address").fill("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv");
  await page.getByRole("button", { name: "Add feed" }).click();
  await expect(page.getByText(/channel_id=UCabcdefghijklmnopqrstuv/)).toBeVisible();
});
