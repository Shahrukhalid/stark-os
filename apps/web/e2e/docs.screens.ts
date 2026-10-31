/**
 * Generates the README screenshots with realistic sample content on a fresh database.
 * Run: npm run screenshots   (not part of the regular test suite)
 */
import { expect, test, type Page } from "@playwright/test";

const TOKEN = "e2e-token-0123456789abcdefghijkl";
async function shot(page: Page, name: string) {
  const dismiss = page.getByRole("button", { name: "Dismiss" });
  while (await dismiss.count()) await dismiss.first().click(); // no toasts in the README images
  await page.waitForTimeout(1000); // let the tab's boot-up animation finish
  await page.screenshot({ path: `../../docs/screenshots/${name}.png`, fullPage: true });
}

async function send(page: Page, text: string) {
  await page.getByLabel("Message").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test("README screenshots", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.locator("#stark-api-url").fill("http://127.0.0.1:8200");
  await page.getByPlaceholder("STARK_API_TOKEN from your .env").fill(TOKEN);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Your AI social media team")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "Command", exact: true }).click();
  for (const p of ["LinkedIn", "Mastodon", "Bluesky"]) {
    await send(page, `EDITH, write a ${p} post about our launch week`);
    await expect(page.getByText(new RegExp(`Here's a ${p} draft`))).toBeVisible({ timeout: 20_000 });
  }
  await send(page, "Friday, check our mentions and draft replies");
  await expect(page.getByText(/SIMULATED sample inbox/).last()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(500);
  await shot(page, "command");

  // Content: schedule one for tomorrow with auto-publish, simulate one, keep one as a draft
  await page.getByRole("button", { name: "Content", exact: true }).click();
  const cards = page.getByTestId("content-item");
  await expect(cards).toHaveCount(3);
  const linkedin = cards.filter({ hasText: "Three things we learned" });
  await linkedin.getByRole("button", { name: "Schedule" }).click();
  const t = new Date(Date.now() + 24 * 3600_000);
  t.setHours(9, 30, 0, 0);
  await linkedin.getByLabel("Publish date and time").fill(new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 16));
  await linkedin.getByRole("button", { name: "Save schedule" }).click();
  await expect(linkedin.getByText("auto-publish approved")).toBeVisible();
  const masto = cards.filter({ hasText: "Behind the scenes" });
  await masto.getByRole("button", { name: "Publish (simulation)" }).click();
  await masto.getByRole("button", { name: "Run simulation" }).click();
  await expect(masto.getByText("SIMULATED", { exact: true })).toBeVisible();
  const bsky = cards.filter({ hasText: "New video is up" });
  await bsky.getByRole("button", { name: "Publish (simulation)" }).click(); // show the confirm step
  await page.waitForTimeout(400);
  await shot(page, "content");
  await bsky.getByRole("button", { name: "Cancel" }).click();

  // Approval card: D.U.M.-E. asks before publishing from chat
  const id = (await bsky.innerText()).match(/cnt_[0-9a-f]{16}/)![0];
  await page.getByRole("button", { name: "Command", exact: true }).click();
  await send(page, `DUM-E, publish ${id}`);
  await expect(page.getByRole("button", { name: "Approve once" })).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(400);
  await shot(page, "approval");
  await page.getByRole("button", { name: "Approve once" }).click();
  await expect(page.getByText(/whirr\s+SIMULATED publish/).last()).toBeVisible({ timeout: 20_000 });

  // Team review: parallel reviews + Ultron's challenge, shown in Tasks
  await send(page, "JARVIS, ask the whole team to review our launch week plan");
  await expect(page.getByText(/Team review complete/).last()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "trace" }).last().click();
  await expect(page.getByText(/Agent messages \(\d+\)/)).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "collaboration");

  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.getByText(/Setup · \d\/4/)).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "start");

  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await expect(page.getByRole("heading", { name: "ULTRON", exact: true })).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "agents");

  await page.getByRole("button", { name: "Models", exact: true }).click();
  await expect(page.getByText(/free requests left today/)).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "models");
  // Live, Calendar and Analytics. Analytics needs real engagement from Bluesky/Mastodon, which a test database
  // does not have, so that one screenshot uses clearly fictional sample numbers (README says so).
  await page.getByRole("button", { name: "Live", exact: true }).click();
  await send2(page);
  await page.waitForTimeout(1500);
  await shot(page, "live");

  await page.getByRole("button", { name: "Calendar", exact: true }).click();
  await expect(page.getByText("Drag a scheduled post", { exact: false })).toBeVisible();
  await shot(page, "calendar");

  await page.route("**/api/social/analytics*", (r) => r.fulfill({ json: sampleAnalytics() }));
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(page.getByText("Best slot so far")).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "analytics");
});

/** Starts a team review over the API so the Live view has something to show. */
async function send2(page: Page) {
  await page.evaluate(async (token) => {
    await fetch("http://127.0.0.1:8200/api/chat", { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${token}` }, body: JSON.stringify({ message: "EDITH, write a Mastodon post about our launch week" }) });
  }, TOKEN);
}

function sampleAnalytics() {
  const now = Date.now();
  const texts = ["Launch week recap: three things we learned shipping in public.", "Behind the scenes of our editing workflow.", "New video is up: how seven agents plan a week of posts."];
  const posts = Array.from({ length: 26 }, (_, i) => {
    const likes = Math.round(4 + 30 * Math.abs(Math.sin(i * 1.7)));
    const reposts = Math.round(likes / 4);
    const replies = Math.round(likes / 6);
    return { id: `sample${i}`, platform: i % 3 ? "bluesky" : "mastodon", kind: "post", text: texts[i % 3], url: null, campaign: "", simulated: false,
      published_at: new Date(now - i * 26 * 3600e3 - (i % 5) * 3600e3).toISOString(), engagement: { likes, reposts, replies, quotes: 0 }, score: likes + 2 * (reposts + replies) };
  });
  const totals = posts.reduce((t, p) => ({ likes: t.likes + p.engagement.likes, reposts: t.reposts + p.engagement.reposts, replies: t.replies + p.engagement.replies, quotes: 0 }), { likes: 0, reposts: 0, replies: 0, quotes: 0 });
  return { counts: { bluesky: { published: 17, scheduled: 3, draft: 4 }, mastodon: { published: 9, draft: 2, failed: 1 } }, posts, totals, measured: posts.length, errors: [], fetched_at: new Date().toISOString() };
}
