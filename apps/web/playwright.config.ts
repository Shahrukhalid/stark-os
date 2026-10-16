import { defineConfig } from "@playwright/test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

/**
 * End-to-end: real dashboard (next start) + real API (uvicorn) + a TEST-ONLY scripted model
 * server speaking the OpenRouter (OpenAI-compatible) protocol. Run `npm run build` first.
 * Python: set STARK_PYTHON (default: ../../services/api/.venv/bin/python).
 */
const TOKEN = "e2e-token-0123456789abcdefghijkl";
const work = process.env.STARK_E2E_DIR || mkdtempSync(path.join(tmpdir(), "stark-e2e-"));
const sandbox = path.join(work, "sandbox");
mkdirSync(path.join(sandbox, "test-folder"), { recursive: true });
for (const f of ["notes.md", "photo.jpg", "budget.csv"]) writeFileSync(path.join(sandbox, "test-folder", f), "x");
process.env.STARK_E2E_DIR = work;

const py = process.env.STARK_PYTHON || path.resolve(__dirname, "../../services/api/.venv/bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:3100", screenshot: "only-on-failure", viewport: { width: 1440, height: 950 } },
  webServer: [
    { command: `${py} e2e/mock_llm.py 8799`, url: "http://127.0.0.1:8799/api/v1/models", reuseExistingServer: false },
    {
      command: `${py} -m uvicorn stark.main:create_app --factory --host 127.0.0.1 --port 8100 --no-access-log`,
      cwd: path.resolve(__dirname, "../../services/api"),
      url: "http://127.0.0.1:8100/api/health",
      reuseExistingServer: false,
      env: {
        STARK_API_TOKEN: TOKEN,
        STARK_WEB_ORIGIN: "http://127.0.0.1:3100",
        DATABASE_URL: `sqlite:///${path.join(work, "e2e.db")}`,
        STARK_DATA_DIR: path.join(work, "data"),
        STARK_WORKSPACE_ROOTS: sandbox,
        OPENROUTER_API_KEY: "e2e-test-key-not-real",
        OPENROUTER_BASE_URL: "http://127.0.0.1:8799/api/v1",
      },
    },
    { command: "npx next start -p 3100 -H 127.0.0.1", url: "http://127.0.0.1:3100", reuseExistingServer: false, env: { NEXT_PUBLIC_STARK_API_URL: "http://127.0.0.1:8100" } },
  ],
});

export { TOKEN };
