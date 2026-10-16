"use client";

import type { AgentState } from "@/lib/types";

/** Original geometric glyphs for each agent (no Marvel artwork). */
export function AgentGlyph({ icon, color, size = 28, active = false }: { icon: string; color: string; size?: number; active?: boolean }) {
  const s = size;
  const common = { fill: "none", stroke: color, strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const shapes: Record<string, React.ReactNode> = {
    core: (
      <>
        <circle cx="16" cy="16" r="12" {...common} opacity={0.5} />
        <circle cx="16" cy="16" r="7" {...common} />
        <circle cx="16" cy="16" r="2.5" fill={color} />
        <path d="M16 2v4M16 26v4M2 16h4M26 16h4" {...common} opacity={0.7} />
      </>
    ),
    pulse: (
      <>
        <rect x="3" y="5" width="26" height="22" rx="5" {...common} opacity={0.5} />
        <path d="M5 17h6l3-7 4 13 3-6h6" {...common} />
      </>
    ),
    shield: (
      <>
        <path d="M16 3l11 4v8c0 7-5 12-11 14C10 27 5 22 5 15V7z" {...common} />
        <path d="M11 16l4 4 6-8" {...common} />
      </>
    ),
    triangle: (
      <>
        <path d="M16 3l13 24H3z" {...common} />
        <path d="M16 12v7" {...common} />
        <circle cx="16" cy="23" r="1.2" fill={color} />
      </>
    ),
    book: (
      <>
        <path d="M4 7c4-2 8-2 12 1 4-3 8-3 12-1v18c-4-2-8-2-12 1-4-3-8-3-12-1z" {...common} />
        <path d="M16 8v18" {...common} opacity={0.6} />
      </>
    ),
    arm: (
      <>
        <path d="M5 27h12M9 27l3-8 8-6 5 3" {...common} />
        <circle cx="12" cy="19" r="2" {...common} />
        <circle cx="20" cy="13" r="2" {...common} />
        <path d="M25 16l3-3M25 16l2 4" {...common} />
      </>
    ),
    spark: (
      <>
        <path d="M16 3l3 10 10 3-10 3-3 10-3-10-10-3 10-3z" {...common} />
      </>
    ),
  };
  return (
    <svg width={s} height={s} viewBox="0 0 32 32" aria-hidden className={active ? "drop-shadow-[0_0_6px_currentColor]" : ""} style={{ color }}>
      {shapes[icon] || <circle cx="16" cy="16" r="10" {...common} />}
    </svg>
  );
}

export const STATE_META: Record<string, { label: string; color: string; animated: boolean }> = {
  idle: { label: "Idle", color: "#5b6b77", animated: false },
  listening: { label: "Listening", color: "#22d3ee", animated: true },
  thinking: { label: "Thinking", color: "#a78bfa", animated: true },
  executing: { label: "Executing", color: "#22d3ee", animated: true },
  waiting_approval: { label: "Waiting for approval", color: "#fbbf24", animated: true },
  collaborating: { label: "Collaborating", color: "#f472b6", animated: true },
  completed: { label: "Completed", color: "#34d399", animated: false },
  failed: { label: "Failed", color: "#f87171", animated: false },
};

export function StateBadge({ state }: { state: AgentState | string }) {
  const m = STATE_META[state] || STATE_META.idle;
  return (
    <span className="chip" style={{ borderColor: `${m.color}55`, color: m.color }}>
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${m.animated ? "anim-pulse" : ""}`} style={{ background: m.color }} />
      {m.label}
    </span>
  );
}

const TASK_COLORS: Record<string, string> = {
  queued: "#7d8d99",
  thinking: "#a78bfa",
  executing: "#22d3ee",
  waiting_approval: "#fbbf24",
  collaborating: "#f472b6",
  completed: "#34d399",
  failed: "#f87171",
  cancelled: "#7d8d99",
};

export function TaskStatus({ status }: { status: string }) {
  const c = TASK_COLORS[status] || "#7d8d99";
  const live = ["thinking", "executing", "waiting_approval", "collaborating", "queued"].includes(status);
  return (
    <span className="chip" style={{ borderColor: `${c}55`, color: c }}>
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${live ? "anim-pulse" : ""}`} style={{ background: c }} />
      {status.replace("_", " ")}
    </span>
  );
}

const AVAIL: Record<string, { label: string; color: string }> = {
  implemented: { label: "Implemented", color: "#34d399" },
  simulated: { label: "Simulated", color: "#fbbf24" },
  requires_credentials: { label: "Requires credentials", color: "#f472b6" },
  requires_hardware: { label: "Requires hardware", color: "#f472b6" },
  unavailable: { label: "Unavailable", color: "#f87171" },
};

export function AvailabilityChip({ value }: { value: string }) {
  const m = AVAIL[value] || { label: value, color: "#7d8d99" };
  return (
    <span className="chip" style={{ borderColor: `${m.color}55`, color: m.color }}>
      {m.label}
    </span>
  );
}

export function RiskChip({ risk }: { risk: string }) {
  const color = { read: "#7d8d99", memory: "#60a5fa", delegation: "#a78bfa", write: "#fbbf24", external: "#f472b6", sensitive: "#fb923c", physical: "#f87171", destructive: "#ef4444" }[risk] || "#7d8d99";
  return (
    <span className="chip" style={{ borderColor: `${color}55`, color }}>
      {risk}
    </span>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-10 text-center text-sm text-[var(--color-mute)]">{children}</div>;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 5) return "just now";
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function duration(a: string | null, b: string | null): string {
  if (!a) return "";
  const ms = (b ? new Date(b).getTime() : Date.now()) - new Date(a).getTime();
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function Section({ title, right, children, className = "" }: { title: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel p-4 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="panel-title">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}
