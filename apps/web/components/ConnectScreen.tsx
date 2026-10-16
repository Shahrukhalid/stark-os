"use client";

import { useState } from "react";
import { StarkClient, type Connection } from "@/lib/api";
import { AgentGlyph } from "./ui";

export function ConnectScreen({ onConnect }: { onConnect: (c: Connection) => void }) {
  const [url, setUrl] = useState(process.env.NEXT_PUBLIC_STARK_API_URL || "http://127.0.0.1:8000");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [remember, setRemember] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const conn = { url: url.trim(), token: token.trim(), remember };
    try {
      await new StarkClient(conn).get("/api/system/status");
      onConnect(conn);
    } catch (err: any) {
      setError(err?.status === 401 ? "Token rejected by the API." : `Cannot reach the API at ${conn.url}. Is it running? (${err?.message || err})`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid-bg flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="panel w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="anim-spin">
            <AgentGlyph icon="core" color="#22d3ee" size={44} />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-[0.25em]">STARK OS</h1>
            <p className="hud-label text-[var(--color-mute)]">Project Genesis · secure link</p>
          </div>
        </div>
        <label htmlFor="stark-api-url" className="hud-label mb-1 block text-[var(--color-mute)]">API address</label>
        <input id="stark-api-url" className="input mb-4" value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="url" />
        <label htmlFor="stark-api-token" className="hud-label mb-1 block text-[var(--color-mute)]">Access token</label>
        <input
          id="stark-api-token"
          className="input mb-2 font-mono"
          autoComplete="off"
          type="password"
          placeholder="STARK_API_TOKEN from your .env"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoFocus
        />
        <p className="mb-5 text-xs text-[var(--color-mute)]">
          Run <code className="font-mono">python3 scripts/setup.py</code> to generate one.
        </p>
        <label className="mb-5 flex items-center gap-2 text-xs text-[var(--color-mute)]">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember on this device (otherwise the token is forgotten when you close the tab)
        </label>
        {error && <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">{error}</p>}
        <button className="btn btn-primary w-full justify-center" disabled={!token || busy}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </form>
    </main>
  );
}
