/**
 * Records the README demo animation (docs/demo.gif). Run: npm run demo-gif
 * Not part of the regular test suite.
 */
import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const TOKEN = "e2e-token-0123456789abcdefghijkl";
const OUT = "../../docs/demo-raw";

test("README demo video", async ({ browser }) => {
  test.setTimeout(120_000);
  mkdirSync(OUT, { recursive: true });
  const size = { width: 1440, height: 900 };
  const ctx = await browser.newContext({ viewport: size, colorScheme: "dark" });
  // "Calm" effects keep the GIF small: the moving particle background changes every pixel of every frame.
  await ctx.addInitScript(() => localStorage.setItem("stark-fx", "calm"));
  const page = await ctx.newPage();
  // Chrome screencast frames + timestamps; ffmpeg turns them into the GIF.
  const cdp = await ctx.newCDPSession(page);
  const frames: { file: string; t: number }[] = [];
  cdp.on("Page.screencastFrame", async (f) => {
    const file = `f${String(frames.length).padStart(5, "0")}.jpg`;
    writeFileSync(`${OUT}/${file}`, Buffer.from(f.data, "base64"));
    frames.push({ file, t: f.metadata.timestamp ?? Date.now() / 1000 });
    await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  const pause = (ms: number) => page.waitForTimeout(ms);
  await page.goto("/");
  await page.locator("#stark-api-url").fill("http://127.0.0.1:8200");
  await page.getByPlaceholder("STARK_API_TOKEN from your .env").fill(TOKEN);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Your AI social media team")).toBeVisible({ timeout: 15_000 });
  await pause(300); // recording starts after sign-in
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: size.width, maxHeight: size.height, everyNthFrame: 1 });
  await pause(1800);

  await page.getByRole("button", { name: "Command", exact: true }).click();
  await pause(500);
  const box = page.getByLabel("Message");
  await box.click();
  await box.pressSequentially("EDITH, write a Bluesky post about our launch week", { delay: 35 });
  await pause(400);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/Here's a Bluesky draft/)).toBeVisible({ timeout: 20_000 });
  await pause(2200);

  await page.getByRole("button", { name: "Content", exact: true }).click();
  const card = page.getByTestId("content-item").first();
  await expect(card).toBeVisible();
  await pause(1500);
  await card.getByRole("button", { name: "Publish (simulation)" }).click();
  await pause(1500);
  await card.getByRole("button", { name: "Run simulation" }).click();
  await expect(card.getByText("SIMULATED", { exact: true })).toBeVisible();
  await pause(1800);

  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Live agent activity" })).toBeVisible();
  await pause(2800);

  await page.getByRole("button", { name: "Calendar", exact: true }).click();
  await expect(page.getByText("Drag a scheduled post", { exact: false })).toBeVisible();
  await pause(2200);

  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await expect(page.getByRole("heading", { name: "ULTRON", exact: true })).toBeVisible();
  await pause(2500);

  await cdp.send("Page.stopScreencast");
  await ctx.close();
  // ffmpeg concat list with each frame's real duration
  const lines = frames.map((f, i) => `file '${f.file}'\nduration ${Math.max(0.02, ((frames[i + 1]?.t ?? f.t + 1) - f.t)).toFixed(3)}`);
  writeFileSync(`${OUT}/frames.txt`, lines.join("\n") + `\nfile '${frames.at(-1)!.file}'\n`);
});
