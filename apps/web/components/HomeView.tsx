"use client";

import { ArrowRight, CalendarClock, CheckCircle2, Circle, MessageSquare, PenLine, Send, ShieldCheck, Sparkles, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { ContentItem, SocialAccount } from "@/lib/types";
import { AgentGlyph, Section } from "./ui";

const STEPS = [
  { icon: MessageSquare, title: "1. Ask", text: "Type what you want in Command, like “EDITH, write a post about my new video”. Address an agent by name, or just talk to J.A.R.V.I.S." },
  { icon: Users, title: "2. The team works", text: "Agents draft, check rules and brand safety, research facts and stress-test the post. Every draft lands in Content." },
  { icon: ShieldCheck, title: "3. You approve", text: "In Content, read the exact text and choose Publish now, Schedule, or Copy text. Nothing is posted without you." },
  { icon: Send, title: "4. It goes out", text: "Bluesky and Mastodon post for real. Approved scheduled posts go out on their own at the right time while STARK OS is running." },
];

const QUICK = [
  { agent: "edith", label: "Write a post", text: "EDITH, write a friendly Bluesky post about " },
  { agent: "jarvis", label: "Plan my week", text: "JARVIS, plan a week of posts for Bluesky and Mastodon about " },
  { agent: "friday", label: "Check my mentions", text: "Friday, check my mentions and draft replies" },
  { agent: "jocasta", label: "What's trending?", text: "Jocasta, what is trending this week in " },
  { agent: "u", label: "Video idea", text: "U, turn my last post into a 30-second vertical video storyboard" },
  { agent: "ultron", label: "Could this backfire?", text: "Ultron, how could this post backfire: " },
];

/** Start page: how STARK OS works, what's left to set up, and one-click starting points. */
export function HomeView({ talkTo, go }: { talkTo: (agentId: string, text?: string) => void; go: (view: "content" | "models" | "team") => void }) {
  const { client, status, agents } = useStark();
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [items, setItems] = useState<ContentItem[]>([]);

  useEffect(() => {
    Promise.all([
      client.get<{ accounts: SocialAccount[] }>("/api/social/accounts"),
      client.get<{ items: ContentItem[] }>("/api/social/queue?limit=50"),
    ])
      .then(([a, q]) => {
        setAccounts(a.accounts);
        setItems(q.items);
      })
      .catch(() => {});
  }, [client]);

  const modelsOk = !!status && status.active_providers.length > 0;
  const connected = accounts.filter((a) => a.mode === "connected");
  const scheduled = items.filter((i) => i.status === "scheduled");
  const checklist = [
    { done: modelsOk, label: "Free AI models connected", hint: modelsOk ? "OpenRouter is working." : "Add OPENROUTER_API_KEY to .env and restart.", action: () => go("models") },
    {
      done: connected.length > 0,
      label: "Connect a social account",
      hint: connected.length ? `Live: ${connected.map((a) => a.connected_as || a.name).join(", ")}` : "Bluesky or Mastodon, two minutes, free. Other platforms work as drafts you copy.",
      action: () => go("content"),
    },
    { done: items.length > 0, label: "Create your first post", hint: items.length ? `${items.length} post(s) so far.` : "Ask E.D.I.T.H. to write one.", action: () => talkTo("edith", QUICK[0].text) },
    { done: scheduled.some((i) => i.auto_publish), label: "Schedule a post to go out on its own", hint: "In Content: Schedule → tick “Publish automatically”.", action: () => go("content") },
  ];
  const doneCount = checklist.filter((c) => c.done).length;

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="panel p-5">
        <div className="hud-label mb-1 text-cyan-300">Welcome</div>
        <h1 className="text-xl font-semibold">Your AI social media team</h1>
        <p className="mt-1 max-w-3xl text-sm text-[var(--color-mute)]">
          Seven agents write, check, research and schedule your posts. You stay in charge: every post is shown to you before it goes out, and everything runs on your computer with free AI models.
        </p>
        <div className="mt-4 grid gap-3 [&>*]:min-w-0 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <div key={s.title} className="rounded-lg border border-[var(--color-line)] bg-black/20 p-3">
              <s.icon size={18} className="mb-2 text-cyan-300" />
              <div className="text-sm font-semibold">{s.title}</div>
              <p className="mt-1 text-xs text-[var(--color-mute)]">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 lg:grid-cols-[1fr_1fr]">
        <Section title={`Setup · ${doneCount}/${checklist.length}`}>
          <ul className="space-y-2">
            {checklist.map((c) => (
              <li key={c.label}>
                <button className="flex w-full items-start gap-3 rounded-lg p-2 text-left transition hover:bg-white/5" onClick={c.action}>
                  {c.done ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-300" /> : <Circle size={18} className="mt-0.5 shrink-0 text-[var(--color-mute)]" />}
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm ${c.done ? "text-[var(--color-mute)] line-through" : "font-medium"}`}>{c.label}</span>
                    <span className="break-anywhere block text-xs text-[var(--color-mute)]">{c.hint}</span>
                  </span>
                  {!c.done && <ArrowRight size={14} className="mt-1 shrink-0 text-cyan-300" />}
                </button>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Start something">
          <div className="grid gap-2 sm:grid-cols-2">
            {QUICK.map((q) => {
              const a = agents.find((x) => x.id === q.agent);
              return (
                <button key={q.label} className="flex items-center gap-2 rounded-lg border border-[var(--color-line)] p-2.5 text-left text-sm transition hover:border-cyan-400/40 hover:bg-white/5" onClick={() => talkTo(q.agent, q.text)}>
                  {a ? <AgentGlyph icon={a.icon} color={a.color} size={22} /> : <PenLine size={18} />}
                  <span className="min-w-0">
                    <span className="block font-medium">{q.label}</span>
                    <span className="block truncate text-xs text-[var(--color-mute)]">{a?.name}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-[var(--color-mute)]">
            <Sparkles size={12} className="mr-1 inline" />
            Tip: tell J.A.R.V.I.S. your brand voice once (“remember: friendly, short, no slang”) and every agent will use it.
          </p>
        </Section>
      </div>

      <Section title="Who does what" right={<button className="btn !py-1 text-xs" onClick={() => go("team")}>All details</button>}>
        <div className="grid gap-2 [&>*]:min-w-0 sm:grid-cols-2 lg:grid-cols-4">
          {agents.map((a) => (
            <button key={a.id} className="flex items-start gap-2 rounded-lg p-2 text-left transition hover:bg-white/5" onClick={() => talkTo(a.id)}>
              <AgentGlyph icon={a.icon} color={a.color} size={24} />
              <span className="min-w-0">
                <span className="block text-sm font-semibold" style={{ color: a.color }}>{a.name}</span>
                <span className="block text-xs text-[var(--color-mute)]">{a.role}</span>
              </span>
            </button>
          ))}
        </div>
        {scheduled.length > 0 && (
          <p className="mt-3 text-xs text-[var(--color-mute)]">
            <CalendarClock size={12} className="mr-1 inline" />
            {scheduled.length} post(s) scheduled. Keep STARK OS running (make dev) so approved posts go out on time.
          </p>
        )}
      </Section>
    </div>
  );
}
