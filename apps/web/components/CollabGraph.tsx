"use client";

import type { Agent, AgentMessage, Task } from "@/lib/types";
import { AgentGlyph } from "./ui";

/** Agents on a ring; edges are the real messages exchanged inside one task tree. */
export function CollabGraph({ agents, messages, tree }: { agents: Agent[]; messages: AgentMessage[]; tree: Task[] }) {
  const size = 340;
  const c = size / 2;
  const r = 128;
  const pos: Record<string, { x: number; y: number }> = {};
  agents.forEach((a, i) => {
    const ang = (i / agents.length) * Math.PI * 2 - Math.PI / 2;
    pos[a.id] = { x: c + r * Math.cos(ang), y: c + r * Math.sin(ang) };
  });
  pos.user = { x: c, y: c };

  const edges = new Map<string, { from: string; to: string; count: number; types: Set<string> }>();
  for (const m of messages) {
    if (!pos[m.sender] || !pos[m.recipient] || m.sender === m.recipient) continue;
    const key = [m.sender, m.recipient].sort().join("|");
    const e = edges.get(key) || { from: m.sender, to: m.recipient, count: 0, types: new Set<string>() };
    e.count++;
    e.types.add(m.type);
    edges.set(key, e);
  }
  const running = new Set(tree.filter((t) => ["thinking", "executing", "collaborating", "waiting_approval", "queued"].includes(t.status)).map((t) => t.agent_id));
  const involved = new Set(tree.map((t) => t.agent_id));

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto w-full max-w-[360px]" role="img" aria-label="Agent collaboration graph">
      <circle cx={c} cy={c} r={r} fill="none" stroke="rgba(34,211,238,0.08)" strokeDasharray="2 5" />
      {[...edges.values()].map((e) => {
        const a = pos[e.from];
        const b = pos[e.to];
        const live = running.has(e.from) || running.has(e.to);
        const failed = e.types.has("TASK_FAILED");
        return (
          <g key={`${e.from}-${e.to}`}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={failed ? "#f87171" : "#22d3ee"} strokeOpacity={0.55} strokeWidth={Math.min(1 + e.count * 0.4, 4)} className={live ? "anim-dash" : ""} />
            <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} fill="#7d8d99" fontSize="9" textAnchor="middle">
              {e.count}
            </text>
          </g>
        );
      })}
      <circle cx={c} cy={c} r={16} fill="#0b1015" stroke="rgba(34,211,238,0.4)" />
      <text x={c} y={c + 3} fill="#d7e3ea" fontSize="9" textAnchor="middle">
        USER
      </text>
      {agents.map((a) => {
        const p = pos[a.id];
        const on = involved.has(a.id);
        return (
          <g key={a.id} opacity={on ? 1 : 0.3}>
            <circle cx={p.x} cy={p.y} r={22} fill="#0b1015" stroke={a.color} strokeOpacity={running.has(a.id) ? 1 : 0.5} strokeWidth={running.has(a.id) ? 2 : 1} className={running.has(a.id) ? "anim-pulse" : ""} style={{ transformOrigin: `${p.x}px ${p.y}px` }} />
            <foreignObject x={p.x - 11} y={p.y - 11} width={22} height={22}>
              <AgentGlyph icon={a.icon} color={a.color} size={22} />
            </foreignObject>
            <text x={p.x} y={p.y + 36} fill={a.color} fontSize="9.5" textAnchor="middle" letterSpacing="1">
              {a.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
