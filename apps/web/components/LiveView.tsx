"use client";

import { Activity, Brain, Cpu, Pause, Play, Radio, ShieldCheck, Wrench, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useStark } from "@/lib/store";
import type { Agent, StarkEvent } from "@/lib/types";
import { Typewriter } from "./fx/Typewriter";
import { AgentGlyph, Empty, Section, STATE_META, timeAgo } from "./ui";

const ACTIVE = new Set(["thinking", "executing", "waiting_approval", "collaborating", "listening"]);
const STREAM_TYPES = new Set(["task.created", "task.thought", "tool.call", "tool.result", "message", "approval.created", "approval.decided", "task.updated", "content.updated", "memory.created", "autopilot.run"]);

interface Line {
  key: string;
  ts: string;
  agent: string | null;
  icon: React.ElementType;
  tag: string;
  text: string;
  tone: "info" | "ok" | "warn" | "bad" | "think";
}

function describe(ev: StarkEvent, i: number): Line | null {
  const d = ev.data || {};
  const key = `${ev.ts}-${i}-${ev.type}`;
  switch (ev.type) {
    case "task.created":
      return { key, ts: ev.ts, agent: d.agent_id, icon: Zap, tag: "TASK", text: `New task: ${String(d.instruction || "").slice(0, 160)}`, tone: "info" };
    case "task.thought":
      return { key, ts: ev.ts, agent: d.agent_id, icon: Brain, tag: "THINK", text: String(d.text || "").replace(/\s+/g, " ").slice(0, 240), tone: "think" };
    case "tool.call":
      return { key, ts: ev.ts, agent: d.agent_id, icon: Wrench, tag: "TOOL", text: `${d.tool}${d.verdict && d.verdict !== "allow" ? ` · ${d.verdict}` : ""}`, tone: d.verdict === "deny" ? "bad" : "info" };
    case "tool.result":
      return { key, ts: ev.ts, agent: d.agent_id, icon: Cpu, tag: d.ok ? "RESULT" : "ERROR", text: `${d.tool}: ${String(d.summary || "").slice(0, 200)}${d.ms ? ` (${d.ms} ms)` : ""}`, tone: d.ok ? "ok" : "bad" };
    case "message":
      return { key, ts: ev.ts, agent: d.sender, icon: Radio, tag: "LINK", text: `${String(d.sender).toUpperCase()} → ${String(d.recipient).toUpperCase()} · ${String(d.type || "").toLowerCase().replace(/_/g, " ")}`, tone: "info" };
    case "approval.created":
      return { key, ts: ev.ts, agent: d.agent_id || null, icon: ShieldCheck, tag: "APPROVAL", text: `Waiting for you: ${String(d.action || "").slice(0, 160)}`, tone: "warn" };
    case "approval.decided":
      return { key, ts: ev.ts, agent: d.agent_id || null, icon: ShieldCheck, tag: "DECIDED", text: `${d.status || "decided"}: ${String(d.action || "").slice(0, 140)}`, tone: d.status === "approved" ? "ok" : "warn" };
    case "task.updated":
      if (d.status === "completed" || d.status === "failed")
        return { key, ts: ev.ts, agent: d.agent_id, icon: Activity, tag: d.status === "completed" ? "DONE" : "FAILED", text: String(d.status === "failed" ? d.error || "" : d.instruction || "").slice(0, 180), tone: d.status === "completed" ? "ok" : "bad" };
      return null;
    case "content.updated":
      return { key, ts: ev.ts, agent: d.created_by || null, icon: Zap, tag: "CONTENT", text: `${d.platform || "post"} ${d.status || "updated"}: ${String(d.text || "").slice(0, 120)}`, tone: "info" };
    case "memory.created":
      return { key, ts: ev.ts, agent: null, icon: Brain, tag: "MEMORY", text: `Stored in ${d.namespace}/${d.layer}`, tone: "info" };
    case "autopilot.run":
      return { key, ts: ev.ts, agent: "jarvis", icon: Zap, tag: "AUTOPILOT", text: `Campaign run: ${d.campaign || d.name || ""} ${d.created != null ? `· ${d.created} draft(s)` : ""}`, tone: "info" };
  }
  return null;
}

const TONE: Record<Line["tone"], string> = {
  info: "text-cyan-300",
  ok: "text-emerald-300",
  warn: "text-amber-300",
  bad: "text-red-300",
  think: "text-violet-300",
};

/** The agent mesh: agents on a ring around the core, with signals flying along every real message. */
function Mesh({ agents, flows }: { agents: Agent[]; flows: { id: string; from: string; to: string }[] }) {
  const size = 520;
  const c = size / 2;
  const r = 190;
  const pos: Record<string, { x: number; y: number }> = { user: { x: c, y: c } };
  agents.forEach((a, i) => {
    const ang = (i / Math.max(agents.length, 1)) * Math.PI * 2 - Math.PI / 2;
    pos[a.id] = { x: c + r * Math.cos(ang), y: c + r * Math.sin(ang) };
  });
  const activeCount = agents.filter((a) => ACTIVE.has(a.live?.status)).length;

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto w-full max-w-[560px]" role="img" aria-label={`Agent network: ${activeCount} agent(s) working`}>
      <defs>
        <radialGradient id="core-g" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.55} />
          <stop offset="60%" stopColor="#a78bfa" stopOpacity={0.12} />
          <stop offset="100%" stopColor="#a78bfa" stopOpacity={0} />
        </radialGradient>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {/* orbits */}
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--color-cyan)" strokeOpacity={0.14} strokeDasharray="2 6" className="orbit" />
      <circle cx={c} cy={c} r={r - 60} fill="none" stroke="var(--color-violet)" strokeOpacity={0.12} strokeDasharray="1 8" className="orbit-rev" />
      {/* spokes from the core to every agent */}
      {agents.map((a) => {
        const p = pos[a.id];
        const on = ACTIVE.has(a.live?.status);
        return <line key={`s-${a.id}`} x1={c} y1={c} x2={p.x} y2={p.y} stroke={a.color} strokeOpacity={on ? 0.55 : 0.12} strokeWidth={on ? 1.6 : 1} className={on ? "anim-dash" : ""} />;
      })}
      {/* signals: one glowing packet per real message, flying sender → recipient */}
      {flows.map((f) => {
        const a = pos[f.from] || pos.user;
        const b = pos[f.to] || pos.user;
        const color = agents.find((x) => x.id === f.from)?.color || "#22d3ee";
        const path = `M${a.x},${a.y} Q${c},${c} ${b.x},${b.y}`;
        return (
          <g key={f.id}>
            <path d={path} fill="none" stroke={color} strokeOpacity={0.35} strokeWidth={1.2}>
              <animate attributeName="stroke-opacity" from="0.6" to="0" dur="2.4s" fill="freeze" />
            </path>
            <circle r={5} fill={color} filter="url(#glow)">
              <animateMotion dur="1.2s" path={path} fill="freeze" />
              <animate attributeName="opacity" values="1;1;0" keyTimes="0;0.85;1" dur="1.4s" fill="freeze" />
            </circle>
          </g>
        );
      })}
      {/* core */}
      <circle cx={c} cy={c} r={70} fill="url(#core-g)" className={activeCount ? "anim-breathe" : ""} />
      <g className="orbit">
        <circle cx={c} cy={c} r={44} fill="none" stroke="var(--color-cyan)" strokeOpacity={0.5} strokeDasharray="30 12 4 12" strokeWidth={1.5} />
      </g>
      <g className="orbit-rev">
        <circle cx={c} cy={c} r={34} fill="none" stroke="var(--color-violet)" strokeOpacity={0.6} strokeDasharray="8 6" />
      </g>
      <circle cx={c} cy={c} r={22} fill="var(--color-panel)" stroke="var(--color-cyan)" strokeOpacity={0.7} />
      <text x={c} y={c - 2} textAnchor="middle" fontSize="9" letterSpacing="2" fill="var(--color-ink)">
        CORE
      </text>
      <text x={c} y={c + 10} textAnchor="middle" fontSize="8" fill="var(--color-cyan)">
        {activeCount ? `${activeCount} active` : "standby"}
      </text>
      {/* agents */}
      {agents.map((a) => {
        const p = pos[a.id];
        const st = a.live?.status || "idle";
        const on = ACTIVE.has(st);
        const meta = STATE_META[st] || STATE_META.idle;
        return (
          <g key={a.id}>
            {on && <circle cx={p.x} cy={p.y} r={28} fill="none" stroke={a.color} strokeWidth={2} className="ripple" />}
            <circle cx={p.x} cy={p.y} r={28} fill="var(--color-panel)" stroke={a.color} strokeOpacity={on ? 1 : 0.4} strokeWidth={on ? 2 : 1} filter={on ? "url(#glow)" : undefined} />
            <foreignObject x={p.x - 14} y={p.y - 14} width={28} height={28}>
              <AgentGlyph icon={a.icon} color={a.color} size={28} active={on} />
            </foreignObject>
            <text x={p.x} y={p.y + 44} textAnchor="middle" fontSize="11" fontWeight={600} letterSpacing="1.5" fill={a.color}>
              {a.name}
            </text>
            <text x={p.x} y={p.y + 57} textAnchor="middle" fontSize="9" fill={meta.color}>
              {meta.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Live: what the team is doing right now, as it happens. */
export function LiveView({ openTask }: { openTask: (id: string) => void }) {
  const { agents, events, tasks, approvals, sseConnected, status } = useStark();
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<StarkEvent[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!paused) setFrozen(events);
  }, [events, paused]);

  const lines = useMemo(() => {
    const out: Line[] = [];
    frozen.forEach((ev, i) => {
      if (!STREAM_TYPES.has(ev.type)) return;
      const l = describe(ev, i);
      if (l && (filter === "all" || l.agent === filter)) out.push(l);
    });
    return out.reverse().slice(0, 80);
  }, [frozen, filter]);

  // messages from the last few seconds become flying signals on the mesh
  const flows = useMemo(
    () =>
      events
        .map((ev, i) => ({ ev, i }))
        .filter(({ ev }) => (ev.type === "message" || ev.type === "task.created") && now - new Date(ev.ts).getTime() < 6000)
        .map(({ ev, i }) =>
          ev.type === "message"
            ? { id: `${ev.ts}-${i}`, from: String(ev.data.sender), to: String(ev.data.recipient) }
            : { id: `${ev.ts}-${i}`, from: String(ev.data.requested_by === "user" ? "user" : ev.data.requested_by || "user"), to: String(ev.data.agent_id) },
        )
        .slice(-24),
    [events, now],
  );

  const running = tasks.filter((t) => ["thinking", "executing", "collaborating", "waiting_approval", "queued"].includes(t.status));
  const fiveMin = events.filter((e) => now - new Date(e.ts).getTime() < 300000);
  const stats = [
    { label: "Agents active", value: agents.filter((a) => ACTIVE.has(a.live?.status)).length, of: agents.length, color: "#22d3ee" },
    { label: "Tasks running", value: running.length, color: "#a78bfa" },
    { label: "Tool calls · 5 min", value: fiveMin.filter((e) => e.type === "tool.call").length, color: "#f472b6" },
    { label: "Agent messages · 5 min", value: fiveMin.filter((e) => e.type === "message").length, color: "#34d399" },
    { label: "Waiting for you", value: approvals.length, color: "#fbbf24" },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel overflow-hidden p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="hud-label text-cyan-300">Neural operations</div>
            <h1 className="holo-text text-xl font-semibold">Live agent activity</h1>
          </div>
          <span className="chip ml-auto">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${sseConnected ? "bg-emerald-400 anim-pulse" : "bg-red-400"}`} />
            {sseConnected ? "Streaming" : "Reconnecting"}
          </span>
          {status && <span className="chip">Mode: {status.mode.replace("_", " ")}</span>}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {stats.map((s) => (
            <div key={s.label} className="rounded-lg border border-[var(--color-line)] bg-black/10 p-3">
              <div className="stat-glow font-mono text-2xl font-semibold" style={{ color: s.color }}>
                {s.value}
                {s.of != null && <span className="text-sm text-[var(--color-mute)]">/{s.of}</span>}
              </div>
              <div className="hud-label mt-1 text-[var(--color-mute)]">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.1fr_1fr]">
        <Section title="Agent network">
          <Mesh agents={agents} flows={flows} />
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {agents
              .filter((a) => ACTIVE.has(a.live?.status))
              .map((a) => (
                <button key={a.id} onClick={() => a.live.task_id && openTask(a.live.task_id)} className="shimmer flex items-center gap-2 rounded-lg border border-[var(--color-line)] p-2 text-left text-xs">
                  <AgentGlyph icon={a.icon} color={a.color} size={18} active />
                  <span className="min-w-0">
                    <span className="font-semibold" style={{ color: a.color }}>{a.name}</span>{" "}
                    <span className="text-[var(--color-mute)]">{(STATE_META[a.live.status] || STATE_META.idle).label.toLowerCase()}</span>
                    <span className="block truncate text-[var(--color-ink)]">{a.live.detail}</span>
                  </span>
                </button>
              ))}
          </div>
          {!agents.some((a) => ACTIVE.has(a.live?.status)) && <p className="mt-2 text-center text-xs text-[var(--color-mute)]">The team is on standby. Give J.A.R.V.I.S. a task in Command and watch it spread across the network.</p>}
        </Section>

        <Section
          title="Neural stream"
          right={
            <div className="flex items-center gap-2">
              <select aria-label="Filter by agent" className="input !w-auto !py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="all">All agents</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <button className="btn !py-1 text-xs" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
                {paused ? <Play size={12} /> : <Pause size={12} />}
                {paused ? "Resume" : "Pause"}
              </button>
            </div>
          }
        >
          {lines.length === 0 ? (
            <Empty>No activity yet. Events appear here the moment an agent thinks, calls a tool or messages a teammate.</Empty>
          ) : (
            <ol className="max-h-[620px] space-y-1.5 overflow-y-auto pr-1 font-mono text-[12px]" aria-live="off">
              {lines.map((l, idx) => {
                const a = l.agent ? agents.find((x) => x.id === l.agent) : undefined;
                const Icon = l.icon;
                return (
                  <li key={l.key} className="flex gap-2 rounded-md border border-transparent px-2 py-1.5 hover:border-[var(--color-line)]" style={{ animation: idx === 0 ? "stark-rise .35s ease-out both" : undefined }}>
                    <Icon size={13} className={`mt-0.5 shrink-0 ${TONE[l.tone]}`} />
                    <span className="min-w-0 flex-1">
                      <span className={`mr-1.5 text-[10px] tracking-widest ${TONE[l.tone]}`}>{l.tag}</span>
                      {a && (
                        <span className="mr-1.5 font-semibold" style={{ color: a.color }}>
                          {a.name}
                        </span>
                      )}
                      <span className="break-anywhere text-[var(--color-ink)]">{idx === 0 && !paused ? <Typewriter text={l.text} /> : l.text}</span>
                    </span>
                    <span className="shrink-0 text-[10px] text-[var(--color-mute)]">{timeAgo(l.ts)}</span>
                  </li>
                );
              })}
            </ol>
          )}
        </Section>
      </div>
    </div>
  );
}
