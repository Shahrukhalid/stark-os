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
  await page.getByRole("button", { name: "Agents" }).click();
  for (const name of ["J.A.R.V.I.S.", "F.R.I.D.A.Y.", "E.D.I.T.H.", "ULTRON", "JOCASTA", "D.U.M.-E.", "U"]) {
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await page.screenshot({ path: "e2e/screenshots/agents.png", fullPage: true });
});

test("EDITH drafts, DUM-E publishes only after approval, and the simulation is labelled", async ({ page }) => {
  await connect(page);
  await send(page, "EDITH, draft a launch post for Bluesky");
  const drafted = page.getByText(/Drafted (cnt_[0-9a-f]{16}) for Bluesky\. Check: PASS\./);
  await expect(drafted).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Content" }).click();
  const item = page.getByTestId("content-item").first();
  await expect(item.getByText("STARK OS is live: seven agents, one social team.", { exact: false })).toBeVisible();
  await expect(item.getByText("check PASS")).toBeVisible();
  await expect(page.getByText("No account connected: every publish is a SIMULATION.", { exact: false })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/content.png", fullPage: true });
  await item.getByRole("button", { name: "Ask D.U.M.-E. to publish" }).click();
  await page.getByRole("button", { name: "Send" }).click();
  const approve = page.getByRole("button", { name: "Approve once" });
  await expect(approve).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/SIMULATION ONLY - nothing will be sent to Bluesky/).first()).toBeVisible();
  await approve.click();
  await expect(page.getByText(/whirr\* SIMULATED publish to Bluesky: nothing was sent/)).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Content" }).click();
  await expect(page.getByTestId("content-item").first().getByText("SIMULATED")).toBeVisible();
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
  await page.getByRole("button", { name: "Diagnostics" }).click();
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
  await page.getByRole("button", { name: "Models" }).click();
  await expect(page.getByText("mock/free-tools:free").first()).toBeVisible();
  await expect(page.getByText(/49 of 50 free requests left today/)).toBeVisible();
  await page.getByRole("button", { name: "Ping", exact: true }).first().click();
  await expect(page.getByText(/ok · \d+ms · tool call/)).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: "e2e/screenshots/models.png", fullPage: true });
});
