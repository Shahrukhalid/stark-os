"use client";

import { useEffect, useState } from "react";
import { StarkClient, type Connection } from "@/lib/api";
import { AgentGlyph } from "./ui";

type Platform = { id: string; name: string; publish: boolean; fields: string[]; how: string };
type Provider = { id: string; name: string; base_url: string; paid: boolean; key_url: string };
type Status = {
  needs_setup: boolean;
  version: string;
  secrets: Record<string, boolean>;
  settings: Record<string, string>;
  platforms: Platform[];
  providers: Provider[];
  labels: Record<string, string>;
  data_dir: string;
};
type Result = { ok: boolean; message: string };

const KEEP = "__keep__"; // "leave the saved value as it is"
const LABELS: Record<string, string> = {
  BLUESKY_HANDLE: "Handle (name.bsky.social)",
  MASTODON_BASE_URL: "Server address (https://…)",
  THREADS_USER_ID: "Threads user ID",
  TELEGRAM_CHAT_ID: "Chat for alerts (optional)",
  TELEGRAM_CHANNEL_ID: "Channel to post in (@name)",
  FACEBOOK_PAGE_ID: "Facebook Page ID",
  INSTAGRAM_USER_ID: "Instagram account ID",
  PINTEREST_BOARD_ID: "Pinterest board ID",
};

/** First-run setup of the desktop app: AI provider and key, social accounts, then the engine restarts with them. */
export function DesktopSetup({ conn, onDone, canSkip }: { conn: Connection; onDone: () => void; canSkip: boolean }) {
  const client = new StarkClient(conn);
  const [st, setSt] = useState<Status | null>(null);
  const [step, setStep] = useState(0);
  const [provider, setProvider] = useState("openrouter-free");
  const [values, setValues] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, Result | "busy">>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    client
      .get<Status>("/api/desktop/status")
      .then((s) => {
        setSt(s);
        const base = s.settings.OPENROUTER_BASE_URL || "";
        setProvider(base && !base.includes("openrouter.ai") ? "custom" : s.settings.OPENROUTER_ALLOW_PAID === "true" ? "openrouter" : "openrouter-free");
        const v: Record<string, string> = { ...s.settings };
        for (const [k, saved] of Object.entries(s.secrets)) if (saved) v[k] = KEEP;
        setValues(v);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!st) return <Frame>{error ? <p className="text-sm text-red-400">{error}</p> : <p className="text-sm text-[var(--color-mute)]">Loading…</p>}</Frame>;

  const prov = st.providers.find((p) => p.id === provider) || st.providers[0];
  const set = (k: string, v: string) => setValues((x) => ({ ...x, [k]: v }));
  const field = (k: string, secret: boolean) => (
    <label key={k} className="block">
      <span className="hud-label text-[var(--color-mute)]">{LABELS[k] || st.labels[k] || k}</span>
      <input
        className={`input mt-1 w-full ${secret ? "font-mono" : ""}`}
        type={secret ? "password" : "text"}
        autoComplete="off"
        placeholder={values[k] === KEEP ? "Saved (type to replace)" : ""}
        value={values[k] === KEEP ? "" : values[k] || ""}
        onChange={(e) => set(k, e.target.value || (st.secrets[k] ? KEEP : ""))}
      />
    </label>
  );
  const isSecret = (k: string) => k in st.labels;

  async function test(id: string, call: () => Promise<Result>) {
    setResults((r) => ({ ...r, [id]: "busy" }));
    try {
      const res = await call();
      setResults((r) => ({ ...r, [id]: res }));
    } catch (e: any) {
      setResults((r) => ({ ...r, [id]: { ok: false, message: String(e?.message || e) } }));
    }
  }

  async function save() {
    setSaving(true);
    setError("");
    const out: Record<string, string> = {
      OPENROUTER_BASE_URL: provider === "custom" ? values.OPENROUTER_BASE_URL || "" : "",
      OPENROUTER_ALLOW_PAID: prov.paid ? "true" : "",
      STARK_TASK_TOKEN_BUDGET: values.STARK_TASK_TOKEN_BUDGET || "",
      OPENROUTER_MODEL: values.OPENROUTER_MODEL || "",
    };
    for (const p of st!.platforms) for (const f of p.fields) out[f] = values[f] ?? "";
    for (const k of ["OPENROUTER_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"]) out[k] = values[k] ?? "";
    try {
      await client.put("/api/desktop/settings", { values: out, restart: true });
      // The engine restarts with the new keys; wait until it answers again.
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const s = await client.get<Status>("/api/desktop/status");
          if (i > 1 && !s.needs_setup) return onDone();
        } catch {
          /* restarting */
        }
      }
      setError("The engine did not come back. Restart STARK OS.");
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }

  const aiKeySet = Boolean(values.OPENROUTER_API_KEY);
  const Res = ({ id }: { id: string }) => {
    const r = results[id];
    if (!r) return null;
    if (r === "busy") return <span className="text-sm text-[var(--color-mute)]">Checking…</span>;
    return <span className={`text-sm ${r.ok ? "text-emerald-400" : "text-red-400"}`}>{r.message}</span>;
  };

  return (
    <Frame>
      <ol className="mb-6 flex gap-2 text-xs" aria-label="Setup steps">
        {["AI model", "Social accounts", "Finish"].map((s, i) => (
          <li key={s} className={`rounded-full px-3 py-1 ${i === step ? "bg-cyan-500/20 text-cyan-300" : "text-[var(--color-mute)]"}`}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <div className="space-y-4">
          <p className="text-sm text-[var(--color-mute)]">
            Choose where STARK OS gets its AI. Free models cost nothing; paid models are only used if you allow them below.
          </p>
          <div className="grid gap-2" role="radiogroup" aria-label="AI provider">
            {st.providers.map((p) => (
              <label key={p.id} className={`panel flex cursor-pointer items-center gap-3 p-3 ${provider === p.id ? "ring-1 ring-cyan-400" : ""}`}>
                <input type="radio" name="provider" checked={provider === p.id} onChange={() => setProvider(p.id)} />
                <span className="text-sm">{p.name}</span>
              </label>
            ))}
          </div>
          {provider === "custom" && field("OPENROUTER_BASE_URL", false)}
          {field("OPENROUTER_API_KEY", true)}
          {prov.key_url && (
            <p className="text-xs text-[var(--color-mute)]">
              No key yet? Create one for free at <span className="font-mono">{prov.key_url}</span>
            </p>
          )}
          {prov.paid && (
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Spending limit: most tokens one task may use</span>
              <input className="input mt-1 w-full" type="number" min={10000} step={10000} placeholder="200000"
                value={values.STARK_TASK_TOKEN_BUDGET || ""} onChange={(e) => set("STARK_TASK_TOKEN_BUDGET", e.target.value)} />
            </label>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" className="btn" disabled={!aiKeySet}
              onClick={() => test("ai", () => client.post("/api/desktop/test-ai", {
                api_key: values.OPENROUTER_API_KEY === KEEP ? "" : values.OPENROUTER_API_KEY,
                base_url: provider === "custom" ? values.OPENROUTER_BASE_URL : prov.base_url,
              }))}>
              Test connection
            </button>
            <Res id="ai" />
          </div>
          <Nav next={() => setStep(1)} nextOk={aiKeySet} skip={canSkip ? onDone : undefined} />
        </div>
      )}

      {step === 1 && (
        <div className="space-y-3">
          <p className="text-sm text-[var(--color-mute)]">
            Connect the accounts STARK OS may post to. Every post still waits for your approval. You can add more later.
          </p>
          {st.platforms.map((p) => (
            <details key={p.id} className="panel p-3" open={p.fields.some((f) => values[f])}>
              <summary className="flex cursor-pointer items-center justify-between text-sm">
                <span>{p.name}</span>
                <span className={`text-xs ${p.publish ? "text-[var(--color-mute)]" : "text-amber-400"}`}>
                  {p.publish ? (p.fields.some((f) => values[f]) ? "Connected" : "Not connected") : "Drafts only"}
                </span>
              </summary>
              <p className="mt-2 text-xs text-[var(--color-mute)]">{p.how}</p>
              {p.fields.length > 0 && (
                <div className="mt-3 space-y-2">
                  {p.fields.map((f) => field(f, isSecret(f)))}
                  <div className="flex flex-wrap items-center gap-3">
                    <button type="button" className="btn"
                      onClick={() => test(p.id, () => client.post("/api/desktop/test-social", {
                        platform: p.id, values: Object.fromEntries(p.fields.map((f) => [f, values[f] || ""])),
                      }))}>
                      Test
                    </button>
                    <Res id={p.id} />
                  </div>
                </div>
              )}
            </details>
          ))}
          <Nav back={() => setStep(0)} next={() => setStep(2)} nextOk />
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <p className="text-sm">STARK OS keeps your keys in this computer&apos;s secure credential store, not in files.</p>
          <p className="text-xs text-[var(--color-mute)]">Your data folder: <span className="font-mono">{st.data_dir}</span></p>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <Nav back={() => setStep(1)} next={save} nextOk={!saving} nextLabel={saving ? "Starting STARK OS…" : "Save and start"} />
        </div>
      )}
    </Frame>
  );
}

function Nav({ back, next, nextOk, nextLabel = "Next", skip }: { back?: () => void; next: () => void; nextOk: boolean; nextLabel?: string; skip?: () => void }) {
  return (
    <div className="flex items-center justify-between pt-2">
      <div className="flex gap-2">
        {back && <button type="button" className="btn" onClick={back}>Back</button>}
        {skip && <button type="button" className="btn" onClick={skip}>Close</button>}
      </div>
      <button type="button" className="btn btn-primary" disabled={!nextOk} onClick={next}>{nextLabel}</button>
    </div>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid-bg flex min-h-screen items-center justify-center p-4">
      <div className="panel w-full max-w-xl p-8">
        <div className="mb-6 flex items-center gap-3">
          <AgentGlyph icon="core" color="#22d3ee" size={40} />
          <div>
            <h1 className="text-xl font-semibold tracking-[0.25em]">STARK OS</h1>
            <p className="hud-label text-[var(--color-mute)]">Setup</p>
          </div>
        </div>
        {children}
      </div>
    </main>
  );
}
