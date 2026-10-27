/** Fresh API + dashboard on separate ports, used only to regenerate the README screenshots. */
import { defineConfig } from "@playwright/test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const TOKEN = "e2e-token-0123456789abcdefghijkl";
const work = mkdtempSync(path.join(tmpdir(), "stark-docs-"));
const sandbox = path.join(work, "sandbox");
mkdirSync(sandbox, { recursive: true });
writeFileSync(path.join(sandbox, "brand-guidelines.md"), "# Brand\nFriendly, short, no slang.\n");
// the venv made by `make setup` / scripts\setup.ps1 (Windows keeps it in Scripts\python.exe); quoted for paths with spaces
const venvPython = process.platform === "win32" ? "../../services/api/.venv/Scripts/python.exe" : "../../services/api/.venv/bin/python";
const py = `"${process.env.STARK_PYTHON || path.resolve(__dirname, venvPython)}"`;

export default defineConfig({
  testDir: "e2e",
  testMatch: process.env.STARK_DEMO ? "demo.screens.ts" : "docs.screens.ts",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3200",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: [
    { command: `${py} e2e/mock_llm.py 8798`, url: "http://127.0.0.1:8798/api/v1/models", reuseExistingServer: false },
    {
      command: `${py} -m uvicorn stark.main:create_app --factory --host 127.0.0.1 --port 8200 --no-access-log`,
      cwd: path.resolve(__dirname, "../../services/api"),
      url: "http://127.0.0.1:8200/api/health",
      reuseExistingServer: false,
      env: {
        STARK_API_TOKEN: TOKEN,
        STARK_WEB_ORIGIN: "http://127.0.0.1:3200",
        DATABASE_URL: `sqlite:///${path.join(work, "docs.db")}`,
        STARK_DATA_DIR: path.join(work, "data"),
        STARK_WORKSPACE_ROOTS: sandbox,
        OPENROUTER_API_KEY: "docs-key-not-real",
        OPENROUTER_BASE_URL: "http://127.0.0.1:8798/api/v1",
      },
    },
    { command: "npx next start -p 3200 -H 127.0.0.1", url: "http://127.0.0.1:3200", reuseExistingServer: false, env: { NEXT_PUBLIC_STARK_API_URL: "http://127.0.0.1:8200" } },
  ],
});
