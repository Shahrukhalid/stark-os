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
  await expect(page.getByText("Live", { exact: true })).toBeVisible({ timeout: 15_000 });
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
  for (const view of ["Start", "Command", "Content", "Agents", "Tasks", "Approvals", "Memory", "Models", "Tools", "Activity", "Settings"]) {
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
