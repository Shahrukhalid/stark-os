"use client";

import { CalendarClock, Check, Copy, ExternalLink, Link2, PauseCircle, PlayCircle, RefreshCw, Send, Sparkles, Trash2, Unlink, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStark } from "@/lib/store";
import type { ContentItem, SocialAccount } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

const STATUSES = ["all", "draft", "scheduled", "published", "failed", "rejected"] as const;

const VERDICT: Record<string, string> = {
  pass: "!text-emerald-300",
  warn: "!text-amber-300",
  fail: "!text-red-300",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  scheduled: "Scheduled",
  publishing: "Publishing…",
  published: "Published",
  failed: "Failed",
  rejected: "Discarded",
};

/** local "YYYY-MM-DDTHH:mm" for a datetime-local input, one hour from now */
function inAnHour(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setSeconds(0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** The content queue: everything your agents drafted. You publish, schedule or discard from here. */
export function ContentView({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify, events } = useStark();
  const [items, setItems] = useState<ContentItem[]>([]);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [paused, setPaused] = useState(false);
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");

  const reqId = useRef(0);
  const load = useCallback(async () => {
    const id = ++reqId.current;
    try {
      const [q, a] = await Promise.all([
        client.get<{ items: ContentItem[]; paused: boolean }>(`/api/social/queue?status=${status}`),
        client.get<{ accounts: SocialAccount[] }>("/api/social/accounts"),
      ]);
      if (id !== reqId.current) return;
      setItems(q.items);
      setPaused(q.paused);
      setAccounts(a.accounts);
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, notify, status]);

  const contentEvents = useMemo(() => events.filter((e) => e.type.startsWith("content.")).length, [events]);
  useEffect(() => {
    load();
  }, [load, contentEvents]);

  const byPlatform = useMemo(() => Object.fromEntries(accounts.map((a) => [a.platform, a])), [accounts]);

  async function resume() {
    try {
      await client.post("/api/social/queue/pause?paused=false");
      notify("success", "Queue resumed. Approved posts will go out at their times again.");
      load();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_360px]">
      <div className="space-y-4">
        {paused && (
          <div className="panel flex flex-wrap items-center gap-3 !border-red-400/50 p-3 text-sm" role="status">
            <PauseCircle size={16} className="text-red-300" />
            <span className="min-w-0 flex-1">The queue is paused (emergency stop or fire suppression). Nothing will be published until you resume it.</span>
            <button className="btn" onClick={resume}>
              <PlayCircle size={14} /> Resume
            </button>
          </div>
        )}
        <Section
          title="Your posts"
          right={
            <div className="flex items-center gap-2">
              <select className="input !w-auto !py-1 text-xs" value={status} onChange={(e) => setStatus(e.target.value as any)} aria-label="Filter by status">
                {STATUSES.map((s) => <option key={s} value={s}>{s === "all" ? "All posts" : STATUS_LABEL[s]}</option>)}
              </select>
              <button className="btn" onClick={load} title="Refresh" aria-label="Refresh posts"><RefreshCw size={14} /></button>
            </div>
          }
        >
          {!items.length ? (
            <Empty>
              No posts yet. Go to <b>Command</b> and try: &ldquo;EDITH, draft a post for Bluesky about our launch&rdquo;.
              <div className="mt-3">
                <button className="btn btn-primary" onClick={() => talkTo("edith", "EDITH, draft a friendly post for Bluesky introducing what I do")}>
                  <Sparkles size={14} /> Draft my first post
                </button>
              </div>
            </Empty>
          ) : (
            <ul className="space-y-3">
              {items.map((it) => (
                <PostCard key={it.id} item={it} account={byPlatform[it.platform]} onChange={load} talkTo={talkTo} />
              ))}
            </ul>
          )}
        </Section>
      </div>
      <AccountsPanel accounts={accounts} onChange={setAccounts} />
    </div>
  );
}

function PostCard({ item: it, account, onChange, talkTo }: { item: ContentItem; account?: SocialAccount; onChange: () => void; talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [mode, setMode] = useState<"none" | "publish" | "schedule">("none");
  const [when, setWhen] = useState(inAnHour);
  const [auto, setAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const live = account?.mode === "connected";
  const editable = ["draft", "scheduled", "failed"].includes(it.status);
  const failing = it.check?.verdict === "fail";
  const fullText = [it.text, ...(it.thread || [])].join("\n\n");

  async function act(fn: () => Promise<any>, ok?: string) {
    setBusy(true);
    try {
      const res = await fn();
      if (res && res.ok === false) notify("error", res.summary || "Not published");
      else if (ok) notify("success", typeof ok === "string" ? ok : "Done");
      setMode("none");
      onChange();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(fullText);
      notify("success", "Copied. Paste it into the app to post it yourself.");
    } catch {
      notify("warn", "Couldn't copy automatically: select the text and copy it.");
    }
  }

  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-black/20 p-3" data-testid="content-item">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="chip">{account?.name || it.platform}</span>
        <span className="chip">{STATUS_LABEL[it.status] || it.status}</span>
        {it.check?.verdict && <span className={`chip ${VERDICT[it.check.verdict] || ""}`}>check {it.check.verdict.toUpperCase()}</span>}
        {it.review?.verdict && <span className="chip">J.A.R.V.I.S.: {it.review.verdict}</span>}
        {it.simulated && <span className="chip !text-amber-300">{it.status === "published" ? "SIMULATED" : "simulated platform"}</span>}
        {it.auto_publish && it.status === "scheduled" && <span className="chip !text-emerald-300">auto-publish approved</span>}
        {it.paused && <span className="chip !text-red-300"><PauseCircle size={12} className="mr-1 inline" />paused</span>}
        {it.due && <span className="chip !text-cyan-300">due now</span>}
        <span className="break-anywhere ml-auto font-mono text-[var(--color-mute)]">{it.id} · by {it.created_by}</span>
      </div>
      <p className="break-anywhere whitespace-pre-wrap text-sm">{it.text}</p>
      {it.thread?.map((p, i) => (
        <p key={i} className="break-anywhere mt-1 border-l-2 border-[var(--color-line)] pl-2 text-sm text-[var(--color-mute)]">{p}</p>
      ))}
      {it.media?.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-[var(--color-mute)]">
          {it.media.map((m, i) => <li key={i}>Media brief: {m.description}{m.alt_text ? ` (alt: ${m.alt_text})` : " (no alt text)"}</li>)}
        </ul>
      )}
      {it.check?.issues?.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {it.check.issues.map((iss, i) => (
            <li key={i} className={iss.level === "fail" ? "text-red-300" : "text-amber-200"}>{iss.level.toUpperCase()} · {iss.message}</li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
        {it.scheduled_for && <span>{it.status === "scheduled" ? "goes out" : "was scheduled"} {new Date(it.scheduled_for).toLocaleString()} ({timeAgo(it.scheduled_for)})</span>}
        {it.error && <span className="text-red-300">{it.error}</span>}
        {it.external_url && /^https?:\/\//i.test(it.external_url) && (
          <a className="inline-flex items-center gap-1 text-cyan-300 hover:underline" href={it.external_url} target="_blank" rel="noreferrer noopener">
            view post <ExternalLink size={12} />
          </a>
        )}
      </div>

      {editable && mode === "none" && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn btn-primary !py-1 text-xs" disabled={busy || failing} onClick={() => setMode("publish")} title={failing ? "Fix the failing check first" : ""}>
            <Send size={13} /> {live ? "Publish now" : "Publish (simulation)"}
          </button>
          <button className="btn !py-1 text-xs" disabled={busy || failing} onClick={() => setMode("schedule")}>
            <CalendarClock size={13} /> Schedule
          </button>
          <button className="btn !py-1 text-xs" onClick={copy}>
            <Copy size={13} /> Copy text
          </button>
          <button className="btn !py-1 text-xs" onClick={() => talkTo("edith", `EDITH, improve ${it.id}: `)}>
            <Sparkles size={13} /> Ask E.D.I.T.H. to improve
          </button>
          {it.status === "scheduled" && (
            <button className="btn !py-1 text-xs" disabled={busy} onClick={() => act(() => client.post(`/api/social/items/${it.id}/unschedule`), "Back to drafts")}>
              <X size={13} /> Unschedule
            </button>
          )}
          <button className="btn btn-danger !py-1 text-xs" disabled={busy} onClick={() => act(() => client.post(`/api/social/items/${it.id}/discard`), "Discarded")}>
            <Trash2 size={13} /> Discard
          </button>
        </div>
      )}

      {mode === "publish" && (
        <div className="mt-3 rounded-lg border border-cyan-400/30 bg-cyan-400/5 p-3 text-sm">
          <p className="mb-2">
            {live ? (
              <>This will post the text above <b>publicly</b> to {account?.name}{account?.connected_as ? ` as ${account.connected_as}` : ""}. Posts are hard to take back once people have seen them.</>
            ) : (
              <>{account?.name} isn&apos;t connected, so this is a <b>simulation</b>: nothing is sent. Use <b>Copy text</b> to post it yourself.</>
            )}
          </p>
          <div className="flex gap-2">
            <button
              className="btn btn-primary"
              disabled={busy}
              onClick={() => act(() => client.post(`/api/social/items/${it.id}/publish`, { fingerprint: it.fingerprint }), live ? "Published" : "Simulated publish recorded")}
            >
              <Check size={14} /> {live ? "Yes, publish" : "Run simulation"}
            </button>
            <button className="btn" onClick={() => setMode("none")}>Cancel</button>
          </div>
        </div>
      )}

      {mode === "schedule" && (
        <div className="mt-3 rounded-lg border border-cyan-400/30 bg-cyan-400/5 p-3 text-sm">
          <label className="mb-2 block">
            <span className="hud-label mb-1 block text-[var(--color-mute)]">When</span>
            <input className="input !w-auto" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} aria-label="Publish date and time" />
          </label>
          <label className="mb-3 flex items-start gap-2 text-xs">
            <input type="checkbox" className="mt-0.5" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            <span>
              <b>Publish automatically at this time.</b> I approve this exact text. If anyone changes it, it won&apos;t go out until I approve it again.
              Leave unticked to just put it on the calendar. STARK OS must be running at that time.
            </span>
          </label>
          <div className="flex gap-2">
            <button
              className="btn btn-primary"
              disabled={busy || !when}
              onClick={() =>
                act(
                  () => client.post(`/api/social/items/${it.id}/schedule`, { fingerprint: it.fingerprint, when: new Date(when).toISOString(), auto }),
                  auto ? "Scheduled: it will go out automatically" : "Added to the calendar",
                )
              }
            >
              <CalendarClock size={14} /> Save schedule
            </button>
            <button className="btn" onClick={() => setMode("none")}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}

const HELP: Record<string, { steps: string[]; link: string }> = {
  bluesky: {
    steps: [
      "Open bsky.app and sign in.",
      "Go to Settings → Privacy and security → App passwords → Add App Password.",
      "Name it “STARK OS”, then copy the password it shows (xxxx-xxxx-xxxx-xxxx).",
    ],
    link: "https://bsky.app/settings/app-passwords",
  },
  mastodon: {
    steps: [
      "On your Mastodon server, open Preferences → Development → New application.",
      "Name it “STARK OS”, keep only the read and write:statuses scopes, and save.",
      "Open the app you created and copy “Your access token”.",
    ],
    link: "",
  },
};

function AccountsPanel({ accounts, onChange }: { accounts: SocialAccount[]; onChange: (a: SocialAccount[]) => void }) {
  const { client, notify } = useStark();
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState({ a: "", b: "" });
  const [busy, setBusy] = useState(false);
  const live = accounts.filter((a) => a.can_connect);
  const others = accounts.filter((a) => !a.can_connect);

  async function connect(platform: string) {
    setBusy(true);
    try {
      const body = platform === "bluesky" ? { handle: form.a, app_password: form.b } : { base_url: form.a, access_token: form.b };
      const res = await client.post<{ connected_as: string; accounts: SocialAccount[] }>(`/api/social/accounts/${platform}`, body);
      onChange(res.accounts);
      notify("success", `Connected as ${res.connected_as}`);
      setOpen(null);
      setForm({ a: "", b: "" });
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(platform: string) {
    try {
      const res = await client.del<{ accounts: SocialAccount[] }>(`/api/social/accounts/${platform}`);
      onChange(res.accounts);
      notify("success", "Disconnected");
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  return (
    <Section title="Your accounts">
      <p className="mb-3 text-xs text-[var(--color-mute)]">
        Logins stay on this computer (never uploaded, never shown again). Nothing is posted without your click or your approval.
      </p>
      <ul className="space-y-3">
        {live.map((a) => (
          <li key={a.platform} className="rounded-lg border border-[var(--color-line)] p-3 text-sm">
            <div className="flex items-center gap-2">
              <span className={`chip ${a.mode === "connected" ? "!text-emerald-300" : "!text-amber-300"}`}>{a.mode === "connected" ? "LIVE" : "NOT CONNECTED"}</span>
              <span className="font-medium">{a.name}</span>
            </div>
            {a.mode === "connected" ? (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                <span className="break-anywhere">Connected as <b className="text-[var(--color-ink)]">{a.connected_as}</b></span>
                {a.source === "dashboard" ? (
                  <button className="btn ml-auto !py-0.5 text-xs" onClick={() => disconnect(a.platform)}>
                    <Unlink size={12} /> Disconnect
                  </button>
                ) : (
                  <span className="ml-auto">set in .env</span>
                )}
              </div>
            ) : open === a.platform ? (
              <form
                className="mt-2 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  connect(a.platform);
                }}
              >
                <ol className="list-decimal space-y-0.5 pl-4 text-xs text-[var(--color-mute)]">
                  {HELP[a.platform].steps.map((s) => <li key={s}>{s}</li>)}
                </ol>
                {HELP[a.platform].link && (
                  <a className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" href={HELP[a.platform].link} target="_blank" rel="noreferrer noopener">
                    Open app passwords <ExternalLink size={11} />
                  </a>
                )}
                <input
                  className="input"
                  aria-label={a.platform === "bluesky" ? "Bluesky handle" : "Mastodon server address"}
                  placeholder={a.platform === "bluesky" ? "yourname.bsky.social" : "https://mastodon.social"}
                  value={form.a}
                  onChange={(e) => setForm({ ...form, a: e.target.value })}
                  autoComplete="off"
                />
                <input
                  className="input font-mono"
                  type="password"
                  aria-label={a.platform === "bluesky" ? "Bluesky app password" : "Mastodon access token"}
                  placeholder={a.platform === "bluesky" ? "app password: xxxx-xxxx-xxxx-xxxx" : "access token"}
                  value={form.b}
                  onChange={(e) => setForm({ ...form, b: e.target.value })}
                  autoComplete="off"
                />
                <div className="flex gap-2">
                  <button className="btn btn-primary" disabled={busy || !form.a || !form.b}>
                    <Link2 size={14} /> {busy ? "Checking…" : "Connect"}
                  </button>
                  <button type="button" className="btn" onClick={() => setOpen(null)}>Cancel</button>
                </div>
              </form>
            ) : (
              <div className="mt-2 flex items-center gap-2 text-xs text-[var(--color-mute)]">
                <span className="min-w-0 flex-1">{a.detail}</span>
                <button className="btn btn-primary !py-1 text-xs" onClick={() => { setOpen(a.platform); setForm({ a: "", b: "" }); }}>
                  <Link2 size={13} /> Connect
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-4">
        <div className="hud-label mb-1 text-[var(--color-mute)]">Draft only (copy &amp; post yourself)</div>
        <p className="mb-2 text-xs text-[var(--color-mute)]">
          These platforms charge for, or tightly restrict, posting from other apps. Your team still writes and checks posts for them; use <b>Copy text</b> and post in their app.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {others.map((a) => (
            <span key={a.platform} className="chip" title={a.detail}>{a.name} · {a.char_limit} chars</span>
          ))}
        </div>
      </div>
    </Section>
  );
}
